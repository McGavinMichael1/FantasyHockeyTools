# Deployment and Luck Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add power-play ice time (deployment) and split PDO (luck) features to the pickup/cooling models and the draft ranker, each behind its own retrain gate.

**Architecture:** MoneyPuck's per-situation game rows already carry both families — `icetime` on the `5on4` row is PP TOI, and the `OnIce_F_*`/`OnIce_A_*` counts on the `5on5` row are PDO's ingredients. Both get merged onto the `all` row inside `fantasyPoints.moneypuckGamePoints`, using the same mechanism that already attaches PPP. Downstream, `mlFeatures.buildRollingFeatures` derives rolling levels and trend deltas for the pickup models, and `moneypuck.buildPlayerSeasons` → `features/draft.py` derives season rates and a luck *residual* for the draft ranker.

**Tech Stack:** Python 3, pandas, XGBoost, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-deployment-and-luck-features-design.md`

## Global Constraints

- **Always invoke `.\.venv\Scripts\python.exe` explicitly.** System `python` on this machine may resolve to an unrelated interpreter.
- **No new dependencies.** Nothing in this plan needs one; adding one triggers the `fht-quality-gates` class (f) freeze-the-pins gate.
- **Splits are season-based, never random rows.** Do not touch `src/season.py`. Pickups: train ≤2022, val 2023. Draft: train ≤2021, val 2022–2023.
- **The 2024 draft test season stays untouched.** `season.DRAFT_TEST_SEASON` is referenced nowhere in this plan and must stay that way.
- **Every on-ice percentage is a ratio of rolling sums, never a rolling mean of per-game ratios.** See spec §3.1. This is the one detail that decides whether the PDO work produces signal or noise.
- **Summed PDO is never a model feature.** It ships named outside the `rolling_` prefix so `pickupFeatureCols`' allowlist does not enrol it.
- **PP TOI and PDO get separate retrain gates.** Never land both and retrain once — the result cannot be attributed.
- **Model `.pkl` files and everything under `data/` are gitignored.** Never `git add` them. After any task that writes one, confirm `git status` is clean of them.
- **Test style:** hand-computed expected values in a comment above the assertion, matching `tests/test_fantasyPoints.py`.
- Full suite must be green before every commit: `.\.venv\Scripts\python.exe -m pytest -q` — baseline is **174 passed, 0 failed**.

---

### Task 1: Pre-registration and baseline capture

Nothing is implemented in this task. It exists because `fht-research-frontier` methodology (a) requires the predicted deltas to be written down *before* any number exists to be rationalized against, and because the draft model's current val Spearman is recorded nowhere.

**Files:**
- Modify: `PROJECT-PLAN.md` (Learning Log section, append a new dated entry)

- [ ] **Step 1: Capture the current draft baseline**

The pickup/cooling numbers are already recorded in `fht-quality-gates` §3. The draft numbers are not. Run:

```powershell
.\.venv\Scripts\python.exe main.py train-draft
```

Copy these four printed lines verbatim — they are the numbers Task 10 must beat:
- `Baseline A (last-season FP/g): val Spearman ..., MAE ...`
- `Baseline B (fp_w3 weighted): val Spearman ..., MAE ...`
- `XGBoost: val Spearman ..., MAE ...`
- The `GATE B3:` verdict line

- [ ] **Step 2: Write the pre-registration into PROJECT-PLAN.md**

Append to the Learning Log, filling in the four captured draft numbers:

```markdown
### 2026-08-24 — Deployment and luck features (pre-registration)

Predictions written BEFORE training, per fht-research-frontier methodology (a).
Plan: docs/superpowers/plans/2026-08-24-deployment-and-luck-features.md

Baselines to beat:
- Pickup val Spearman 0.6214 / AUC-equiv 0.8465
- Cooling val Spearman 0.6063 / AUC-equiv 0.7673
- Spot-check top-15 per date 67/60/47/53/47 (mean 55%); 25 sim adds 60% hit,
  2.83 FP/g vs chaser 40% / 2.35 FP/g
- Draft Baseline A val Spearman <FILL IN>, Baseline B <FILL IN>,
  current XGBoost <FILL IN>, gate verdict <FILL IN>

Predictions:
1. PP TOI helps the PICKUP model more than cooling. Expect pickup spot-check
   top-15 mean +3 to +8 points (55% -> 58-63%); cooling roughly flat.
2. PDO helps the COOLING model more than pickups. Cooling is the weaker model
   and "running hot, due to regress" is exactly what an on-ice shooting-%
   residual measures. Expect cooling val Spearman +0.01 to +0.03; pickup
   spot-check within noise of whatever PP TOI leaves it at.
3. On-ice SAVE % lands in the bottom half of reports/pickup_feature_importance.png.
   It reaches fantasy points only through plus/minus, which moneypuckGamePoints
   does not compute.
4. rolling_delta_5_20_pp_toi_share outranks rolling_5_powerPlayIcetime in
   feature importance -- the promotion is the signal, not the level.
5. Draft: onice_sh_luck's standardized Ridge coefficient is NEGATIVE. A positive
   one means the residual is acting as a talent proxy and the feature is wrong.
6. Draft val Spearman moves by less than +0.01. Season-level luck residuals are
   a small correction to a target already dominated by fpPerGame; a large jump
   would be more suspicious than encouraging.

If a prediction is wrong, that is a recorded result, not a reason to re-cut the
metric.
```

- [ ] **Step 3: Commit**

```powershell
git add PROJECT-PLAN.md docs/superpowers/specs/2026-08-24-deployment-and-luck-features-design.md docs/superpowers/plans/2026-08-24-deployment-and-luck-features.md
git commit -m "docs: pre-register the deployment and luck feature experiment"
```

---

### Task 2: Widen GAME_COLUMNS and version the game-log cache

PDO needs five MoneyPuck columns the pipeline does not currently read. Widening `GAME_COLUMNS` alone is a trap: `loadGameLogs` serves the existing Parquet cache whenever it is newer than the current CSV, so the first run after this change would happily serve a cache written with the *old* column set and then fail downstream with a `KeyError` that looks like a code bug. Versioning the cache filename makes this class of change self-invalidating forever.

**Files:**
- Modify: `src/moneypuck.py:32-39` (GAME_COLUMNS), `src/moneypuck.py:100-139` (loadGameLogs)
- Test: `tests/test_moneypuck.py`

**Interfaces:**
- Produces: `moneypuck.GAME_CACHE_VERSION` (str), `moneypuck.gameCachePath(min_season) -> str`, and five new columns available on every row returned by `loadGameLogs`: `OnIce_F_goals`, `OnIce_F_shotsOnGoal`, `OnIce_F_xGoals`, `OnIce_A_goals`, `OnIce_A_shotsOnGoal`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_moneypuck.py` (the existing `_game_row` helper builds rows from `GAME_COLUMNS`, so it picks up the new columns automatically):

```python
def test_game_columns_include_the_on_ice_pdo_ingredients():
    # PDO needs on-ice goals and shots, for and against, plus the xGoals
    # denominator for the shot-quality-adjusted version.
    for col in ['OnIce_F_goals', 'OnIce_F_shotsOnGoal', 'OnIce_F_xGoals',
                'OnIce_A_goals', 'OnIce_A_shotsOnGoal']:
        assert col in moneypuck.GAME_COLUMNS


def test_cache_path_is_versioned_so_column_changes_invalidate_it():
    # A cache written with an older GAME_COLUMNS must not be served to code
    # expecting the newer set. The version tag in the filename is what makes
    # that impossible rather than merely unlikely.
    path = moneypuck.gameCachePath(2020)
    assert moneypuck.GAME_CACHE_VERSION in os.path.basename(path)
    assert path.endswith('.parquet')
    assert moneypuck.gameCachePath(2008) != moneypuck.gameCachePath(2020)
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moneypuck.py -q
```
Expected: FAIL — `AttributeError: module 'src.moneypuck' has no attribute 'gameCachePath'`, and the GAME_COLUMNS assertion fails.

- [ ] **Step 3: Widen GAME_COLUMNS**

Replace `src/moneypuck.py:32-39` with:

```python
GAME_COLUMNS = [
    'playerId', 'name', 'gameId', 'season', 'gameDate', 'position', 'situation',
    'icetime', 'gameScore',
    'onIce_corsiPercentage', 'onIce_fenwickPercentage',
    'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_points',
    'I_F_xGoals', 'I_F_shotsOnGoal', 'I_F_hits', 'shotsBlockedByPlayer',
    'I_F_oZoneShiftStarts', 'I_F_dZoneShiftStarts', 'I_F_highDangerShots',
    # On-ice goals and shots, for and against -- PDO's four ingredients, plus
    # the xGoals denominator for the shot-quality-adjusted version. Read off
    # the 5on5 rows only; see fantasyPoints.moneypuckGamePoints for why.
    'OnIce_F_goals', 'OnIce_F_shotsOnGoal', 'OnIce_F_xGoals',
    'OnIce_A_goals', 'OnIce_A_shotsOnGoal',
]

# Bump whenever GAME_COLUMNS changes. The cache filename carries this tag so a
# cache written with an older column set can never be served to code expecting
# the newer one -- loadGameLogs prefers a fresh-looking cache over the raw
# files, so without the tag a widened GAME_COLUMNS fails downstream with a
# KeyError that looks like a code bug.
GAME_CACHE_VERSION = 'v2'
```

- [ ] **Step 4: Add gameCachePath and use it in loadGameLogs**

Insert after `writeCache` (around `src/moneypuck.py:74`):

```python
def gameCachePath(min_season):
    """Default on-disk cache path for loadGameLogs at a given min_season."""
    return os.path.join(
        PROCESSED_DIR, f'moneypuck_games_{GAME_CACHE_VERSION}_{min_season}.parquet')
```

Then in `loadGameLogs`, replace:

```python
    if cache_file is None:
        cache_file = os.path.join(PROCESSED_DIR, f'moneypuck_games_{min_season}.parquet')
```

with:

```python
    if cache_file is None:
        cache_file = gameCachePath(min_season)
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moneypuck.py -q
```
Expected: PASS.

- [ ] **Step 6: Delete the orphaned v1 caches**

The old cache files are now unreachable dead weight (54 MB). They are gitignored, so this only touches the working tree:

```powershell
Remove-Item d:\repos\FantasyHockeyTools\data\processed\moneypuck_games_2008.parquet -ErrorAction SilentlyContinue
Remove-Item d:\repos\FantasyHockeyTools\data\processed\moneypuck_games_2020.parquet -ErrorAction SilentlyContinue
```

- [ ] **Step 7: Rebuild the 2020 cache and confirm the new columns arrive**

This reads the 2.6 GB history file — expect several minutes and a "Loading MoneyPuck data from…" print. Per `fht-debugging-playbook`, that is expected, not a hang; do not kill it.

```powershell
.\.venv\Scripts\python.exe -c "from src import moneypuck; df = moneypuck.loadGameLogs(min_season=2020); print(df.shape); print(df[['OnIce_F_goals','OnIce_F_shotsOnGoal','OnIce_A_goals','OnIce_A_shotsOnGoal','OnIce_F_xGoals']].sum())"
```

Expected: a shape with 27 columns, and five non-zero sums. **All-zero sums mean the wrong columns were read** — stop and check the header names against `data/raw/moneypuck_current.csv` before continuing.

- [ ] **Step 8: Full suite, then commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -c "import main"
git status --short
git add src/moneypuck.py tests/test_moneypuck.py
git commit -m "feat: read on-ice goal/shot counts and version the game-log cache"
```

`git status --short` must show no `data/` or `models/` entries. If it does, they are not gitignored as expected — stop and fix `.gitignore` before committing.

---

### Task 3: Attach PP ice time and 5on5 on-ice counts to each player-game

Both feature families need per-situation values merged onto the one-row-per-player-game frame. `moneypuckGamePoints` already does exactly this for PPP and the PP goal/assist breakdown; this task extends it with two more merges of the same shape. The fantasy-point value itself is untouched, and a test pins that.

**Files:**
- Modify: `src/fantasyPoints.py:44-87`
- Test: `tests/test_fantasyPoints.py`, `tests/test_moneypuck.py`

**Interfaces:**
- Consumes: the five `OnIce_*` columns from Task 2.
- Produces: six new columns on every `moneypuckGamePoints` output row — `powerPlayIcetime`, `ev_onIce_goalsFor`, `ev_onIce_shotsFor`, `ev_onIce_xGoalsFor`, `ev_onIce_goalsAgainst`, `ev_onIce_shotsAgainst`. Also the module constant `fantasyPoints.EV_ONICE_COLUMNS` (dict mapping MoneyPuck name → output name).

- [ ] **Step 1: Update both test row helpers**

The merges read `icetime` and the `OnIce_*` columns, so any test frame lacking them will now raise `KeyError`. Update the helpers first.

In `tests/test_fantasyPoints.py`, replace `_moneypuck_row` (lines 7-20) with:

```python
def _moneypuck_row(playerId, gameId, situation, goals=0, pA=0, sA=0,
                   sog=0, hits=0, blocks=0, points=0, icetime=0,
                   onice_gf=0, onice_sf=0, onice_xgf=0.0,
                   onice_ga=0, onice_sa=0):
    return {
        'playerId': playerId,
        'gameId': gameId,
        'situation': situation,
        'icetime': icetime,
        'I_F_goals': goals,
        'I_F_primaryAssists': pA,
        'I_F_secondaryAssists': sA,
        'I_F_shotsOnGoal': sog,
        'I_F_hits': hits,
        'shotsBlockedByPlayer': blocks,
        'I_F_points': points,
        'OnIce_F_goals': onice_gf,
        'OnIce_F_shotsOnGoal': onice_sf,
        'OnIce_F_xGoals': onice_xgf,
        'OnIce_A_goals': onice_ga,
        'OnIce_A_shotsOnGoal': onice_sa,
    }
```

In `tests/test_moneypuck.py`, add the five on-ice keys to `_pickup_row`'s returned dict (it already passes `icetime`). Replace its signature and return with:

```python
def _pickup_row(playerId, gameId, gameDate, situation='all', season=2025,
                name='Player One', position='C', icetime=1200,
                goals=0, pA=0, sA=0, sog=0, hits=0, blocks=0, points=0,
                onice_gf=0, onice_sf=0, onice_xgf=0.0,
                onice_ga=0, onice_sa=0):
    """Minimal full-situation game-log row for buildPickupStats tests."""
    return {
        'playerId': playerId, 'gameId': gameId, 'gameDate': gameDate,
        'season': season, 'name': name, 'position': position,
        'situation': situation, 'icetime': icetime,
        'I_F_goals': goals, 'I_F_primaryAssists': pA,
        'I_F_secondaryAssists': sA, 'I_F_shotsOnGoal': sog,
        'I_F_hits': hits, 'shotsBlockedByPlayer': blocks,
        'I_F_points': points,
        'OnIce_F_goals': onice_gf, 'OnIce_F_shotsOnGoal': onice_sf,
        'OnIce_F_xGoals': onice_xgf, 'OnIce_A_goals': onice_ga,
        'OnIce_A_shotsOnGoal': onice_sa,
    }
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_fantasyPoints.py`:

```python
def test_moneypuck_game_points_carries_power_play_icetime():
    # PP TOI is the 5on4 row's icetime, merged onto the 'all' row. The 'all'
    # row's icetime (1080s) is total ice time and must not be overwritten.
    df = pd.DataFrame([
        _moneypuck_row(1, 100, 'all', goals=1, points=1, icetime=1080),
        _moneypuck_row(1, 100, '5on4', points=1, icetime=180),
        _moneypuck_row(1, 100, '4on5', icetime=90),
    ])
    row = fantasyPoints.moneypuckGamePoints(df).iloc[0]
    assert row['powerPlayIcetime'] == 180
    assert row['icetime'] == 1080


def test_moneypuck_game_points_on_ice_counts_come_from_5on5_only():
    # PDO is an even-strength stat. The 'all' row's on-ice counts include
    # power-play time, which would turn a luck feature into a deployment
    # proxy -- so only the 5on5 row's counts are carried through.
    df = pd.DataFrame([
        _moneypuck_row(1, 100, 'all', onice_gf=3, onice_sf=25,
                       onice_ga=2, onice_sa=20, onice_xgf=2.5),
        _moneypuck_row(1, 100, '5on5', onice_gf=1, onice_sf=18,
                       onice_ga=2, onice_sa=17, onice_xgf=1.4),
        _moneypuck_row(1, 100, '5on4', onice_gf=2, onice_sf=7,
                       onice_ga=0, onice_sa=3, onice_xgf=1.1),
    ])
    row = fantasyPoints.moneypuckGamePoints(df).iloc[0]
    assert row['ev_onIce_goalsFor'] == 1
    assert row['ev_onIce_shotsFor'] == 18
    assert row['ev_onIce_goalsAgainst'] == 2
    assert row['ev_onIce_shotsAgainst'] == 17
    assert row['ev_onIce_xGoalsFor'] == pytest.approx(1.4)


def test_moneypuck_game_points_missing_situations_give_zero_not_nan():
    # A player with no 5on4 and no 5on5 row that game gets zeros, so
    # downstream rolling sums never silently propagate NaN.
    df = pd.DataFrame([_moneypuck_row(2, 100, 'all', goals=1, points=1, icetime=600)])
    row = fantasyPoints.moneypuckGamePoints(df).iloc[0]
    assert row['powerPlayIcetime'] == 0
    assert row['ev_onIce_goalsFor'] == 0
    assert row['ev_onIce_shotsAgainst'] == 0


def test_moneypuck_game_points_value_is_unchanged_by_the_new_columns():
    # Same fixture as test_moneypuck_game_points_with_special_teams:
    # FP = 3*1 + 2*(1+1) + 0.15*4 + 0.15*2 + 0.35*1 + 1*2 + 1*1 = 11.25
    # Adding deployment/luck columns must not move the scoring path at all.
    df = pd.DataFrame([
        _moneypuck_row(1, 100, 'all', goals=1, pA=1, sA=1, sog=4, hits=2,
                       blocks=1, points=3, icetime=1080, onice_gf=3, onice_sf=25),
        _moneypuck_row(1, 100, '5on4', goals=1, pA=1, points=2, icetime=180),
        _moneypuck_row(1, 100, '4on5', points=1, icetime=90),
        _moneypuck_row(1, 100, '5on5', points=1, icetime=810, onice_gf=1, onice_sf=18),
    ])
    row = fantasyPoints.moneypuckGamePoints(df).iloc[0]
    assert row['fantasyPoints'] == pytest.approx(11.25)
```

- [ ] **Step 3: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fantasyPoints.py -q
```
Expected: FAIL — `KeyError: 'powerPlayIcetime'` on the new tests. The four pre-existing tests must still PASS after the helper change; if any of them fails, the helper edit broke something and that must be fixed before continuing.

- [ ] **Step 4: Implement the two merges**

Add this module constant near `GOALIE_WEIGHTS` in `src/fantasyPoints.py`:

```python
# 5on5 on-ice counts carried onto each player-game for the PDO features.
# MoneyPuck column -> pipeline column. 'ev' = even strength.
EV_ONICE_COLUMNS = {
    'OnIce_F_goals': 'ev_onIce_goalsFor',
    'OnIce_F_shotsOnGoal': 'ev_onIce_shotsFor',
    'OnIce_F_xGoals': 'ev_onIce_xGoalsFor',
    'OnIce_A_goals': 'ev_onIce_goalsAgainst',
    'OnIce_A_shotsOnGoal': 'ev_onIce_shotsAgainst',
}
```

In `moneypuckGamePoints`, insert after the `powerPlayGoals`/`powerPlayAssists` fillna block (currently `src/fantasyPoints.py:75-76`) and before the `result['fantasyPoints'] = ...` assignment:

```python
    # Power-play ice time: the 5on4 row's icetime. Same 5-on-3-lands-in-'other'
    # undercount as PPP, and for the same reason -- MoneyPuck has no 5on3
    # situation row. The 'all' row's own icetime (total TOI) is untouched.
    pp_toi = (games_df[games_df['situation'] == '5on4']
              .groupby(['playerId', 'gameId'])['icetime']
              .sum()
              .rename('powerPlayIcetime')
              .reset_index())
    result = result.merge(pp_toi, on=['playerId', 'gameId'], how='left')
    result['powerPlayIcetime'] = result['powerPlayIcetime'].fillna(0)

    # 5on5 on-ice goal and shot counts -- PDO's ingredients. Even strength
    # only: on the 'all' rows, power-play time systematically inflates on-ice
    # shooting % for exactly the players who already get PP1 minutes, which
    # turns a luck feature into a deployment feature the model already has.
    ev_counts = (games_df[games_df['situation'] == '5on5']
                 .groupby(['playerId', 'gameId'])[list(EV_ONICE_COLUMNS)]
                 .sum()
                 .rename(columns=EV_ONICE_COLUMNS)
                 .reset_index())
    result = result.merge(ev_counts, on=['playerId', 'gameId'], how='left')
    ev_cols = list(EV_ONICE_COLUMNS.values())
    result[ev_cols] = result[ev_cols].fillna(0)
```

Also extend the docstring's closing line to mention the new columns:

```python
    powerPlayIcetime (5on4 icetime) and the ev_onIce_* counts (5on5 on-ice
    goals/shots for and against) ride along for the deployment and luck
    features -- see src/features/mlFeatures.py and src/features/draft.py.
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fantasyPoints.py tests/test_moneypuck.py -q
```
Expected: PASS, all of them.

- [ ] **Step 6: Full suite and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add src/fantasyPoints.py tests/test_fantasyPoints.py tests/test_moneypuck.py
git commit -m "feat: carry PP ice time and 5on5 on-ice counts through the scoring path"
```

---

### Task 4: PP TOI rolling features and trend deltas

**Files:**
- Modify: `src/features/mlFeatures.py:7-43`
- Test: `tests/test_mlFeatures.py`

**Interfaces:**
- Consumes: `powerPlayIcetime` from Task 3.
- Produces: per-game `pp_toi_share`; rolling columns `rolling_{5,10,20}_{powerPlayIcetime,pp_toi_share,icetime}`; trend deltas `rolling_delta_5_20_{game_fantasy_points,icetime,powerPlayIcetime,pp_toi_share}`. All are auto-enrolled as model features by `pickupFeatureCols`' `rolling_` prefix match.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mlFeatures.py` (note the new import):

```python
from src.features.mlFeatures import buildLabel, buildRollingFeatures


def _rolling_frame(pp_icetimes, total_icetime=1200):
    """One player, ascending gameDates, constant total ice time."""
    n = len(pp_icetimes)
    return pd.DataFrame({
        'playerId': [1] * n,
        'season': [2023] * n,
        'gameDate': [20231001 + i for i in range(n)],
        'game_fantasy_points': [2.0] * n,
        'gameScore': [0.5] * n,
        'icetime': [total_icetime] * n,
        'powerPlayIcetime': pp_icetimes,
        'pp_toi_share': [pp / total_icetime for pp in pp_icetimes],
        'I_F_goals': [0] * n, 'I_F_primaryAssists': [0] * n,
        'I_F_secondaryAssists': [0] * n, 'I_F_xGoals': [0.0] * n,
        'I_F_shotsOnGoal': [0] * n, 'ozone_start_pct': [0.5] * n,
        'xgoals_surplus': [0.0] * n, 'high_danger_rate': [0.0] * n,
        'onIce_corsiPercentage': [50.0] * n,
        'onIce_fenwickPercentage': [50.0] * n,
        'ev_onIce_goalsFor': [0] * n, 'ev_onIce_shotsFor': [0] * n,
        'ev_onIce_xGoalsFor': [0.0] * n, 'ev_onIce_goalsAgainst': [0] * n,
        'ev_onIce_shotsAgainst': [0] * n,
    })


def test_pp_toi_share_is_a_rate_not_a_level():
    # 180s of PP out of 1200s total = 0.15. A 4th-liner and a 1st-liner with
    # the same raw PP seconds are different signals; the share separates them.
    df = _rolling_frame([180] * 5)
    out = buildRollingFeatures(df)
    assert out['rolling_5_pp_toi_share'].iloc[-1] == pytest.approx(0.15)
    assert out['rolling_5_powerPlayIcetime'].iloc[-1] == pytest.approx(180)


def test_pp_toi_delta_detects_a_promotion():
    # 20 games at 60s of PP, then 5 games at 300s -- a PP1 promotion.
    # rolling_5 = 300, rolling_20 = (15*60 + 5*300)/20 = (900+1500)/20 = 120.
    # delta = +180s. A rolling LEVEL alone cannot tell this apart from a
    # player who has always had 120s; the delta is the breakout signal.
    df = _rolling_frame([60] * 20 + [300] * 5)
    out = buildRollingFeatures(df)
    last = out.iloc[-1]
    assert last['rolling_5_powerPlayIcetime'] == pytest.approx(300)
    assert last['rolling_20_powerPlayIcetime'] == pytest.approx(120)
    assert last['rolling_delta_5_20_powerPlayIcetime'] == pytest.approx(180)


def test_trend_deltas_are_zero_for_a_steady_player():
    # No role change -> no trend signal. Guards against a delta that is really
    # measuring window-length artefacts rather than change.
    df = _rolling_frame([120] * 25)
    out = buildRollingFeatures(df)
    last = out.iloc[-1]
    assert last['rolling_delta_5_20_powerPlayIcetime'] == pytest.approx(0)
    assert last['rolling_delta_5_20_pp_toi_share'] == pytest.approx(0)
    assert last['rolling_delta_5_20_game_fantasy_points'] == pytest.approx(0)


def test_icetime_is_rolled_at_20_games_so_its_delta_exists():
    # icetime was previously rolled at 5 and 10 only; the 5-vs-20 delta needs
    # the 20 window. The 5 and 10 columns must still be produced.
    out = buildRollingFeatures(_rolling_frame([120] * 25))
    for col in ['rolling_5_icetime', 'rolling_10_icetime', 'rolling_20_icetime',
                'rolling_delta_5_20_icetime']:
        assert col in out.columns
```

Add `import pytest` at the top of `tests/test_mlFeatures.py` if not already present.

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mlFeatures.py -q
```
Expected: FAIL — `KeyError: 'rolling_5_pp_toi_share'`.

- [ ] **Step 3: Derive pp_toi_share in loadMoneyPuckData**

In `src/features/mlFeatures.py`, add after the `high_danger_rate` line (currently line 16):

```python
    # Share of total ice time spent on the power play. A rate, not a level: a
    # 4th-liner with 1:30 of PP time is a different signal from a 1st-liner
    # with the same 1:30. Both are kept as features; the model picks.
    moneyPuckData['pp_toi_share'] = (
        moneyPuckData['powerPlayIcetime'] / moneyPuckData['icetime'].replace(0, 1))
```

- [ ] **Step 4: Roll the deployment stats and build the trend deltas**

Replace the body of `buildRollingFeatures` (lines 21-43) with:

```python
# Stats whose 5-vs-20-game gap is itself a signal. A rolling level cannot tell
# "has always been a PP1 guy" apart from "was promoted three games ago", and
# only the second is a breakout signal -- the Raddysh case in
# backtest.KNOWN_PICKUPS is exactly this.
TREND_DELTA_STATS = ['game_fantasy_points', 'icetime',
                     'powerPlayIcetime', 'pp_toi_share']


def buildRollingFeatures(df, windows=[5, 10, 20]):
    # icetime moved here from role_stats so its 20-game window exists for the
    # trend delta; the 5- and 10-game columns are unchanged.
    all_window_stats = ['I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
                        'I_F_xGoals', 'I_F_shotsOnGoal', 'game_fantasy_points',
                        'gameScore', 'ozone_start_pct', 'xgoals_surplus',
                        'high_danger_rate', 'icetime',
                        'powerPlayIcetime', 'pp_toi_share'] # all windows

    possession_stats = ['onIce_corsiPercentage', 'onIce_fenwickPercentage'] #10, 20 only

    for window in windows:
        for stat in all_window_stats:
            df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))
        if window >= 10:
            for stat in possession_stats:
                df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))

    # Trend deltas: recent form minus the longer baseline. Only computed when
    # both windows were actually built -- a silent per-stat skip would hide a
    # missing feature, so this guards once, explicitly.
    if {5, 20} <= set(windows):
        for stat in TREND_DELTA_STATS:
            df[f'rolling_delta_5_20_{stat}'] = (
                df[f'rolling_5_{stat}'] - df[f'rolling_20_{stat}'])

    # After the rolling windows loop
    df['season_avg_so_far'] = (
        df.groupby(['playerId', 'season'])['game_fantasy_points']
        .transform(lambda x: x.shift(1).expanding().mean())
    )

    return df
```

Note the `role_stats` list is gone — `icetime` moved into `all_window_stats`.

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mlFeatures.py -q
```
Expected: PASS.

- [ ] **Step 6: Leakage review**

`fht-quality-gates` class (b) requires this, and it must be recorded in the commit message, not just thought about. Confirm each by reading the code:

1. `season_avg_so_far` is still `x.shift(1).expanding().mean()` — the shift(1) is the same-day leakage guard and must not have moved.
2. Every new rolling window uses pandas' trailing `.rolling()`, which includes the current row and no future rows. **Including the current game is correct and pre-existing** — every existing rolling feature does it, and the label (`next_5_avg`) is strictly future via `.shift(-1)`. Do not "fix" this.
3. No new column uses a negative shift.
4. Rolling windows group by `playerId` only, so they span the offseason. That is pre-existing behaviour, unchanged here, and out of scope for this plan.

Verify (1) and (3) mechanically:

```powershell
Select-String -Path src\features\mlFeatures.py -Pattern "shift\(1\)\.expanding|shift\(-"
```
Expected: exactly one hit, the `season_avg_so_far` line. Any `shift(-` outside `buildLabel` is a leak.

- [ ] **Step 7: Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add src/features/mlFeatures.py tests/test_mlFeatures.py
git commit -m "feat: add PP ice-time features and 5-vs-20 trend deltas

Leakage review (fht-quality-gates class b): season_avg_so_far still
shift(1).expanding(); all new windows are trailing .rolling() including the
current row, matching existing features; label stays strictly future; no new
negative shifts."
```

---

### Task 5: GATE — retrain the pickup and cooling models on PP TOI

No new code. This is the evidence gate for Task 4, and it runs *before* PDO lands so the result is attributable to PP TOI alone.

**Files:**
- Modify: `PROJECT-PLAN.md` (Learning Log)

- [ ] **Step 1: Bust the stale feature cache**

`latestGameState` caches the engineered current-season frame for 24 hours. It was written with the old column set; feeding it to a model trained on the new one fails on a feature-count mismatch.

```powershell
Remove-Item d:\repos\FantasyHockeyTools\data\processed\current_players_features.csv -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Retrain**

```powershell
.\.venv\Scripts\python.exe main.py train-pickups
```

Record verbatim: both models' `Best params`, `Train Spearman`, `Val Spearman`, and `Val AUC vs is_heating_up`.

- [ ] **Step 3: Run the product metric**

Global Spearman/AUC are training-time diagnostics. The acceptance metric is the spot-check hit rate.

```powershell
.\.venv\Scripts\python.exe main.py spot-check
```

Record: the five per-date top-15 hit rates, the last-10-FP baseline rates, and the closing simulated-adds line (model hit rate + avg realized next-5 FP/g vs chaser).

- [ ] **Step 4: Check the feature importance plot**

Open `reports/pickup_feature_importance.png`. Confirm prediction 4 from Task 1: does `rolling_delta_5_20_pp_toi_share` outrank `rolling_5_powerPlayIcetime`? Record the answer either way.

- [ ] **Step 5: Eyeball gate**

`fht-quality-gates` §2: *"If the top-20 looks wrong, it is wrong."* In the spot-check output, check the `Known 2025-26 waiver gems` block — specifically **Darren Raddysh**, whose entry (`Hedman injury opened PP1 mid-season`) is the exact case PP TOI is supposed to catch. Compare his FA rank at each date against the Task 1 baseline run. If PP TOI features did not move the one player they were designed for, that is a finding worth recording even if the aggregate metric improved.

- [ ] **Step 6: Record the verdict in PROJECT-PLAN.md**

Append to the Learning Log entry from Task 1:

```markdown
**PP TOI result (2026-08-24):** <numbers>. Prediction 1 said pickup spot-check
top-15 mean 58-63%, cooling flat. Actual: <numbers>. Verdict: <ADOPTED /
REVERTED>. Raddysh FA rank vs baseline: <before> -> <after>.
```

**Decision rule, decided in advance:** adopt if the spot-check top-15 mean is at or above the 55% baseline **and** the simulated-adds hit rate is at or above 60%. A metric that only moves on val Spearman while the spot-check falls is not a result — that is precisely the failure mode `fht-research-frontier` methodology (c) exists to catch. If the gate fails, `git revert` Task 4's commit, record the negative result, and continue to Task 6 (PDO is independent of PP TOI and still deserves its own look).

- [ ] **Step 7: Commit**

```powershell
git status --short
git add PROJECT-PLAN.md
git commit -m "docs: record the PP TOI retrain result"
```

`.pkl` files must not appear in `git status`. They are gitignored; if they show up, stop.

---

### Task 6: On-ice luck features (split PDO)

**Files:**
- Modify: `src/features/mlFeatures.py`
- Test: `tests/test_mlFeatures.py`

**Interfaces:**
- Consumes: the five `ev_onIce_*` columns from Task 3.
- Produces: `mlFeatures.buildOnIceLuckFeatures(df, windows=ONICE_WINDOWS) -> DataFrame`, called from `buildRollingFeatures`. Feature columns `rolling_{10,20}_{onice_shooting_pct,onice_save_pct,onice_gax}` and `rolling_delta_10_20_onice_shooting_pct`; display-only columns `pdo_10`, `pdo_20` (deliberately outside the `rolling_` prefix so the allowlist skips them).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mlFeatures.py`. Extend the `_rolling_frame` helper from Task 4 with on-ice arguments by replacing it with:

```python
def _rolling_frame(pp_icetimes, total_icetime=1200, onice_gf=None,
                   onice_sf=None, onice_ga=None, onice_sa=None, onice_xgf=None):
    """One player, ascending gameDates, constant total ice time."""
    n = len(pp_icetimes)
    zeros = [0] * n
    return pd.DataFrame({
        'playerId': [1] * n,
        'season': [2023] * n,
        'gameDate': [20231001 + i for i in range(n)],
        'game_fantasy_points': [2.0] * n,
        'gameScore': [0.5] * n,
        'icetime': [total_icetime] * n,
        'powerPlayIcetime': pp_icetimes,
        'pp_toi_share': [pp / total_icetime for pp in pp_icetimes],
        'I_F_goals': zeros, 'I_F_primaryAssists': zeros,
        'I_F_secondaryAssists': zeros, 'I_F_xGoals': [0.0] * n,
        'I_F_shotsOnGoal': zeros, 'ozone_start_pct': [0.5] * n,
        'xgoals_surplus': [0.0] * n, 'high_danger_rate': [0.0] * n,
        'onIce_corsiPercentage': [50.0] * n,
        'onIce_fenwickPercentage': [50.0] * n,
        'ev_onIce_goalsFor': onice_gf if onice_gf is not None else zeros,
        'ev_onIce_shotsFor': onice_sf if onice_sf is not None else zeros,
        'ev_onIce_xGoalsFor': onice_xgf if onice_xgf is not None else [0.0] * n,
        'ev_onIce_goalsAgainst': onice_ga if onice_ga is not None else zeros,
        'ev_onIce_shotsAgainst': onice_sa if onice_sa is not None else zeros,
    })
```

Then add the tests:

```python
def test_onice_shooting_pct_is_a_ratio_of_sums_not_a_mean_of_ratios():
    # 10 games. Nine quiet games: 1 goal on 5 on-ice shots (20%). One busy
    # game: 1 goal on 55 on-ice shots (1.8%).
    #   ratio of sums   = (9*1 + 1) / (9*5 + 55) = 10 / 100 = 0.10   <- correct
    #   mean of ratios  = (9*0.20 + 0.018) / 10  = 0.1818            <- wrong
    # The busy game must pull the estimate down in proportion to its shots.
    df = _rolling_frame([0] * 10,
                        onice_gf=[1] * 9 + [1],
                        onice_sf=[5] * 9 + [55],
                        onice_ga=[0] * 10,
                        onice_sa=[10] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_shooting_pct'].iloc[-1] == pytest.approx(0.10)


def test_onice_save_pct_is_one_minus_goals_against_over_shots_against():
    # 10 games x (1 GA on 10 SA) = 10 GA / 100 SA -> save % = 1 - 0.10 = 0.90
    df = _rolling_frame([0] * 10,
                        onice_gf=[0] * 10, onice_sf=[10] * 10,
                        onice_ga=[1] * 10, onice_sa=[10] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_save_pct'].iloc[-1] == pytest.approx(0.90)


def test_pdo_is_display_only_and_not_enrolled_as_a_model_feature():
    # PDO is the sum of two columns already present. It ships for the eyeball
    # gate and the board, but naming it outside the rolling_ prefix keeps
    # pickupFeatureCols' allowlist from feeding a collinear column to the model.
    df = _rolling_frame([0] * 10,
                        onice_gf=[1] * 10, onice_sf=[10] * 10,
                        onice_ga=[1] * 10, onice_sa=[10] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    # SH% = 10/100 = 0.10; SV% = 1 - 10/100 = 0.90; PDO = 1.00
    assert out['pdo_10'].iloc[-1] == pytest.approx(1.00)
    assert 'pdo_10' not in mlFeatures.pickupFeatureCols(out)
    assert 'rolling_10_onice_shooting_pct' in mlFeatures.pickupFeatureCols(out)


def test_onice_percentages_are_nan_below_the_shot_floor():
    # 10 games x 4 on-ice shots = 40 shots, under the 60-shot floor. A
    # percentage off that few shots is denominator noise; NaN is the honest
    # answer and XGBoost handles it natively.
    df = _rolling_frame([0] * 10,
                        onice_gf=[1] * 10, onice_sf=[4] * 10,
                        onice_ga=[1] * 10, onice_sa=[4] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert pd.isna(out['rolling_10_onice_shooting_pct'].iloc[-1])
    assert pd.isna(out['rolling_10_onice_save_pct'].iloc[-1])


def test_onice_features_need_a_full_window():
    # Partial windows have even smaller denominators than the floor allows,
    # so min_periods is the full window: the first 9 rows of a 10-game window
    # are NaN regardless of shot volume.
    df = _rolling_frame([0] * 12,
                        onice_gf=[1] * 12, onice_sf=[20] * 12,
                        onice_ga=[1] * 12, onice_sa=[20] * 12)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_shooting_pct'].iloc[:9].isna().all()
    assert out['rolling_10_onice_shooting_pct'].iloc[9] == pytest.approx(0.05)


def test_onice_gax_is_goals_above_expected_per_game():
    # 10 games x (2 on-ice goals, 1.0 on-ice xG, 20 shots):
    # (20 goals - 10.0 xG) / 10 games = +1.0 goals above expected per game.
    df = _rolling_frame([0] * 10,
                        onice_gf=[2] * 10, onice_sf=[20] * 10,
                        onice_xgf=[1.0] * 10,
                        onice_ga=[0] * 10, onice_sa=[20] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_gax'].iloc[-1] == pytest.approx(1.0)
```

Add `from src.features import mlFeatures` to the test file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mlFeatures.py -q
```
Expected: FAIL — `KeyError: 'rolling_10_onice_shooting_pct'`.

- [ ] **Step 3: Implement buildOnIceLuckFeatures**

Add to `src/features/mlFeatures.py`, above `buildRollingFeatures`:

```python
ONICE_COUNT_COLS = ['ev_onIce_goalsFor', 'ev_onIce_shotsFor', 'ev_onIce_xGoalsFor',
                    'ev_onIce_goalsAgainst', 'ev_onIce_shotsAgainst']
# 5 games is ~60 on-ice shots -- too few for a percentage to mean anything.
ONICE_WINDOWS = [10, 20]
# Minimum on-ice shots behind an estimate before it is worth reporting.
MIN_ONICE_SHOTS = 60


def buildOnIceLuckFeatures(df, windows=ONICE_WINDOWS):
    """On-ice shooting and save percentages over rolling windows -- PDO, split.

    Computed as a RATIO OF ROLLING SUMS, never a rolling mean of per-game
    ratios: a player is on the ice for ~10-25 shots a game, so a per-game
    on-ice shooting % is mostly denominator noise, and averaging those ratios
    would weight a 6-shot game the same as a 25-shot game. That is why this
    cannot ride along in buildRollingFeatures' .rolling().mean() loop.

    The two halves stay SEPARATE features. On-ice shooting % is real signal --
    a player's assists depend on teammates converting shots while he is out
    there, and a hot rate regresses. On-ice save % reaches fantasy points only
    through plus/minus, which moneypuckGamePoints does not compute, so summing
    them into one PDO number would dilute the half that can move the label.
    pdo_{window} is still produced for the eyeball gate and the draft board,
    named outside the rolling_ prefix so pickupFeatureCols does not enrol it.

    Below MIN_ONICE_SHOTS the estimate is NaN rather than a number nobody
    should trust; XGBoost handles NaN natively.
    """
    grouped = df.groupby('playerId')
    for window in windows:
        sums = {col: grouped[col].transform(
                    lambda x: x.rolling(window, min_periods=window).sum())
                for col in ONICE_COUNT_COLS}
        enough_for = sums['ev_onIce_shotsFor'] >= MIN_ONICE_SHOTS
        enough_against = sums['ev_onIce_shotsAgainst'] >= MIN_ONICE_SHOTS

        shooting = (sums['ev_onIce_goalsFor']
                    / sums['ev_onIce_shotsFor']).where(enough_for)
        saving = (1 - sums['ev_onIce_goalsAgainst']
                  / sums['ev_onIce_shotsAgainst']).where(enough_against)

        df[f'rolling_{window}_onice_shooting_pct'] = shooting
        df[f'rolling_{window}_onice_save_pct'] = saving
        # Shot-quality-adjusted shooting half: on-ice goals above expected, per
        # game. Regresses like on-ice SH% but does not punish a player whose
        # line generates low-percentage looks.
        df[f'rolling_{window}_onice_gax'] = (
            (sums['ev_onIce_goalsFor'] - sums['ev_onIce_xGoalsFor']) / window
        ).where(enough_for)
        df[f'pdo_{window}'] = shooting + saving

    if {10, 20} <= set(windows):
        df['rolling_delta_10_20_onice_shooting_pct'] = (
            df['rolling_10_onice_shooting_pct'] - df['rolling_20_onice_shooting_pct'])
    return df
```

- [ ] **Step 4: Call it from buildRollingFeatures**

In `buildRollingFeatures`, insert immediately before `return df`:

```python
    df = buildOnIceLuckFeatures(df)
```

This is why it goes inside `buildRollingFeatures` rather than beside it: there are three call sites (`main.py:36`, `src/backtest.py:57`, `src/features/pickups.py:49`) and a fourth function is a fourth thing to forget.

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mlFeatures.py -q
```
Expected: PASS.

- [ ] **Step 6: Full suite and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add src/features/mlFeatures.py tests/test_mlFeatures.py
git commit -m "feat: add split-PDO on-ice luck features

Leakage review (fht-quality-gates class b): trailing .rolling() sums only,
no negative shifts, label unchanged. Ratios are sums-over-sums so a
high-volume game weights proportionally."
```

---

### Task 7: GATE — retrain the pickup and cooling models on PDO

The evidence gate for Task 6, run separately from Task 5 so the two feature families are attributable.

**Files:**
- Modify: `PROJECT-PLAN.md` (Learning Log)

- [ ] **Step 1: Bust the stale feature cache and retrain**

```powershell
Remove-Item d:\repos\FantasyHockeyTools\data\processed\current_players_features.csv -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe main.py train-pickups
```

Record both models' `Val Spearman` and `Val AUC vs is_heating_up`.

- [ ] **Step 2: Run the product metric**

```powershell
.\.venv\Scripts\python.exe main.py spot-check
```

Record the five per-date top-15 hit rates and the simulated-adds summary line.

- [ ] **Step 3: Check predictions 2 and 3**

- Prediction 2 said **cooling** gains more than pickups (+0.01 to +0.03 val Spearman). Compare against Task 5's recorded cooling number, not the original 0.6063 — Task 5 may have moved it.
- Prediction 3 said on-ice **save %** lands in the bottom half of `reports/pickup_feature_importance.png`. Open the plot and check. If it ranks high, that is worth investigating before celebrating: it most likely means the feature is proxying team quality, not luck.

- [ ] **Step 4: Record the verdict**

Append to the same Learning Log entry:

```markdown
**PDO result (2026-08-24):** <numbers>. Prediction 2 said cooling val Spearman
+0.01 to +0.03. Actual: <numbers>. Prediction 3 (on-ice SV% in the bottom half
of feature importance): <held / did not hold>. Verdict: <ADOPTED / REVERTED>.
```

**Decision rule, decided in advance:** same as Task 5 — spot-check top-15 mean at or above the Task 5 figure and simulated-adds hit rate at or above 60%. Cooling improving while pickups hold flat counts as a pass; that is the pre-registered expectation. If the gate fails, `git revert` Task 6's commit and record the negative result. **Do not** respond to a failed gate by tuning hyperparameters in the same change — that is research-frontier item 1, a separate experiment, and mixing them destroys attribution for both.

- [ ] **Step 5: Commit**

```powershell
git add PROJECT-PLAN.md
git commit -m "docs: record the PDO retrain result"
```

---

### Task 8: Season-level deployment and luck aggregates

The draft ranker reads `data/processed/player_seasons.csv`, not game logs. This task adds the season aggregates and rebuilds that file.

**Files:**
- Modify: `src/moneypuck.py:141-184` (buildPlayerSeasons)
- Test: `tests/test_moneypuck.py`

**Interfaces:**
- Consumes: `powerPlayIcetime` and `ev_onIce_*` from Task 3.
- Produces, on each `(playerId, season)` row: `totalIcetime`, `totalPPIcetime`, `avgPPIcetime`, `ppToiShare`, `oniceShootingPct`, `oniceSavePct`, `pdo`, `oniceGaxPerGame`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_moneypuck.py`:

```python
def test_build_player_seasons_aggregates_pp_icetime_as_a_share():
    # 2 games, 1200s total ice time each, 180s of PP each:
    #   totalPPIcetime = 360, totalIcetime = 2400 -> ppToiShare = 0.15
    #   avgPPIcetime = 360 / 2 games = 180
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015, icetime=1200),
        _pickup_row(1, 100, 20251015, situation='5on4', icetime=180),
        _pickup_row(1, 101, 20251017, icetime=1200),
        _pickup_row(1, 101, 20251017, situation='5on4', icetime=180),
    ])
    row = moneypuck.buildPlayerSeasons(df).iloc[0]
    assert row['totalPPIcetime'] == 360
    assert row['totalIcetime'] == 2400
    assert row['ppToiShare'] == pytest.approx(0.15)
    assert row['avgPPIcetime'] == pytest.approx(180)


def test_build_player_seasons_onice_rates_are_sums_over_sums():
    # 2 games of 5on5 on-ice counts:
    #   game 1: 1 GF on 10 SF, 2 GA on 20 SA
    #   game 2: 3 GF on 30 SF, 1 GA on 20 SA
    #   SH% = (1+3)/(10+30) = 4/40 = 0.10
    #   SV% = 1 - (2+1)/(20+20) = 1 - 3/40 = 0.925
    #   PDO = 1.025
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015),
        _pickup_row(1, 100, 20251015, situation='5on5', onice_gf=1, onice_sf=10,
                    onice_ga=2, onice_sa=20),
        _pickup_row(1, 101, 20251017),
        _pickup_row(1, 101, 20251017, situation='5on5', onice_gf=3, onice_sf=30,
                    onice_ga=1, onice_sa=20),
    ])
    row = moneypuck.buildPlayerSeasons(df).iloc[0]
    assert row['oniceShootingPct'] == pytest.approx(0.10)
    assert row['oniceSavePct'] == pytest.approx(0.925)
    assert row['pdo'] == pytest.approx(1.025)


def test_build_player_seasons_onice_gax_is_per_game():
    # 2 games, 4 on-ice goals total on 3.0 total on-ice xG:
    # (4 - 3.0) / 2 games = +0.5 goals above expected per game.
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015),
        _pickup_row(1, 100, 20251015, situation='5on5', onice_gf=1, onice_sf=10,
                    onice_xgf=1.5),
        _pickup_row(1, 101, 20251017),
        _pickup_row(1, 101, 20251017, situation='5on5', onice_gf=3, onice_sf=10,
                    onice_xgf=1.5),
    ])
    row = moneypuck.buildPlayerSeasons(df).iloc[0]
    assert row['oniceGaxPerGame'] == pytest.approx(0.5)


def test_build_player_seasons_zero_onice_shots_is_nan_not_infinity():
    # A player with no 5on5 rows must not produce a divide-by-zero rate.
    df = pd.DataFrame([_pickup_row(1, 100, 20251015)])
    row = moneypuck.buildPlayerSeasons(df).iloc[0]
    assert pd.isna(row['oniceShootingPct'])
    assert pd.isna(row['oniceSavePct'])
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moneypuck.py -q
```
Expected: FAIL — `KeyError: 'totalPPIcetime'`.

- [ ] **Step 3: Add the aggregations**

In `buildPlayerSeasons`'s `.agg(...)` call, add after `totalFP=('fantasyPoints', 'sum'),`:

```python
        totalIcetime=('icetime', 'sum'),
        totalPPIcetime=('powerPlayIcetime', 'sum'),
        totalOnIceGoalsFor=('ev_onIce_goalsFor', 'sum'),
        totalOnIceShotsFor=('ev_onIce_shotsFor', 'sum'),
        totalOnIceXGoalsFor=('ev_onIce_xGoalsFor', 'sum'),
        totalOnIceGoalsAgainst=('ev_onIce_goalsAgainst', 'sum'),
        totalOnIceShotsAgainst=('ev_onIce_shotsAgainst', 'sum'),
```

Then add after the existing `highDangerShare` derivation:

```python
    # Deployment. ppToiShare is the rate the draft model wants; avgPPIcetime is
    # the level, kept because a share hides whether 20% of 12 minutes or 20% of
    # 22 is behind it.
    summary['ppToiShare'] = (
        summary['totalPPIcetime'] / summary['totalIcetime'].replace(0, 1))
    summary['avgPPIcetime'] = (
        summary['totalPPIcetime'] / summary['gamesPlayed'].replace(0, 1))

    # Luck, at 5on5. Sums over sums, never a mean of per-game rates -- see
    # features/mlFeatures.buildOnIceLuckFeatures for the full argument. A
    # player with no 5on5 shots gets NaN, not a divide-by-zero.
    summary['oniceShootingPct'] = (
        summary['totalOnIceGoalsFor']
        / summary['totalOnIceShotsFor'].where(summary['totalOnIceShotsFor'] > 0))
    summary['oniceSavePct'] = 1 - (
        summary['totalOnIceGoalsAgainst']
        / summary['totalOnIceShotsAgainst'].where(summary['totalOnIceShotsAgainst'] > 0))
    # Display/diagnostic only, same as pdo_{window} on the game-log side: the
    # two halves are what the model sees.
    summary['pdo'] = summary['oniceShootingPct'] + summary['oniceSavePct']
    summary['oniceGaxPerGame'] = (
        (summary['totalOnIceGoalsFor'] - summary['totalOnIceXGoalsFor'])
        / summary['gamesPlayed'].replace(0, 1))
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moneypuck.py -q
```
Expected: PASS.

- [ ] **Step 5: Rebuild player_seasons.csv**

This reads the full 2.6 GB history from 2008 and rebuilds the v2 cache at `min_season=2008` — several minutes. Expected, not a hang.

```powershell
.\.venv\Scripts\python.exe scripts/build_player_seasons.py
```

- [ ] **Step 6: Re-run the A2 acceptance check**

`fht-quality-gates` class (a): the aggregation changed, so the scoring acceptance numbers must be re-confirmed. The script prints them. Confirm:
- McDavid 2023-24 reads **32 G / 100 A**, PPP ≈ 42
- rows/season is roughly `n_seasons × ~900 skaters` — 2–3× that means situation rows were double-counted

**If McDavid's line moved, stop.** The new merges leaked into the scoring path, and nothing downstream can be trusted until that is fixed.

- [ ] **Step 7: Sanity-check the new columns against hockey reality**

```powershell
.\.venv\Scripts\python.exe -c "import pandas as pd; d = pd.read_csv('data/processed/player_seasons.csv'); d = d[d['gamesPlayed'] >= 40]; print(d[['ppToiShare','oniceShootingPct','oniceSavePct','pdo','oniceGaxPerGame']].describe())"
```

Expected ranges — anything outside these is a bug, not a discovery:
- `oniceShootingPct` mean ≈ 0.07–0.09 (league on-ice SH% is ~8%)
- `oniceSavePct` mean ≈ 0.91–0.93
- `pdo` mean ≈ **1.00** — this is PDO's defining property; a mean far off 1.00 means the halves are computed wrong
- `ppToiShare` mean ≈ 0.08–0.15, max well under 0.5

- [ ] **Step 8: Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git status --short
git add src/moneypuck.py tests/test_moneypuck.py
git commit -m "feat: aggregate PP ice time and 5on5 on-ice rates per player-season

A2 acceptance re-checked after the aggregation change: McDavid 2023-24
32G/100A, PPP 42. League mean PDO 1.00."
```

---

### Task 9: Draft features — deployment level, luck residual

**Files:**
- Modify: `src/features/draft.py:16-67`, `src/models/draft.py:39-43` (BASE_FEATURE_COLS)
- Test: `tests/test_shared.py` is for `features/shared.py`; create `tests/test_draft_features.py`

**Interfaces:**
- Consumes: `ppToiShare`, `avgPPIcetime`, `oniceShootingPct`, `oniceGaxPerGame` from Task 8.
- Produces: `pp_toi_share_delta`, `onice_sh_luck` on `build_draft_features` output; five new entries in `BASE_FEATURE_COLS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_draft_features.py`:

```python
import pandas as pd
import pytest

from src.features.draft import build_draft_features


def _season_row(playerId, season, onice_sh=0.08, pp_share=0.10, **kwargs):
    """Minimal player_seasons row for build_draft_features."""
    row = {
        'playerId': playerId, 'season': season, 'gamesPlayed': 82,
        'full_name': f'Player {playerId}', 'position': 'C',
        'avgIcetime': 1100.0, 'avgGameScore': 0.6,
        'avgCorsiPercentage': 50.0, 'avgFenwickPercentage': 50.0,
        'totalGoals': 20, 'totalPrimaryAssists': 20, 'totalSecondaryAssists': 10,
        'totalPoints': 50, 'totalShotsOnGoal': 200, 'totalHits': 50,
        'totalShotsBlocked': 40, 'totalXGoals': 18.0,
        'totalHighDangerShots': 40, 'totalPPP': 15, 'totalPPGoals': 5,
        'totalPPAssists': 10, 'totalSHP': 1, 'totalFP': 200.0,
        'fpPerGame': 2.44, 'xGoalsSurplus': 2.0, 'highDangerShare': 0.2,
        'ppToiShare': pp_share, 'avgPPIcetime': 150.0,
        'oniceShootingPct': onice_sh, 'oniceSavePct': 0.92,
        'pdo': onice_sh + 0.92, 'oniceGaxPerGame': 0.1,
    }
    row.update(kwargs)
    return row


def test_onice_sh_luck_is_deviation_from_the_players_own_baseline():
    # Three seasons at 8% on-ice SH%, then a 12% season.
    # prior 3-season mean = 0.08 -> luck = 0.12 - 0.08 = +0.04.
    # Deviation from his OWN history, not the league: on-ice SH% has a real
    # talent component (elite linemates convert more) and only the transient
    # part regresses.
    df = pd.DataFrame([
        _season_row(1, 2020, onice_sh=0.08),
        _season_row(1, 2021, onice_sh=0.08),
        _season_row(1, 2022, onice_sh=0.08),
        _season_row(1, 2023, onice_sh=0.12),
    ])
    out = build_draft_features(df).sort_values('season')
    assert out['onice_sh_luck'].iloc[-1] == pytest.approx(0.04)


def test_onice_sh_luck_is_nan_in_a_players_first_season():
    # A rookie has no baseline to deviate from. NaN is correct and matches
    # fp_delta's treatment; XGBoost handles it natively.
    df = pd.DataFrame([_season_row(1, 2023, onice_sh=0.14)])
    out = build_draft_features(df)
    assert pd.isna(out['onice_sh_luck'].iloc[0])


def test_pp_toi_share_delta_tracks_a_role_change():
    # 6% of ice time on the PP, then 18% -- a PP2-to-PP1 promotion.
    df = pd.DataFrame([
        _season_row(1, 2022, pp_share=0.06),
        _season_row(1, 2023, pp_share=0.18),
    ])
    out = build_draft_features(df).sort_values('season')
    assert out['pp_toi_share_delta'].iloc[-1] == pytest.approx(0.12)
    assert pd.isna(out['pp_toi_share_delta'].iloc[0])


def test_luck_residual_keeps_players_separate():
    # Player 2's history must not bleed into player 1's baseline.
    df = pd.DataFrame([
        _season_row(1, 2022, onice_sh=0.08),
        _season_row(2, 2022, onice_sh=0.20),
        _season_row(1, 2023, onice_sh=0.10),
    ])
    out = build_draft_features(df)
    row = out[(out['playerId'] == 1) & (out['season'] == 2023)].iloc[0]
    assert row['onice_sh_luck'] == pytest.approx(0.02)


def test_new_draft_features_are_in_the_model_feature_list():
    from src.models.draft import BASE_FEATURE_COLS
    for col in ['ppToiShare', 'avgPPIcetime', 'pp_toi_share_delta',
                'onice_sh_luck', 'oniceGaxPerGame']:
        assert col in BASE_FEATURE_COLS
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_draft_features.py -q
```
Expected: FAIL — `KeyError: 'onice_sh_luck'`.

- [ ] **Step 3: Add the features**

In `src/features/draft.py`, insert after the `fp_w3` block (currently line 45) and before the `# target only` comment:

```python
    # Deployment: PP ice-time share is the strongest role signal available.
    # ppToiShare rides through from player_seasons as-is (this row's own
    # concluded season); the delta is the backward-looking role change.
    # Note this is deliberately distinct from PP_share above: that is PP
    # OUTPUT (fantasy points earned on the PP), this is PP OPPORTUNITY (time).
    # They will correlate; check the Ridge coefficients for one flipping sign.
    sorted_player_seasons['pp_toi_share_delta'] = g['ppToiShare'].diff()

    # Luck as a RESIDUAL, not a level. The model's strongest input is this
    # season's fpPerGame; on-ice shooting %'s entire marginal contribution is
    # telling the model that number was inflated, which a raw rate cannot say.
    # Deviation from the player's own prior 3 seasons rather than the league
    # mean: on-ice SH% has a real talent component and only the transient part
    # regresses. First season -> NaN, same as fp_delta, and correct.
    prior_onice_sh = g['oniceShootingPct'].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    sorted_player_seasons['onice_sh_luck'] = (
        sorted_player_seasons['oniceShootingPct'] - prior_onice_sh)
```

**Placement matters:** `g = sorted_player_seasons.groupby('playerId')` is created at line 36 and holds a reference to the frame as it was then. `ppToiShare` and `oniceShootingPct` arrive from `player_seasons.csv`, so they exist before `g` and are visible through it. Do not move this block above line 36.

- [ ] **Step 4: Add them to the model's feature list**

In `src/models/draft.py`, replace `BASE_FEATURE_COLS` (lines 39-43) with:

```python
BASE_FEATURE_COLS = [
    'fpPerGame', 'fp_delta', 'fp_w3', 'PP_share', 'hitblock_share',
    'xGoalsSurplus', 'avgIcetime', 'career_games', 'age_at_season_start',
    'highDangerShare', 'avgGameScore',
    # Deployment (opportunity) and luck (sustainability). onice_sh_luck is a
    # residual against the player's own baseline -- its standardized Ridge
    # coefficient MUST come out negative. A positive one means it is acting as
    # a talent proxy, not a luck proxy, and the feature is wrong.
    'ppToiShare', 'avgPPIcetime', 'pp_toi_share_delta',
    'onice_sh_luck', 'oniceGaxPerGame',
]
```

- [ ] **Step 5: Run the tests to verify they pass**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_draft_features.py -q
```
Expected: PASS.

- [ ] **Step 6: Full suite and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add src/features/draft.py src/models/draft.py tests/test_draft_features.py
git commit -m "feat: add PP deployment and on-ice luck residual to the draft ranker"
```

---

### Task 10: GATE — retrain the draft ranker

**Files:**
- Modify: `PROJECT-PLAN.md` (Learning Log)

- [ ] **Step 1: Retrain**

```powershell
.\.venv\Scripts\python.exe main.py train-draft
```

- [ ] **Step 2: Check the Ridge coefficient signs — the real gate**

`train()` prints standardized Ridge coefficients specifically for this. Confirm:

| Feature | Required sign | Meaning if wrong |
|---|---|---|
| `onice_sh_luck` | **negative** | Acting as a talent proxy, not a luck proxy — feature is wrong |
| `ppToiShare` | positive | PP opportunity should raise next-season FP/g |
| `fpPerGame` | strongly positive | Pre-existing sanity check; if this flips, something broke |

Also check whether `PP_share` (PP output) flipped sign now that `ppToiShare` (PP opportunity) is present — collinearity between the two is expected and a flip is informative, not automatically a bug, but it must be recorded.

**If `onice_sh_luck` is positive, stop and debug the feature before reading any Spearman number.** A high validation score from a feature doing the opposite of what it was designed to do is exactly the "AUC has misled this project once" failure mode.

- [ ] **Step 3: Record Spearman against the Task 1 baselines**

Compare the printed `XGBoost: val Spearman` and the `GATE B3` verdict against the numbers captured in Task 1. Prediction 6 said the move would be under +0.01.

- [ ] **Step 4: Eyeball gate on the board**

```powershell
.\.venv\Scripts\python.exe main.py draft
```

`fht-quality-gates` §2: check the top 20. A 38-year-old riding one lucky season sitting near the top is a bug, not a result — and `onice_sh_luck` is specifically supposed to *demote* that player. Compare the top 20 against the pre-change `data/processed/draft_rankings.csv` and record which players moved most, in both directions. Per session memory: surface the actual names, not just the margin.

- [ ] **Step 5: Record the verdict**

```markdown
**Draft result (2026-08-24):** Baseline A <x>, Baseline B <y>, XGBoost before
<z>, XGBoost after <w>. GATE B3: <PASS/FAIL>. Ridge signs: onice_sh_luck
<sign>, ppToiShare <sign>, PP_share <sign, flipped?>. Biggest movers in the
top 30: <names, both directions>. Verdict: <ADOPTED / REVERTED>.
```

**Decision rule, decided in advance:** adopt if `onice_sh_luck`'s Ridge coefficient is negative **and** val Spearman is at or above the Task 1 XGBoost figure. A neutral Spearman with correct signs still counts as a pass — prediction 6 expects a small move, and the features are there to demote unsustainable seasons, which the aggregate rank correlation only partly rewards.

**Do not touch `season.DRAFT_TEST_SEASON` (2024).** No result in this task justifies spending the held-out look. That decision needs explicit owner sign-off, separately.

- [ ] **Step 6: Commit**

```powershell
git status --short
git add PROJECT-PLAN.md
git commit -m "docs: record the draft ranker retrain result"
```

---

### Task 11: Documentation and downstream refresh

**Files:**
- Modify: `CLAUDE.md`, `PROJECT-PLAN.md` (Current Phase), `.claude/skills/fht-domain-reference/SKILL.md`, `.claude/skills/fht-research-frontier/SKILL.md`

- [ ] **Step 1: Refresh the frontend export**

The draft board reads `frontend_data.json`, which is now stale relative to the retrained models.

```powershell
.\.venv\Scripts\python.exe api_export.py
```

Per the July 2026 handoff, this path can block on Yahoo OAuth waiting on stdin. If it hangs with no output, that is the known cause — check `fht-operations` rather than assuming a code bug.

- [ ] **Step 2: Update fht-domain-reference**

Its §2 table lists `GAME_COLUMNS` as a "fixed 22-column subset" with the full list inline. Update the count to 27 and add the five `OnIce_*` columns. Add rows to the field table:

```markdown
| `OnIce_F_` / `OnIce_A_` prefix | on-ice goals/shots FOR and AGAINST while the player was on the ice — PDO's ingredients, read from the `5on5` rows only |
| PDO | on-ice SH% + on-ice SV%, league mean 1.00 by construction. Split into halves in this repo, never summed into a model feature: on-ice SV% reaches fantasy points only through plus/minus, which `moneypuckGamePoints` does not compute |
```

Also add PDO and PP TOI to the glossary, and update the provenance command list to include a `pdo` mean check.

- [ ] **Step 3: Update fht-research-frontier item 2**

Item 2 ("Trend and deployment features") is what this work implements. Mark its status the way item 3 is marked — `**STATUS: SHIPPED 2026-08-24**` with the recorded before/after numbers and the verdict from Tasks 5, 7 and 10 — keeping the original rationale text below it.

- [ ] **Step 4: Update CLAUDE.md**

Add to the Known issues list, matching the existing entries' style, one line recording what shipped and what the gates said. If any gate failed and the feature was reverted, record *that* — a recorded negative result is the point of methodology (e).

Also update the architecture-at-a-glance note if the cache filename change is worth surfacing (it is: a fresh clone rebuilding `moneypuck_games_v2_*.parquet` is new behaviour).

- [ ] **Step 5: Update PROJECT-PLAN's Current Phase**

Standing rule per `fht-quality-gates` §5.

- [ ] **Step 6: Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git status --short
git add CLAUDE.md PROJECT-PLAN.md .claude/skills/
git commit -m "docs: record the deployment and luck feature work in the skill library"
```

---

## Rollback notes

Each feature task is a single commit and reverts cleanly. Two things do **not** revert with the code:

- **The v2 game-log caches.** They are supersets of the v1 columns, so reverted code reads them fine — `usecols` is only applied to the raw CSVs, and reverted code simply ignores the extra columns. No action needed.
- **`player_seasons.csv`.** Rebuilt in Task 8 with extra columns. Reverted draft code ignores them. No rebuild needed on revert.

If Task 4 or Task 6 is reverted after its gate fails, **also delete `data/processed/current_players_features.csv`** and retrain — the saved `.pkl` expects the feature count that was in effect when it was fitted.
