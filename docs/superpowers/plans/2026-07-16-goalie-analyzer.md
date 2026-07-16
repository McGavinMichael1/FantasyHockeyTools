# Goalie Draft + Keeper Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add goalies to the draft and keeper analyzers: goalie fantasy scoring, a goalie_seasons table (MoneyPuck + NHL API), a trained goalie ranker, goalie rows with VORP in draft_rankings.csv, and goalie keeper eligibility.

**Architecture:** Mirrors the skater draft pipeline exactly — a one-time season-table build script, a features module, a model module with the baselines→Ridge→XGBoost gate protocol, and CLI wiring in main.py. MoneyPuck supplies skill features (xGoals); the NHL API landing endpoint supplies W/L/SO/GS for fantasy points (MoneyPuck goalie data has none of those). Cross-position comparability comes from VORP via `keeper.replacement_levels`, not raw FP.

**Tech Stack:** Python (pandas, xgboost, scikit-learn, pytest), Next.js/TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md` (all owner decisions settled 2026-07-16).

## Global Constraints

- Always invoke Python as `.\.venv\Scripts\python.exe` (system `python` may be an unrelated interpreter).
- Set `$env:PYTHONUTF8='1'` before any command that hits the NHL API (response previews crash cp1252 consoles).
- Never auto-download MoneyPuck data; the four goalie CSVs already exist in `data/raw/goalies/` (see its README.md).
- MoneyPuck rows: use `situation == 'all'` only — summing situation rows double-counts every stat.
- `GOALIE_WEIGHTS` exactly: gamesStarted 0.75, wins 2.5, losses −1, goalsAgainst −0.5, saves 0.15, shutouts 3.
- Losses are **regulation-only** (owner confirmed 2026-07-16): use the NHL API `losses` field as-is; never add `otLosses`.
- Goalie replacement rank is **20**; projected-GP cap is **65**; goalie `MIN_GP` is **15** (train and display).
- Splits: train ≤ 2021, val 2022+2023, test 2024 gets ONE look after the gate, never random rows.
- The test suite has 1 pre-existing failure (`tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations`, known guard-ordering bug). Expect it in every full-suite run; do NOT fix it in this plan.
- Commit after every task with a conventional message (`feat:`/`test:`/`docs:`) ending in `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Full test command: `.\.venv\Scripts\python.exe -m pytest -v` (pytest.ini is the config that counts).

---

### Task 1: Goalie scoring weights and function

**Files:**
- Modify: `src/fantasyPoints.py` (append after `calculateSkaterPoints`, line 26)
- Test: `tests/test_fantasyPoints.py` (append)

**Interfaces:**
- Produces: `fantasyPoints.GOALIE_WEIGHTS: dict[str, float]` and `fantasyPoints.calculateGoaliePoints(stats) -> float` where `stats` is any Mapping/Series with `.get` (keys: `gamesStarted`, `wins`, `losses`, `goalsAgainst`, `saves`, `shutouts`; missing keys count 0). Task 3 calls it with pandas Series rows.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fantasyPoints.py`:

```python
def test_calculate_goalie_points_matches_hand_computed_season():
    # Hellebuyck-tier season: 60 GS, 37 W, 19 L, 158 GA, 1656 SV, 5 SO
    # = 60*0.75 + 37*2.5 + 19*-1 + 158*-0.5 + 1656*0.15 + 5*3
    # = 45 + 92.5 - 19 - 79 + 248.4 + 15 = 302.9
    stats = {'gamesStarted': 60, 'wins': 37, 'losses': 19,
             'goalsAgainst': 158, 'saves': 1656, 'shutouts': 5}
    assert fantasyPoints.calculateGoaliePoints(stats) == pytest.approx(302.9)


def test_calculate_goalie_points_defaults_missing_stats_to_zero():
    assert fantasyPoints.calculateGoaliePoints({}) == 0
    assert fantasyPoints.calculateGoaliePoints({'wins': 2}) == pytest.approx(5.0)


def test_goalie_weights_are_the_six_league_categories_exactly():
    assert fantasyPoints.GOALIE_WEIGHTS == {
        'gamesStarted': 0.75, 'wins': 2.5, 'losses': -1,
        'goalsAgainst': -0.5, 'saves': 0.15, 'shutouts': 3,
    }
```

If `tests/test_fantasyPoints.py` does not already import `pytest`, add `import pytest` at the top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fantasyPoints.py -v`
Expected: the three new tests FAIL with `AttributeError: ... has no attribute 'calculateGoaliePoints'` (existing tests still pass).

- [ ] **Step 3: Write the implementation**

Append to `src/fantasyPoints.py`:

```python
# League scoring weights for goalies — the single source of truth, same
# discipline as SKATER_WEIGHTS. `losses` is regulation-only (owner confirmed
# 2026-07-16): this league does not record OT/SO losses as losses, so use
# the NHL API `losses` field as-is and never add otLosses.
GOALIE_WEIGHTS = {
    'gamesStarted': 0.75,
    'wins': 2.5,
    'losses': -1,
    'goalsAgainst': -0.5,
    'saves': 0.15,
    'shutouts': 3,
}


def calculateGoaliePoints(stats):
    """League fantasy points for one goalie stat line (dict or pandas Series).

    Keys are NHL-API field names; `saves` is derived upstream as
    shotsAgainst - goalsAgainst. Missing keys count as zero.
    """
    points = 0
    for stat, weight in GOALIE_WEIGHTS.items():
        points += (stats.get(stat, 0) or 0) * weight
    return points
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_fantasyPoints.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/fantasyPoints.py tests/test_fantasyPoints.py
git commit -m "feat: add goalie fantasy scoring (GOALIE_WEIGHTS)"
```

---

### Task 2: NHL API goalie season records + birthdate cache append

**Files:**
- Modify: `src/dataProcessing.py` (append at end)
- Test: `tests/test_goalie_seasons.py` (create)

**Interfaces:**
- Consumes: `nhlAPI.getPlayerStats(player_id)` (existing; returns the landing JSON dict).
- Produces:
  - `dataProcessing.extractGoalieSeasons(data, player_id) -> list[dict]` — one dict per NHL regular-season row, keys `playerId, season, gamesPlayed, gamesStarted, wins, losses, otLosses, shutouts, goalsAgainst, shotsAgainst`, with `season` in MoneyPuck convention (2023 = 2023-24).
  - `dataProcessing.aggregateGoalieSeasonRows(rows) -> pd.DataFrame` — one row per (playerId, season).
  - `dataProcessing.getGoalieSeasonsWithCache(player_ids) -> pd.DataFrame` — permanent cache `data/raw/goalie_nhl_seasons.csv`, fetches only ids missing from the cache.
  - `dataProcessing.appendMissingBirthDates(player_ids) -> pd.DataFrame` — like `getAllBirthDatesWithCache` but also fetches ids the cache lacks.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_goalie_seasons.py`:

```python
import pandas as pd

from src import dataProcessing


LANDING_FIXTURE = {
    'birthDate': '1993-05-19',
    'seasonTotals': [
        # NHL regular season — kept
        {'season': 20232024, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 60, 'gamesStarted': 60, 'wins': 37, 'losses': 19,
         'otLosses': 4, 'shutouts': 5, 'goalsAgainst': 158, 'shotsAgainst': 1814},
        # playoffs — dropped (gameTypeId 3)
        {'season': 20232024, 'gameTypeId': 3, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 5, 'gamesStarted': 5, 'wins': 1, 'losses': 4,
         'otLosses': 0, 'shutouts': 0, 'goalsAgainst': 15, 'shotsAgainst': 130},
        # AHL — dropped
        {'season': 20152016, 'gameTypeId': 2, 'leagueAbbrev': 'AHL',
         'gamesPlayed': 30, 'gamesStarted': 30, 'wins': 20, 'losses': 8,
         'otLosses': 1, 'shutouts': 2, 'goalsAgainst': 70, 'shotsAgainst': 800},
        # traded season: one row per team, must aggregate to one
        {'season': 20222023, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 20, 'gamesStarted': 18, 'wins': 10, 'losses': 8,
         'otLosses': 1, 'shutouts': 1, 'goalsAgainst': 55, 'shotsAgainst': 600},
        {'season': 20222023, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 15, 'gamesStarted': 14, 'wins': 7, 'losses': 6,
         'otLosses': 0, 'shutouts': 0, 'goalsAgainst': 40, 'shotsAgainst': 450},
        # ancient season with a missing field — None coerces to 0
        {'season': 20082009, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 40, 'gamesStarted': None, 'wins': 22, 'losses': 15,
         'otLosses': 2, 'shutouts': 3, 'goalsAgainst': 100, 'shotsAgainst': 1100},
    ],
}


def test_extract_goalie_seasons_filters_and_converts_season_keys():
    rows = dataProcessing.extractGoalieSeasons(LANDING_FIXTURE, 8478024)
    seasons = sorted(r['season'] for r in rows)
    assert seasons == [2008, 2022, 2022, 2023]  # no playoffs, no AHL
    assert all(r['playerId'] == 8478024 for r in rows)
    ancient = next(r for r in rows if r['season'] == 2008)
    assert ancient['gamesStarted'] == 0  # None -> 0


def test_aggregate_goalie_season_rows_sums_traded_stints():
    rows = dataProcessing.extractGoalieSeasons(LANDING_FIXTURE, 8478024)
    df = dataProcessing.aggregateGoalieSeasonRows(rows)
    assert len(df) == 3  # 2008, 2022 (merged), 2023
    traded = df[df['season'] == 2022].iloc[0]
    assert traded['gamesPlayed'] == 35
    assert traded['wins'] == 17
    assert traded['shotsAgainst'] == 1050


def test_append_missing_birthdates_fetches_only_missing_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(dataProcessing, 'RAW_DATA_DIR', str(tmp_path))
    pd.DataFrame({'playerId': [1], 'birthDate': ['1990-01-01']}).to_csv(
        tmp_path / 'player_birthdates.csv', index=False)

    fetched = []

    def fake_fetch(ids):
        fetched.extend(ids)
        return pd.DataFrame({'playerId': ids, 'birthDate': ['1995-05-05'] * len(ids)})

    monkeypatch.setattr(dataProcessing, 'makeAllBirthDatesDataFrame', fake_fetch)
    result = dataProcessing.appendMissingBirthDates([1, 2])

    assert fetched == [2]  # id 1 was cached, never refetched
    assert sorted(result['playerId'].tolist()) == [1, 2]
    on_disk = pd.read_csv(tmp_path / 'player_birthdates.csv')
    assert sorted(on_disk['playerId'].tolist()) == [1, 2]


def test_get_goalie_seasons_with_cache_appends_missing_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(dataProcessing, 'RAW_DATA_DIR', str(tmp_path))
    pd.DataFrame({'playerId': [1], 'season': [2023], 'gamesPlayed': [50],
                  'gamesStarted': [48], 'wins': [30], 'losses': [15],
                  'otLosses': [3], 'shutouts': [4], 'goalsAgainst': [120],
                  'shotsAgainst': [1400]}).to_csv(
        tmp_path / 'goalie_nhl_seasons.csv', index=False)

    fetched = []

    def fake_make(ids):
        fetched.extend(ids)
        return pd.DataFrame({'playerId': ids, 'season': [2023] * len(ids),
                             'gamesPlayed': [20] * len(ids), 'gamesStarted': [18] * len(ids),
                             'wins': [9] * len(ids), 'losses': [8] * len(ids),
                             'otLosses': [1] * len(ids), 'shutouts': [1] * len(ids),
                             'goalsAgainst': [50] * len(ids), 'shotsAgainst': [560] * len(ids)})

    monkeypatch.setattr(dataProcessing, 'makeGoalieSeasonsDataFrame', fake_make)
    result = dataProcessing.getGoalieSeasonsWithCache([1, 2])

    assert fetched == [2]
    assert sorted(result['playerId'].tolist()) == [1, 2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_goalie_seasons.py -v`
Expected: FAIL with `AttributeError: module 'src.dataProcessing' has no attribute 'extractGoalieSeasons'`.

- [ ] **Step 3: Write the implementation**

Append to `src/dataProcessing.py`:

```python
def extractGoalieSeasons(data, player_id):
    """NHL regular-season goalie rows from a landing response.

    Filters to gameTypeId 2 (regular season) + leagueAbbrev NHL, converts the
    season key to MoneyPuck convention (20232024 -> 2023). Traded goalies get
    one row per team per season here -- aggregateGoalieSeasonRows sums them.
    """
    rows = []
    for s in data.get('seasonTotals', []):
        if s.get('gameTypeId') != 2 or s.get('leagueAbbrev') != 'NHL':
            continue
        rows.append({
            'playerId': player_id,
            'season': s['season'] // 10000,
            'gamesPlayed': s.get('gamesPlayed') or 0,
            'gamesStarted': s.get('gamesStarted') or 0,
            'wins': s.get('wins') or 0,
            'losses': s.get('losses') or 0,
            'otLosses': s.get('otLosses') or 0,
            'shutouts': s.get('shutouts') or 0,
            'goalsAgainst': s.get('goalsAgainst') or 0,
            'shotsAgainst': s.get('shotsAgainst') or 0,
        })
    return rows


def aggregateGoalieSeasonRows(rows):
    """One row per (playerId, season): sums the per-team stint rows."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.groupby(['playerId', 'season'], as_index=False).sum()


def makeGoalieSeasonsDataFrame(player_ids):
    def worker(player_id):
        try:
            return extractGoalieSeasons(nhlAPI.getPlayerStats(player_id), player_id)
        except Exception as e:
            print(f"Failed for goalie {player_id}: {e}")
            return []
    with ThreadPoolExecutor(max_workers=5) as executor:
        rows = [row for result in executor.map(worker, player_ids) for row in result]
    return aggregateGoalieSeasonRows(rows)


def getGoalieSeasonsWithCache(player_ids):
    """Permanent cache (like birthdates), plus append-missing: ids absent
    from the cache are fetched and appended. Completed seasons never change;
    at season rollover DELETE data/raw/goalie_nhl_seasons.csv so every
    goalie's newest season gets fetched fresh (a few minutes, threaded).
    """
    cache_file = os.path.join(RAW_DATA_DIR, 'goalie_nhl_seasons.csv')
    if os.path.exists(cache_file):
        cached = pd.read_csv(cache_file)
        missing = sorted(set(player_ids) - set(cached['playerId']))
        if not missing:
            return cached
        combined = pd.concat([cached, makeGoalieSeasonsDataFrame(missing)],
                             ignore_index=True)
        combined.to_csv(cache_file, index=False)
        return combined
    df = makeGoalieSeasonsDataFrame(player_ids)
    df.to_csv(cache_file, index=False)
    return df


def appendMissingBirthDates(player_ids):
    """getAllBirthDatesWithCache returns the cache as-is when it exists; this
    also fetches ids the cache lacks (goalies were never in player_seasons,
    so the draft-era birthdate build skipped them).
    """
    cache_file = os.path.join(RAW_DATA_DIR, 'player_birthdates.csv')
    if not os.path.exists(cache_file):
        return getAllBirthDatesWithCache(player_ids)
    cached = pd.read_csv(cache_file)
    missing = sorted(set(player_ids) - set(cached['playerId']))
    if not missing:
        return cached
    combined = pd.concat([cached, makeAllBirthDatesDataFrame(missing)],
                         ignore_index=True)
    combined.to_csv(cache_file, index=False)
    return combined
```

Note: `RAW_DATA_DIR` must be read inside the functions via the module global (as written) so the tests' `monkeypatch.setattr(dataProcessing, 'RAW_DATA_DIR', ...)` takes effect — do not capture it as a default argument.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_goalie_seasons.py -v`
Expected: ALL PASS (5 tests).

- [ ] **Step 5: Commit**

```powershell
git add src/dataProcessing.py tests/test_goalie_seasons.py
git commit -m "feat: fetch NHL API goalie season records with permanent cache"
```

---

### Task 3: MoneyPuck goalie loader + merged goalie_seasons builder

**Files:**
- Modify: `src/moneypuck.py` (constants near line 20, function after `buildPlayerSeasons`)
- Create: `src/features/goalies.py`
- Test: `tests/test_goalie_seasons.py` (append)

**Interfaces:**
- Consumes: `fantasyPoints.calculateGoaliePoints(stats)` (Task 1).
- Produces:
  - `moneypuck.loadGoalieSeasons(history_file=..., current_file=...) -> pd.DataFrame` — one row per (playerId, season), columns `playerId, season, name, games_played, icetime, xGoals, goals, ongoal`.
  - `src/features/goalies.py::build_goalie_seasons(mp_seasons, nhl_seasons) -> pd.DataFrame` — inner merge on (playerId, season); adds `full_name, position('G'), saves, fantasyPoints, fpPerGame, gsax, save_pct, xsave_delta`. Task 5's `build_goalie_features` consumes this exact output.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_goalie_seasons.py`:

```python
from src import moneypuck
from src.features import goalies as goalie_features


def _mp_situation_fixture(path):
    rows = []
    for situation, icetime, xg, goals, ongoal in [
        ('all', 180000.0, 140.0, 120.0, 1500.0),
        ('5on5', 150000.0, 90.0, 80.0, 1100.0),
        ('4on5', 15000.0, 40.0, 30.0, 300.0),
        ('5on4', 12000.0, 5.0, 5.0, 50.0),
        ('other', 3000.0, 5.0, 5.0, 50.0),
    ]:
        rows.append({'playerId': 1, 'season': 2023, 'name': 'Test Goalie',
                     'team': 'WPG', 'position': 'G', 'situation': situation,
                     'games_played': 60, 'icetime': icetime, 'xGoals': xg,
                     'goals': goals, 'ongoal': ongoal})
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_goalie_seasons_keeps_only_all_situation(tmp_path):
    history = tmp_path / 'hist.csv'
    current = tmp_path / 'curr.csv'
    _mp_situation_fixture(history)
    _mp_situation_fixture(current)

    df = moneypuck.loadGoalieSeasons(history_file=str(history),
                                     current_file=str(current))

    assert 'situation' not in df.columns
    # Both files carry the same (playerId, season), so the stint-groupby sums
    # the two 'all' rows into one: xGoals = 140 x 2 = 280. If situation rows
    # leaked, xGoals would include 90+40+5+5 per file (560 total).
    assert len(df) == 1
    assert df['xGoals'].sum() == 280.0


def test_load_goalie_seasons_raises_when_file_missing(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        moneypuck.loadGoalieSeasons(history_file=str(tmp_path / 'nope.csv'),
                                    current_file=str(tmp_path / 'nope2.csv'))


def test_build_goalie_seasons_scores_regulation_losses_only():
    mp = pd.DataFrame([{'playerId': 1, 'season': 2023, 'name': 'Test Goalie',
                        'games_played': 60, 'icetime': 180000.0,
                        'xGoals': 150.0, 'goals': 158.0, 'ongoal': 1814.0}])
    nhl = pd.DataFrame([{'playerId': 1, 'season': 2023, 'gamesPlayed': 60,
                         'gamesStarted': 60, 'wins': 37, 'losses': 19,
                         'otLosses': 4, 'shutouts': 5, 'goalsAgainst': 158,
                         'shotsAgainst': 1814}])

    out = goalie_features.build_goalie_seasons(mp, nhl)

    assert len(out) == 1
    row = out.iloc[0]
    assert row['position'] == 'G'
    assert row['full_name'] == 'Test Goalie'
    assert row['saves'] == 1814 - 158
    # 45 + 92.5 - 19 - 79 + 248.4 + 15 = 302.9 -- otLosses=4 must NOT subtract
    assert row['fantasyPoints'] == pytest.approx(302.9)
    assert row['fpPerGame'] == pytest.approx(302.9 / 60)
    assert row['gsax'] == pytest.approx(150.0 - 158.0)
    assert row['save_pct'] == pytest.approx(1 - 158.0 / 1814.0)
    assert row['xsave_delta'] == pytest.approx((150.0 - 158.0) / 1814.0)


def test_build_goalie_seasons_drops_rows_without_nhl_match():
    mp = pd.DataFrame([
        {'playerId': 1, 'season': 2023, 'name': 'Matched Goalie',
         'games_played': 60, 'icetime': 180000.0, 'xGoals': 150.0,
         'goals': 158.0, 'ongoal': 1814.0},
        {'playerId': 2, 'season': 2023, 'name': 'Unmatched Goalie',
         'games_played': 10, 'icetime': 30000.0, 'xGoals': 25.0,
         'goals': 30.0, 'ongoal': 300.0},
    ])
    nhl = pd.DataFrame([{'playerId': 1, 'season': 2023, 'gamesPlayed': 60,
                         'gamesStarted': 60, 'wins': 37, 'losses': 19,
                         'otLosses': 4, 'shutouts': 5, 'goalsAgainst': 158,
                         'shotsAgainst': 1814}])

    out = goalie_features.build_goalie_seasons(mp, nhl)
    assert out['playerId'].tolist() == [1]  # no NHL record -> no FP -> dropped
```

Add `import pytest` at the top of `tests/test_goalie_seasons.py` (module level, replacing the function-local import above if you prefer — keep one style).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_goalie_seasons.py -v`
Expected: new tests FAIL with `AttributeError` / `ModuleNotFoundError: No module named 'src.features.goalies'`; Task 2 tests still pass.

- [ ] **Step 3: Write the moneypuck loader**

In `src/moneypuck.py`, add constants after `CURRENT_FILE` (line 20):

```python
GOALIE_DIR = os.path.join(RAW_DATA_DIR, 'goalies')
GOALIE_HISTORY_SEASONS_FILE = os.path.join(GOALIE_DIR, 'goalies_2008_to_2024_seasons.csv')
GOALIE_CURRENT_SEASONS_FILE = os.path.join(GOALIE_DIR, 'goalies_current_seasons.csv')
GOALIE_SEASON_COLUMNS = ['playerId', 'season', 'name', 'situation',
                         'games_played', 'icetime', 'xGoals', 'goals', 'ongoal']
```

Add after `buildPlayerSeasons`:

```python
def loadGoalieSeasons(history_file=GOALIE_HISTORY_SEASONS_FILE,
                      current_file=GOALIE_CURRENT_SEASONS_FILE):
    """Season-level MoneyPuck goalie rows, 'all'-situation only.

    The raw files carry one row per situation per goalie-season (and one row
    per team stint for traded goalies); the 'all' row already totals the
    situation rows, so only 'all' survives and stints are summed. `goals`
    here means goals AGAINST; `ongoal` is shots on goal against.
    """
    for path in (history_file, current_file):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{path} missing -- download the goalie season CSVs from "
                "moneypuck.com/data.htm into data/raw/goalies/ "
                "(see that folder's README.md for which file is which)")
    frames = [pd.read_csv(f, usecols=GOALIE_SEASON_COLUMNS)
              for f in (history_file, current_file)]
    df = pd.concat(frames, ignore_index=True)
    df = df[df['situation'] == 'all'].drop(columns=['situation'])
    return (df.groupby(['playerId', 'season'], as_index=False)
              .agg(name=('name', 'first'),
                   games_played=('games_played', 'sum'),
                   icetime=('icetime', 'sum'),
                   xGoals=('xGoals', 'sum'),
                   goals=('goals', 'sum'),
                   ongoal=('ongoal', 'sum')))
```

- [ ] **Step 4: Write the merge builder**

Create `src/features/goalies.py`:

```python
# Goalie draft pipeline: the merged goalie-season table and its draft features.
#
# MoneyPuck goalie data is shot/xGoals data only -- no W/L/SO/GS -- so fantasy
# points come from NHL API season records (src/dataProcessing.py) merged in.
# MoneyPuck contributes the skill features (gsax, expected save%).

import pandas as pd

from src import fantasyPoints


def build_goalie_seasons(mp_seasons: pd.DataFrame,
                         nhl_seasons: pd.DataFrame) -> pd.DataFrame:
    """One scored row per goalie-season: MoneyPuck skill + NHL API record.

    Inner merge on (playerId, season): a row without an NHL record has no
    W/L/SO and cannot be scored. Callers report the hit rate (GATE G1).
    `losses` stays the NHL regulation-only field -- owner confirmed 2026-07-16
    that OT/SO losses are not losses in this league; never add otLosses.
    """
    nhl = nhl_seasons.copy()
    nhl['saves'] = nhl['shotsAgainst'] - nhl['goalsAgainst']
    merged = mp_seasons.merge(nhl, on=['playerId', 'season'], how='inner')
    merged = merged.rename(columns={'name': 'full_name'})
    merged['position'] = 'G'
    merged['fantasyPoints'] = merged.apply(fantasyPoints.calculateGoaliePoints, axis=1)
    merged['fpPerGame'] = (merged['fantasyPoints']
                           / merged['gamesPlayed'].where(merged['gamesPlayed'] > 0))
    merged['gsax'] = merged['xGoals'] - merged['goals']
    merged['save_pct'] = 1 - merged['goals'] / merged['ongoal'].where(merged['ongoal'] > 0)
    merged['xsave_delta'] = merged['gsax'] / merged['ongoal'].where(merged['ongoal'] > 0)
    return merged
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_goalie_seasons.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/moneypuck.py src/features/goalies.py tests/test_goalie_seasons.py
git commit -m "feat: build merged goalie_seasons table (MoneyPuck + NHL API)"
```

---

### Task 4: build_goalie_seasons.py script + real build (GATE G1)

**Files:**
- Create: `scripts/build_goalie_seasons.py`
- Output (gitignored): `data/processed/goalie_seasons.csv`, `data/raw/goalie_nhl_seasons.csv`, appended `data/raw/player_birthdates.csv`

**Interfaces:**
- Consumes: `moneypuck.loadGoalieSeasons()`, `dataProcessing.getGoalieSeasonsWithCache(ids)`, `dataProcessing.appendMissingBirthDates(ids)`, `goalies.build_goalie_seasons(mp, nhl)`.
- Produces: `data/processed/goalie_seasons.csv` — the input Task 5's features read. Columns per Task 3's `build_goalie_seasons` output.

- [ ] **Step 1: Write the script**

Create `scripts/build_goalie_seasons.py`:

```python
r"""Build data/processed/goalie_seasons.csv: MoneyPuck goalie skill data merged
with NHL API season records (W/L/SO/GS) and scored with GOALIE_WEIGHTS.

One-time build per season. First run fetches ~500 goalies' landing pages
(threaded, minutes) into the permanent cache data/raw/goalie_nhl_seasons.csv,
and appends goalie birthDates to data/raw/player_birthdates.csv. At season
rollover, delete goalie_nhl_seasons.csv so everyone's new season is fetched.

    $env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts/build_goalie_seasons.py

PYTHONUTF8=1 is required: getPlayerStats prints response previews with
non-ASCII names (cp1252 consoles crash otherwise).
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src import dataProcessing  # noqa: E402
from src import moneypuck  # noqa: E402
from src.features import goalies  # noqa: E402

OUT_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'goalie_seasons.csv')


def main():
    mp = moneypuck.loadGoalieSeasons()
    ids = sorted(mp['playerId'].unique().tolist())
    print(f"MoneyPuck: {len(mp)} goalie-season rows, {len(ids)} goalies")

    print("Fetching NHL API season records (threaded; minutes on first run)...")
    nhl = dataProcessing.getGoalieSeasonsWithCache(ids)

    print("Appending goalie birthDates to the shared cache...")
    dataProcessing.appendMissingBirthDates(ids)

    seasons = goalies.build_goalie_seasons(mp, nhl)
    seasons.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}")

    # ---- GATE G1 acceptance checks ----------------------------------------
    hit_rate = len(seasons) / len(mp)
    print("\n" + "=" * 60)
    print("GATE G1 acceptance")
    print("=" * 60)
    print(f"rows:               {len(seasons):,} (expect ~1,400-1,700)")
    print(f"seasons:            {seasons['season'].nunique()} "
          f"({seasons['season'].min()}-{seasons['season'].max()}; expect 18)")
    print(f"merge hit rate:     {hit_rate:.1%} of MoneyPuck rows (expect >= 95%)")
    print("  a low hit rate means the playerId or season-key join is broken --")
    print("  measure before trusting (the birthdates lesson).")
    if len(seasons) > 3000:
        print("  WARNING: row count ~5x expected => situation rows leaked through.")

    hellebuyck = seasons[
        seasons['full_name'].str.contains('Hellebuyck', case=False, na=False)
        & (seasons['season'] == 2023)]
    print("\nHellebuyck 2023-24 spot-check (verify against hockey-reference.com):")
    if hellebuyck.empty:
        print("  NOT FOUND -- check name/join handling before trusting output.")
    else:
        r = hellebuyck.iloc[0]
        print(f"  GP {r['gamesPlayed']:.0f} | GS {r['gamesStarted']:.0f} | "
              f"W {r['wins']:.0f} | L {r['losses']:.0f} | SO {r['shutouts']:.0f} | "
              f"SV {r['saves']:.0f} | FP {r['fantasyPoints']:.1f} "
              f"({r['fpPerGame']:.2f}/gm)")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run the build for real**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts/build_goalie_seasons.py`
Expected: completes in minutes; GATE G1 block prints.

- [ ] **Step 3: Verify GATE G1**

- Row count in 1,400–1,700 and 18 seasons (2008–2025). ~5x that = situation leak: stop and debug `loadGoalieSeasons`.
- Merge hit rate ≥ 95%. If lower, inspect a few unmatched (playerId, season) pairs by hand before proceeding.
- Hand-verify the Hellebuyck line against hockey-reference.com (2023-24: 60 GP, 37 W, 5 SO expected; regulation-L will be lower than hockey-reference's combined L — that's correct for this league).
- Record the printed numbers; Task 10 writes them into PROJECT-PLAN.md's Learning Log.

- [ ] **Step 4: Run the full suite (regression check)**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: only the 1 pre-existing `test_moneypuck` failure.

- [ ] **Step 5: Commit**

```powershell
git add scripts/build_goalie_seasons.py
git commit -m "feat: add goalie_seasons build script with GATE G1 checks"
```

---

### Task 5: Shared age helper + goalie draft features (GATE G2)

**Files:**
- Modify: `src/features/shared.py` (add function; keep the existing stub untouched)
- Modify: `src/features/draft.py:56-77` (replace inline birthdate block with the shared helper)
- Modify: `src/features/goalies.py` (append `build_goalie_features`)
- Test: `tests/test_goalie_features.py` (create)

**Interfaces:**
- Consumes: Task 3's `build_goalie_seasons` output columns (`playerId, season, gamesPlayed, gamesStarted, icetime, gsax, fpPerGame, save_pct, xsave_delta, ...`).
- Produces:
  - `shared.add_age_at_season_start(df) -> pd.DataFrame` — merges `data/raw/player_birthdates.csv`, adds `age_at_season_start` (fractional years at Oct-1); NaN when cache/player missing.
  - `goalies.build_goalie_features(goalie_seasons) -> pd.DataFrame` — adds `career_games, gs_share, gsax_per60, fp_delta, fp_w3, gp_w3, age_at_season_start, target_fpPerGame, target_gamesPlayed`. Task 6 trains on this; Task 8 predicts from it (and uses `gp_w3` for projected GP).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_goalie_features.py`:

```python
import pandas as pd
import pytest

from src.features import goalies as goalie_features


def _seasons(rows):
    base = {'full_name': 'G', 'position': 'G', 'gamesStarted': 50,
            'icetime': 180000.0, 'gsax': 5.0, 'save_pct': 0.91,
            'xsave_delta': 0.004, 'fantasyPoints': 250.0,
            'wins': 30, 'losses': 15, 'shutouts': 3, 'goalsAgainst': 140,
            'saves': 1500, 'shotsAgainst': 1640, 'xGoals': 145.0,
            'goals': 140.0, 'ongoal': 1640.0, 'games_played': 55}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_target_is_next_consecutive_season_only():
    df = _seasons([
        {'playerId': 1, 'season': 2020, 'gamesPlayed': 50, 'fpPerGame': 4.0},
        {'playerId': 1, 'season': 2021, 'gamesPlayed': 55, 'fpPerGame': 4.5},
        {'playerId': 1, 'season': 2023, 'gamesPlayed': 60, 'fpPerGame': 5.0},  # gap
    ])
    out = goalie_features.build_goalie_features(df).set_index('season')

    assert out.loc[2020, 'target_fpPerGame'] == pytest.approx(4.5)
    assert out.loc[2020, 'target_gamesPlayed'] == 55
    # 2021 -> 2023 is a gap season: no target (GATE G2 leakage discipline)
    assert pd.isna(out.loc[2021, 'target_fpPerGame'])
    assert pd.isna(out.loc[2023, 'target_fpPerGame'])


def test_lags_do_not_bleed_across_players():
    df = _seasons([
        {'playerId': 1, 'season': 2022, 'gamesPlayed': 60, 'fpPerGame': 5.0},
        {'playerId': 2, 'season': 2023, 'gamesPlayed': 40, 'fpPerGame': 2.0},
    ])
    out = goalie_features.build_goalie_features(df)
    player2 = out[out['playerId'] == 2].iloc[0]
    assert pd.isna(player2['fp_delta'])  # not 2.0 - 5.0


def test_fp_w3_and_gp_w3_renormalize_missing_history():
    df = _seasons([
        {'playerId': 1, 'season': 2021, 'gamesPlayed': 40, 'fpPerGame': 3.0},
        {'playerId': 1, 'season': 2022, 'gamesPlayed': 60, 'fpPerGame': 5.0},
    ])
    out = goalie_features.build_goalie_features(df).set_index('season')
    # 2022 has 2 seasons of history: (0.5*5 + 0.3*3) / 0.8
    assert out.loc[2022, 'fp_w3'] == pytest.approx((0.5 * 5.0 + 0.3 * 3.0) / 0.8)
    assert out.loc[2022, 'gp_w3'] == pytest.approx((0.5 * 60 + 0.3 * 40) / 0.8)
    # single-season goalie: weight renormalizes to just the own season
    assert out.loc[2021, 'fp_w3'] == pytest.approx(3.0)


def test_workload_and_rate_features():
    df = _seasons([{'playerId': 1, 'season': 2023, 'gamesPlayed': 60,
                    'fpPerGame': 5.0, 'gamesStarted': 58,
                    'icetime': 200000.0, 'gsax': 10.0}])
    out = goalie_features.build_goalie_features(df).iloc[0]
    assert out['gs_share'] == pytest.approx(58 / 82)
    assert out['gsax_per60'] == pytest.approx(10.0 / 200000.0 * 3600)
    assert out['career_games'] == 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_goalie_features.py -v`
Expected: FAIL with `AttributeError: ... no attribute 'build_goalie_features'`.

- [ ] **Step 3: Add the shared age helper**

In `src/features/shared.py`, add at the top `import os` and `import pandas as pd` (keep whatever exists), then append:

```python
def add_age_at_season_start(df: pd.DataFrame) -> pd.DataFrame:
    """Merge data/raw/player_birthdates.csv (built by scripts/build_birthdates.py,
    extended with goalie ids by scripts/build_goalie_seasons.py) and add
    age_at_season_start: fractional years at an Oct-1 season start.
    Missing cache or missing player -> NaN age, never a crash.
    """
    birthdates_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'data', 'raw', 'player_birthdates.csv')
    df = df.copy()
    if not os.path.exists(birthdates_path):
        print("player_birthdates.csv not found -- run scripts/build_birthdates.py; "
              "age_at_season_start set to NaN")
        df['age_at_season_start'] = pd.NA
        return df
    birthdates = (pd.read_csv(birthdates_path)[['playerId', 'birthDate']]
                  .drop_duplicates('playerId'))
    df = df.merge(birthdates, on='playerId', how='left')
    birth = pd.to_datetime(df['birthDate'], errors='coerce')
    # MoneyPuck season 2023 == the 2023-24 season, starting ~Oct 1, 2023.
    season_start = pd.to_datetime(df['season'].astype(str) + '-10-01')
    df['age_at_season_start'] = (season_start - birth).dt.days / 365.25
    return df
```

- [ ] **Step 4: Refactor draft.py to use it**

In `src/features/draft.py`, replace the whole birthdate block (lines 57–77, from the `# Age at season start.` comment through the `else:` branch that sets `pd.NA`) with:

```python
    # Age at season start -- shared with the goalie features (same birthdate
    # cache, same Oct-1 convention). See src/features/shared.py.
    sorted_player_seasons = shared.add_age_at_season_start(sorted_player_seasons)
```

and add `from src.features import shared` to the imports (drop the now-unused `import os` if nothing else uses it).

- [ ] **Step 5: Add build_goalie_features**

Append to `src/features/goalies.py` (add `from src.features import shared` to its imports):

```python
def build_goalie_features(goalie_seasons: pd.DataFrame) -> pd.DataFrame:
    """Draft features from the goalie_seasons table.

    Same leakage discipline as src/features/draft.py (GATE G2): each row IS a
    concluded season, so own-season columns are legitimate features with no
    shift; only the target shifts, masked to consecutive seasons; every lag is
    groupby(playerId)-scoped. No position one-hots -- every row is a G.
    """
    df = goalie_seasons.sort_values(['playerId', 'season']).copy()
    df['career_games'] = df.groupby('playerId')['gamesPlayed'].cumsum()
    # workload is the dominant goalie fantasy signal (starter vs backup)
    df['gs_share'] = df['gamesStarted'] / 82
    df['gsax_per60'] = (df['gsax'] / df['icetime'].where(df['icetime'] > 0)) * 3600

    g = df.groupby('playerId')
    df['fp_delta'] = g['fpPerGame'].diff()
    # 50/30/20 weighted recency, renormalized when history is short -- the
    # same scheme as the skater fp_w3. gp_w3 feeds the projected-GP heuristic.
    for col, out in (('fpPerGame', 'fp_w3'), ('gamesPlayed', 'gp_w3')):
        w = pd.concat([df[col] * 0.5,
                       g[col].shift(1) * 0.3,
                       g[col].shift(2) * 0.2], axis=1)
        weights_present = w.notna().mul([0.5, 0.3, 0.2]).sum(axis=1)
        df[out] = w.sum(axis=1) / weights_present

    df = shared.add_age_at_season_start(df)

    g = df.groupby('playerId')  # re-group: the merge above changed df
    next_season = g['season'].shift(-1)
    df['target_fpPerGame'] = g['fpPerGame'].shift(-1).where(
        next_season == df['season'] + 1)
    df['target_gamesPlayed'] = g['gamesPlayed'].shift(-1).where(
        next_season == df['season'] + 1)
    return df
```

- [ ] **Step 6: Run tests to verify they pass, plus full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_goalie_features.py -v`
Expected: ALL PASS (4 tests).

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: only the 1 pre-existing `test_moneypuck` failure — the draft.py refactor must not break anything.

- [ ] **Step 7: Verify the draft refactor on real data (behavior unchanged)**

Run: `.\.venv\Scripts\python.exe -c "from main import loadPlayerSeasonFeatures; df = loadPlayerSeasonFeatures(); print(df['age_at_season_start'].notna().mean())"`
Expected: prints ~1.0 (same ~100% age coverage as before the refactor).

- [ ] **Step 8: Commit**

```powershell
git add src/features/shared.py src/features/draft.py src/features/goalies.py tests/test_goalie_features.py
git commit -m "feat: add goalie draft features; share age helper with skater features"
```

---

### Task 6: Goalie ranker model + train-goalies CLI + real training (GATE G3)

**Files:**
- Create: `src/models/goalieDraft.py`
- Modify: `main.py` (import, `trainGoalies`, subparser, dispatch)
- Output (gitignored): `models/goalieDraft/model.pkl`, `reports/goalie_feature_importance.png`

**Interfaces:**
- Consumes: Task 5's `build_goalie_features` output.
- Produces:
  - `goalieDraft.train(df)` — runs the full G3 protocol and saves a payload.
  - `goalieDraft.predict(df) -> pd.Series` named `projected_fpPerGame`, indexed like `df`. Works whether the saved payload is the XGBoost model (`kind: 'xgb'`) or Baseline B (`kind: 'baseline_b'`, returns `df['fp_w3']`).
  - `main.py train-goalies` CLI command.

- [ ] **Step 1: Write the model module**

Create `src/models/goalieDraft.py`. This deliberately mirrors `src/models/draft.py`'s protocol, with three differences: goalie feature list, `MIN_GP = 15`, and an honest ship-the-baseline branch (the payload records what shipped; `predict` obeys it). No SHAP/explainability in v1.

```python
# Goalie draft ranker: train, save, load, and predict next-season FP/game.
#
# Same interface as every model module (train/predict/load/save) and the same
# Phase B3 protocol as src/models/draft.py: baselines first, Ridge as a
# coefficient-sign diagnostic, XGBoost on a season-based PredefinedSplit.
# GATE G3: XGBoost ships only if it beats BOTH baselines on val Spearman --
# otherwise the saved payload IS Baseline B (fp_w3) and predict() returns it.
# With only ~600-900 eligible goalie rows a baseline win is the expected
# outcome, not a failure state.

import os
import pickle

import matplotlib.pyplot as plt
import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import make_scorer, mean_absolute_error
from sklearn.model_selection import PredefinedSplit, RandomizedSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'goalieDraft', 'model.pkl')

TARGET_COL = 'target_fpPerGame'
FEATURE_COLS = [
    'fpPerGame', 'fp_delta', 'fp_w3', 'gsax_per60', 'save_pct', 'xsave_delta',
    'gs_share', 'career_games', 'age_at_season_start',
]

TRAIN_MAX_SEASON = 2021
VAL_SEASONS = (2022, 2023)
# Test season 2024 gets ONE manual look after the gate, then is never touched.

# Goalie seasons max ~65 games; 20 (the skater floor) would discard legitimate
# backup seasons. 15 keeps backups while excluding cameos.
MIN_GP = 15


def _spearman(y_true, y_pred):
    return spearmanr(y_true, y_pred).statistic


def _feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"feature columns missing from input df: {missing}")
    X = df.reindex(columns=FEATURE_COLS)
    return X.apply(lambda s: pd.to_numeric(s, errors='coerce')).astype('float64')


def train(df: pd.DataFrame):
    """Run the GATE G3 protocol and save whichever ranker ships.

    Record the printed numbers in PROJECT-PLAN.md's Learning Log -- text,
    not just the reports/ plot.
    """
    eligible = df[
        (df['gamesPlayed'] >= MIN_GP)
        & (df['target_gamesPlayed'] >= MIN_GP)
        & df[TARGET_COL].notna()
    ]
    train_df = eligible[eligible['season'] <= TRAIN_MAX_SEASON]
    val_df = eligible[eligible['season'].isin(VAL_SEASONS)]
    print(f"train rows: {len(train_df)} (seasons <= {TRAIN_MAX_SEASON}), "
          f"val rows: {len(val_df)} (seasons {VAL_SEASONS})")

    X_train = _feature_matrix(train_df)
    y_train = train_df[TARGET_COL]
    X_val = _feature_matrix(val_df)
    y_val = val_df[TARGET_COL]

    baseline_rhos = {}
    for name, val_pred in [('Baseline A (last-season FP/g)', val_df['fpPerGame']),
                           ('Baseline B (fp_w3 weighted)', val_df['fp_w3'])]:
        baseline_rhos[name] = _spearman(y_val, val_pred)
        print(f"{name}: val Spearman {baseline_rhos[name]:.4f}, "
              f"MAE {mean_absolute_error(y_val, val_pred):.4f}")

    ridge = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge())
    ridge.fit(X_train, y_train)
    ridge_pred = ridge.predict(X_val)
    print(f"Ridge: val Spearman {_spearman(y_val, ridge_pred):.4f}, "
          f"MAE {mean_absolute_error(y_val, ridge_pred):.4f}")
    coefs = pd.Series(ridge[-1].coef_, index=FEATURE_COLS).sort_values()
    print("Ridge coefficients (standardized). Sanity-check signs -- fp_w3 and "
          "gs_share should be strongly positive; a wrong sign is a feature bug:")
    print(coefs.to_string())

    split_indicator = [-1] * len(X_train) + [0] * len(X_val)
    ps = PredefinedSplit(split_indicator)
    X_all = pd.concat([X_train, X_val])
    y_all = pd.concat([y_train, y_val])
    param_dist = {
        'n_estimators': [100, 200, 300],
        'max_depth': [3, 4, 5],
        'learning_rate': [0.01, 0.05, 0.1],
        'subsample': [0.7, 0.8, 0.9],
        'colsample_bytree': [0.7, 0.8, 1.0],
    }
    # refit=False: evaluate honestly on a train-only fit first (see models/draft.py)
    search = RandomizedSearchCV(
        xgb.XGBRegressor(random_state=42),
        param_distributions=param_dist,
        n_iter=20,
        scoring=make_scorer(_spearman),
        cv=ps,
        random_state=42,
        refit=False,
        verbose=1,
    )
    search.fit(X_all, y_all)
    print("Best params:", search.best_params_)

    eval_model = xgb.XGBRegressor(random_state=42, **search.best_params_)
    eval_model.fit(X_train, y_train)
    xgb_pred = eval_model.predict(X_val)
    xgb_rho = _spearman(y_val, xgb_pred)
    print(f"XGBoost: val Spearman {xgb_rho:.4f}, "
          f"MAE {mean_absolute_error(y_val, xgb_pred):.4f}")

    if all(xgb_rho > rho for rho in baseline_rhos.values()):
        print("GATE G3: PASS -- XGBoost beats both baselines on val Spearman. "
              "Confirm on test-2024 exactly once, then stop touching test.")
        model = xgb.XGBRegressor(random_state=42, **search.best_params_)
        model.fit(X_all, y_all)
        save({'kind': 'xgb', 'model': model, 'feature_cols': FEATURE_COLS})
        os.makedirs('reports', exist_ok=True)
        xgb.plot_importance(model, max_num_features=len(FEATURE_COLS))
        plt.title('Goalie Draft Model - Feature Importances')
        plt.tight_layout()
        plt.savefig('reports/goalie_feature_importance.png')
        plt.close()
    else:
        print("GATE G3: FAIL -- XGBoost does not beat both baselines. Shipping "
              "Baseline B (fp_w3) as the goalie ranker; predict() will return "
              "fp_w3. A legitimate outcome at this sample size, not a failure.")
        save({'kind': 'baseline_b', 'model': None, 'feature_cols': FEATURE_COLS})


def predict(df: pd.DataFrame) -> pd.Series:
    """Projected next-season goalie FP/game from whichever ranker shipped."""
    payload = load()
    if payload['kind'] == 'baseline_b':
        return pd.Series(pd.to_numeric(df['fp_w3'], errors='coerce').to_numpy(),
                         index=df.index, name='projected_fpPerGame')
    X = _feature_matrix(df)
    preds = payload['model'].predict(X)
    return pd.Series(preds, index=df.index, name='projected_fpPerGame')


def load():
    """Load the saved payload: {'kind', 'model', 'feature_cols'}."""
    with open(MODEL_PATH, 'rb') as f:
        return pickle.load(f)


def save(payload):
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(payload, f)
```

- [ ] **Step 2: Wire the CLI**

In `main.py`:

1. Add import: `from src.models import goalieDraft as goalieDraftModel` and `from src.features import goalies as goalieFeatures` (with the other imports).
2. Add near `KEEPER_RANKINGS_PATH` (line 23): `GOALIE_SEASONS_PATH = os.path.join('data', 'processed', 'goalie_seasons.csv')`
3. Add after `trainDraft()` (line 153):

```python
def loadGoalieSeasonFeatures():
    """Goalie draft feature rows from the cached goalie-season table (built by
    scripts/build_goalie_seasons.py -- see data/raw/goalies/README.md)."""
    if not os.path.exists(GOALIE_SEASONS_PATH):
        raise FileNotFoundError(
            f"{GOALIE_SEASONS_PATH} missing -- run scripts/build_goalie_seasons.py first")
    return goalieFeatures.build_goalie_features(pd.read_csv(GOALIE_SEASONS_PATH))


def trainGoalies():
    """Train the goalie draft ranker (GATE G3 protocol, see the spec)."""
    goalieDraftModel.train(loadGoalieSeasonFeatures())
```

4. Add subparser after the `'train-draft'` line (line 271): `sub.add_parser('train-goalies', help='train the goalie draft ranker on historical goalie-seasons')`
5. Add dispatch after the `'train-draft'` branch: `elif args.command == 'train-goalies': trainGoalies()`

- [ ] **Step 3: Train for real (GATE G3)**

Run: `.\.venv\Scripts\python.exe main.py train-goalies`
Expected: prints train/val row counts (train ~500–700, val ~100–160), both baselines' Spearman/MAE, Ridge coefficients, XGBoost result, and the GATE G3 verdict; saves `models/goalieDraft/model.pkl`.

- [ ] **Step 4: Verify GATE G3 honestly**

- Record every printed number (baselines, Ridge, XGBoost, verdict) — Task 10 puts them in the Learning Log.
- Sanity-check Ridge signs: `fp_w3` and `gs_share` positive. A wrong sign = feature bug; stop and debug before accepting any verdict.
- If val Spearman is suspiciously high (≥ 0.95), suspect leakage — recheck the target mask in Task 5 before celebrating.
- Either verdict (PASS or ship-Baseline-B) is acceptable; do NOT retune until XGBoost wins. If PASS: run the one allowed test-2024 look now — filter features to `season == 2024` rows with targets, compute Spearman with the saved model, record it, and never touch test again.

- [ ] **Step 5: Verify predict() round-trips**

Run: `.\.venv\Scripts\python.exe -c "from main import loadGoalieSeasonFeatures; from src.models import goalieDraft; df = loadGoalieSeasonFeatures(); cur = df[df['season'] == 2025]; p = goalieDraft.predict(cur); print(len(p), p.describe())"`
Expected: ~80–95 predictions, plausible FP/g range (roughly 2–6).

- [ ] **Step 6: Commit**

```powershell
git add src/models/goalieDraft.py main.py
git commit -m "feat: goalie draft ranker with baseline-shipping gate + train-goalies CLI"
```

---

### Task 7: keeper.py — goalie eligibility, replacement rank G, vorp helper

**Files:**
- Modify: `src/keeper.py`
- Modify: `scripts/build_keeper_summary.py:68` (prompt copy)
- Test: `tests/test_keeper.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `keeper.REPLACEMENT_RANKS` gains `"G": 20`; `keeper.ELIGIBLE_POSITIONS` replaces `SKATER_POSITIONS` (grep for other usages before deleting the old name).
  - `keeper.replacement_levels(projections)` — now SKIPS (with a warning print) positions with zero rows on the board (skaters-only degraded mode), still raises when a position is present but shallower than its rank.
  - `keeper.vorp_column(projections) -> pd.Series` — `projected_total - replacement_level[position]`, NaN where no level exists. Task 8 uses it for the draft board.
  - `keeper.analyze_keepers` treats goalies as full candidates (no exclusion branch).

- [ ] **Step 1: Update the tests**

In `tests/test_keeper.py`:

1. In `_projection_board()`, add a goalie tier to the position list — replace the list with:

```python
    for position, count, top_total in [
        ("C", 30, 200),
        ("L", 30, 180),
        ("R", 30, 160),
        ("D", 90, 220),
        ("G", 30, 240),
    ]:
```

2. Replace `test_keeper_analysis_keeps_goalies_and_unmatched_players_in_the_audit` entirely with:

```python
def test_keeper_analysis_treats_goalies_as_full_candidates():
    roster = [
        {"name": "G Player 1", "player_id": "g1", "eligible_positions": ["G"]},
        {"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"]},
        {"name": "L Player 1", "player_id": "y2", "eligible_positions": ["LW"]},
        {"name": "R Player 1", "player_id": "y3", "eligible_positions": ["RW"]},
        {"name": "Not On Board", "player_id": "u1", "eligible_positions": ["C"]},
    ]

    rankings = keeper.analyze_keepers(roster, _projection_board())
    recommended = rankings[rankings["is_recommended"]].sort_values("keeper_rank")

    # Raw surpluses on this fixture: C/L/R = 23 each (rank-24 replacement),
    # G = 240 - 221 = 19 (rank-20 replacement). Four matched candidates fill
    # the four slots, goalie last -- the point is the goalie COMPETES on value
    # instead of being excluded.
    assert recommended["full_name"].tolist() == [
        "C Player 1", "L Player 1", "R Player 1", "G Player 1",
    ]
    goalie_row = recommended[recommended["full_name"] == "G Player 1"].iloc[0]
    assert goalie_row["raw_keeper_value"] == pytest.approx(19.0)
    unmatched = rankings[rankings["yahoo_name"] == "Not On Board"].iloc[0]
    assert unmatched["excluded_reason"] == "No projection match"


def test_vorp_column_is_nan_for_positions_without_replacement_level():
    board = _projection_board()
    skaters_only = board[board["position"] != "G"].copy()
    vorp = keeper.vorp_column(skaters_only)
    assert vorp.notna().all()

    with_goalies = keeper.vorp_column(board)
    g_rows = board["position"] == "G"
    # G replacement = 20th goalie = 240-19 = 221
    top_goalie = board[g_rows].sort_values("projected_total", ascending=False).index[0]
    assert with_goalies.loc[top_goalie] == pytest.approx(240.0 - 221.0)
```

3. Add `import pytest` to the imports.

Note the first existing test (`test_keeper_analysis_recommends_four_skaters_with_late_round_costs`) uses a skater-only roster against a board that now contains goalies; its expected recommendation order is unchanged (no goalie in that roster) but `round_pick_costs` bands shift because 30 G rows joined the board — verify it still passes; if the round-cost assertion breaks, the fixture's totals overlap differently: keep the assertion `net = raw - pick_cost` (it's invariant) and drop nothing else.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_keeper.py -v`
Expected: new tests FAIL (`AttributeError: ... no attribute 'vorp_column'`; goalie test fails on the exclusion branch).

- [ ] **Step 3: Implement the keeper changes**

In `src/keeper.py`:

1. Module docstring: change to `"""Keeper value calculations for skaters and goalies. ..."""` (drop "Skater-only").
2. Line 15–16: replace with:

```python
REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48, "G": 20}
ELIGIBLE_POSITIONS = frozenset(REPLACEMENT_RANKS)
```

3. `_position` (line 28): add `"G": "G"` to the mapping dict.
4. Delete the `_goalie` function (lines 31–39) and its branch in `analyze_keepers` (lines 96–100).
5. `replacement_levels`: replace the body with:

```python
def replacement_levels(projections: pd.DataFrame) -> dict[str, float]:
    """Positional replacement totals. A position absent from the board is
    skipped with a warning (e.g. goalies in skaters-only degraded mode);
    a position present but shallower than its rank is a data bug -> raise."""
    levels = {}
    for position, rank in REPLACEMENT_RANKS.items():
        players = projections[projections["position"] == position].sort_values(
            "projected_total", ascending=False
        )
        if players.empty:
            print(f"⚠️  No projected {position} rows on the board; "
                  f"skipping the {position} replacement level")
            continue
        if len(players) < rank:
            raise ValueError(f"Need at least {rank} projected {position}s for keeper values")
        levels[position] = float(players.iloc[rank - 1]["projected_total"])
    return levels
```

6. Add after `round_pick_costs`:

```python
def vorp_column(projections: pd.DataFrame) -> pd.Series:
    """Value over positional replacement for every row: projected_total minus
    the position's replacement level. NaN where no level exists (position
    missing from the board), so degraded skaters-only exports still work."""
    levels = replacement_levels(projections)
    return pd.to_numeric(projections["projected_total"], errors="coerce") - (
        projections["position"].map(levels)
    )
```

7. In `analyze_keepers`, replace both `SKATER_POSITIONS` references (lines 71, 111) with `ELIGIBLE_POSITIONS`, and change the excluded reason string `"Not a skater projection"` to `"No positional projection"`.

8. In `scripts/build_keeper_summary.py` line 68, remove the sentence fragment `"Do not mention goalies, "` from the prompt string (keep the rest of the sentence grammatical — read the full string first and reflow it).

- [ ] **Step 4: Run tests to verify they pass, plus full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_keeper.py tests/test_keeper_summary.py tests/test_api_export_keeper.py -v`
Expected: ALL PASS. If `test_keeper_summary.py` asserted the goalie sentence, update that assertion to the new prompt text.

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: only the 1 pre-existing `test_moneypuck` failure.

- [ ] **Step 5: Commit**

```powershell
git add src/keeper.py scripts/build_keeper_summary.py tests/test_keeper.py tests/test_keeper_summary.py
git commit -m "feat: goalies are full keeper candidates; add G replacement rank and vorp helper"
```

---

### Task 8: main.py draft/keeper integration + real run (GATE G4)

**Files:**
- Modify: `main.py` (`buildCurrentDraftProjections`, new `buildCurrentGoalieProjections` + `buildFullProjections`, `runDraft`, `runKeeper`)
- Output (gitignored): regenerated `data/processed/draft_rankings.csv`

**Interfaces:**
- Consumes: `goalieDraftModel.predict(df)` (Task 6), `keeper.vorp_column(board)` (Task 7), `gp_w3` from Task 5.
- Produces: `draft_rankings.csv` gains `projected_gp` (78 for skaters, weighted-capped for goalies) and `vorp` columns; rows sorted by `vorp` descending; goalie rows with `position == 'G'`. Task 9's export reads these columns.

- [ ] **Step 1: Add the goalie projection builders**

In `main.py`, add after `buildCurrentDraftProjections` (line 204):

```python
GOALIE_GP_CAP = 65        # a goalie season tops out around 65 starts
GOALIE_DISPLAY_MIN_GP = 15  # display floor, mirrors goalieDraft.MIN_GP


def buildCurrentGoalieProjections():
    """Current-season goalie projections shaped like the skater board.

    projected_total = projected FP/GP x projected GP, where projected GP is
    the 50/30/20 weighted games played capped at GOALIE_GP_CAP -- the x78
    skater assumption is wrong for goalies, where workload IS the value.
    No confidence/factor columns in v1 (the ranker may be Baseline B).
    """
    df = loadGoalieSeasonFeatures()
    current = df[df['season'] == CURRENT_SEASON].copy()
    current['projected_fpPerGame'] = goalieDraftModel.predict(current)

    rankings = current[['playerId', 'full_name', 'position', 'gamesPlayed',
                        'fpPerGame', 'projected_fpPerGame']].copy()
    rankings['age'] = current['age_at_season_start'] + 1
    rankings['projected_gp'] = current['gp_w3'].clip(upper=GOALIE_GP_CAP)
    rankings['projected_total'] = (rankings['projected_fpPerGame']
                                   * rankings['projected_gp'])
    rankings['delta_vs_last'] = (rankings['projected_fpPerGame']
                                 - rankings['fpPerGame'])
    return rankings


def buildFullProjections():
    """Skater + goalie projection board. Goalie prerequisites missing (no
    goalie_seasons.csv or no trained goalie model) degrades to skaters-only
    with a loud warning -- never silently, never fatally."""
    projections = buildCurrentDraftProjections()
    projections['projected_gp'] = 78
    try:
        projections = pd.concat(
            [projections, buildCurrentGoalieProjections()], ignore_index=True)
    except FileNotFoundError as e:
        print(f"⚠️  Goalie projections unavailable ({e})")
        print("   Board is SKATERS-ONLY. Run scripts/build_goalie_seasons.py and")
        print("   'python main.py train-goalies' to include goalies.")
    return projections
```

- [ ] **Step 2: Rewire runDraft and runKeeper**

Replace `runDraft` (lines 207–239) with:

```python
def runDraft():
    """Rank this year's draft-eligible (non-keeper) players by projected fantasy value."""
    rankings = buildFullProjections()
    # Display-side GP floors: an injury-shortened season can still carry keeper
    # value, but a tiny-sample rate stat is too noisy for the draft board.
    is_goalie = rankings['position'] == 'G'
    rankings = rankings[
        (~is_goalie & (rankings['gamesPlayed'] >= 20))
        | (is_goalie & (rankings['gamesPlayed'] >= GOALIE_DISPLAY_MIN_GP))
    ].copy()

    # VORP before the keeper filter: replacement level is about league-wide
    # talent depth, not about who happens to still be draftable.
    rankings['vorp'] = keeper.vorp_column(rankings)

    # Draft pool must exclude anyone already kept -- keeper lists aren't in the Yahoo
    # API until draft day, so they're maintained manually in data/raw/keepers.csv.
    # Missing/empty file = keepers not announced yet: warn loudly and rank everyone
    # rather than refuse, so pre-draft-day rankings (and the frontend) still work.
    try:
        keeper_names = keepers.loadKeepers()
        before = len(rankings)
        rankings = keepers.filterOutKeepers(rankings, keeper_names)
        print(f"Keepers: removed {before - len(rankings)} of {len(keeper_names)} listed keepers from the pool")
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  No keeper list applied ({e})")
        print("   Rankings include EVERY player. Fine before keepers are announced;")
        print("   on draft day, fill data/raw/keepers.csv and re-run.")

    # VORP is the default cross-position order (owner decision 2026-07-16).
    rankings = rankings.sort_values('vorp', ascending=False)
    out_path = os.path.join('data', 'processed', 'draft_rankings.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rankings.to_csv(out_path, index=False)
    print(f"\nWrote {len(rankings)} players to {out_path}")

    print("\n=== Top 20 by VORP (cross-position) ===")
    print(rankings[['full_name', 'position', 'age', 'gamesPlayed',
                    'fpPerGame', 'projected_fpPerGame', 'projected_gp',
                    'projected_total', 'vorp', 'delta_vs_last']]
          .head(20)
          .to_string(index=False))

    goalie_rows = rankings[rankings['position'] == 'G']
    if not goalie_rows.empty:
        print("\n=== Top 10 goalies (GATE G4 eyeball) ===")
        print(goalie_rows[['full_name', 'age', 'gamesPlayed', 'fpPerGame',
                           'projected_fpPerGame', 'projected_gp',
                           'projected_total', 'vorp']]
              .head(10)
              .to_string(index=False))
```

In `runKeeper` (line 242), change `projections = buildCurrentDraftProjections()` to `projections = buildFullProjections()`.

- [ ] **Step 3: Run the draft for real**

Run: `.\.venv\Scripts\python.exe main.py draft`
Expected: board writes with goalie rows; the two tables print; no keeper list warning is fine (pre-draft-day mode).

- [ ] **Step 4: Verify GATE G4 (eyeball — a real gate)**

- Top-10 goalies must be Hellebuyck/Shesterkin-tier workhorse starters.
- No backup with a hot 20-game season may outrank a healthy starter on projected **total** (per-game rank may legitimately differ) — scan `projected_gp` for backups near the top.
- Cross-position top-20 by VORP should mix elite skaters with the very best goalies, not be all-goalie or no-goalie. If it looks wrong, it is wrong — debug features (age join, gp_w3, replacement levels) before trusting any metric.
- Confirm degraded mode: `Rename-Item models\goalieDraft\model.pkl model.pkl.bak; .\.venv\Scripts\python.exe main.py draft; Rename-Item models\goalieDraft\model.pkl.bak model.pkl` — expect the loud skaters-only warning and a successful skaters-only CSV, then restore.

Record the top-10 goalie list and the verdict for Task 10's Learning Log entry.

- [ ] **Step 5: Full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: only the 1 pre-existing `test_moneypuck` failure.

- [ ] **Step 6: Commit**

```powershell
git add main.py
git commit -m "feat: goalie rows and VORP ordering on the draft board; goalie-inclusive keeper board"
```

---

### Task 9: api_export + frontend (G filter, VORP column)

**Files:**
- Modify: `api_export.py` (`build_draft_list`, ~line 112)
- Modify: `frontend/src/types/player.ts` (Position union + DraftPlayer fields)
- Modify: `frontend/src/components/rink/DraftBoard.tsx` (positions array, VORP/GP columns, default sort)
- Test: `tests/test_api_export_draft.py` (create)

**Interfaces:**
- Consumes: `draft_rankings.csv` with `vorp` and `projected_gp` (Task 8).
- Produces: each `draft` entry in `frontend_data.json` gains `vorp: float|null` and `projected_gp: float|null`; old CSVs without the columns export `null`s and must not crash.

- [ ] **Step 1: Write the failing export test**

Create `tests/test_api_export_draft.py`:

```python
import pandas as pd

import api_export


BASE_ROW = {
    'playerId': 1, 'full_name': 'Test Goalie', 'position': 'G',
    'gamesPlayed': 60, 'fpPerGame': 4.2, 'projected_fpPerGame': 4.5,
    'projected_total': 270.0, 'delta_vs_last': 0.3, 'age': 30.0,
}


def test_build_draft_list_exports_vorp_and_projected_gp(tmp_path, monkeypatch):
    df = pd.DataFrame([{**BASE_ROW, 'vorp': 42.5, 'projected_gp': 60.0}])
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    entries = api_export.build_draft_list()

    assert entries[0]['vorp'] == 42.5
    assert entries[0]['projected_gp'] == 60.0
    assert entries[0]['positionCode'] == 'G'


def test_build_draft_list_survives_csv_without_vorp_columns(tmp_path, monkeypatch):
    df = pd.DataFrame([BASE_ROW])  # pre-goalie CSV shape
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    entries = api_export.build_draft_list()

    assert entries[0]['vorp'] is None
    assert entries[0]['projected_gp'] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_export_draft.py -v`
Expected: FAIL with `KeyError: 'vorp'`.

- [ ] **Step 3: Implement the export change**

In `api_export.py::build_draft_list`, inside the `draft_list.append({...})` dict (after the `'delta_vs_last'` line), add:

```python
            'vorp': (round(float(row['vorp']), 1)
                     if 'vorp' in df.columns and not pd.isna(row['vorp']) else None),
            'projected_gp': (round(float(row['projected_gp']), 1)
                             if 'projected_gp' in df.columns and not pd.isna(row['projected_gp']) else None),
```

- [ ] **Step 4: Run export tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api_export_draft.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Frontend types and board**

1. `frontend/src/types/player.ts` line 1: `export type Position = 'C' | 'L' | 'R' | 'D' | 'G';`
2. In the `DraftPlayer` interface (the one with `projected_total` near line 61), add:

```typescript
  vorp: number | null;
  projected_gp: number | null;
```

3. In `frontend/src/components/rink/DraftBoard.tsx`:
   - Positions row (line 204): `const positions: (Position | 'ALL')[] = ['ALL', 'C', 'L', 'R', 'D', 'G'];`
   - Default sort (line 166): `const [sortKey, setSortKey] = useState('vorp');`
   - Add a VORP column to the `COLUMNS` array after the `projected_total` column, matching the existing column object shape exactly (read a neighboring column definition first and copy its structure — header/label, `sortValue`, and cell render). Sorting must be null-safe and render `—` for missing values:

```typescript
  {
    key: 'vorp',
    label: 'VORP',
    // old frontend_data.json snapshots lack vorp -- sort them last, render a dash
    sortValue: (p) => p.vorp ?? Number.NEGATIVE_INFINITY,
    // in the cell render: {p.vorp != null ? p.vorp.toFixed(1) : '—'}
  },
```

- [ ] **Step 6: Build the frontend + regenerate the export**

Run: `cd frontend; npm run build; cd ..`
Expected: build succeeds (type errors here mean the DraftPlayer shape or column def doesn't match — fix before continuing).

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe api_export.py`
Expected: succeeds if pickup models/caches are present locally; if it fails on unrelated pickup prerequisites, run the keeper/draft-relevant check instead via the tests above and note it. Spot-check `data/processed/frontend_data.json` contains `"vorp"` in a draft entry: `Select-String -Path data\processed\frontend_data.json -Pattern '"vorp"' -Quiet` prints `True`.

- [ ] **Step 7: Full suite + commit**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: only the 1 pre-existing `test_moneypuck` failure.

```powershell
git add api_export.py tests/test_api_export_draft.py frontend/src/types/player.ts frontend/src/components/rink/DraftBoard.tsx
git commit -m "feat: goalie rows, G filter, and VORP sort on the frontend draft board"
```

---

### Task 10: Bookkeeping — PROJECT-PLAN, skills, operations runbook

**Files:**
- Modify: `PROJECT-PLAN.md` (goalie decision + Learning Log + Current Phase)
- Modify: `.claude/skills/fht-architecture-contract/SKILL.md` (weak-point row, system map)
- Modify: `.claude/skills/fht-draft-campaign/SKILL.md` (Phase D goalie section)
- Modify: `.claude/skills/fht-operations/SKILL.md` (build runbook + season rollover)

**Interfaces:** none — documentation truth-keeping. Numbers come from the gate records in Tasks 4, 6, 8.

- [ ] **Step 1: PROJECT-PLAN.md**

1. Find the "Goalies v1 = NO ML" / goalie section around the weights table (near line 354) and mark it superseded: add a line `**SUPERSEDED 2026-07-16:** goalies now have a trained ranker — see docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md.` Do not delete the weights table (it is still the scoring source of record).
2. Append a Learning Log entry with the recorded GATE G1 numbers (rows, seasons, hit rate, Hellebuyck line), GATE G3 numbers (baselines/Ridge/XGBoost Spearman+MAE, verdict, and the one test-2024 look if taken), and the GATE G4 verdict (top-10 goalie list summary).
3. Update the "Current Phase" section: add the goalie analyzer items as completed with dates.

- [ ] **Step 2: Skill updates**

1. `fht-architecture-contract`: in "Known weak points", remove the row "Goalies have no scoring path" and update its provenance note; in the system map, add `data/raw/goalies/*.csv -> src/moneypuck.py::loadGoalieSeasons` and `src/models/goalieDraft.py` alongside the other models.
2. `fht-draft-campaign`: in "Phase D", replace the "Goalies v1 = NO ML" block with a short pointer: goalie ranker shipped per the 2026-07-16 spec (scoring in `fantasyPoints.GOALIE_WEIGHTS`, model in `src/models/goalieDraft.py`, gates G1–G4 recorded in PROJECT-PLAN Learning Log); update the "Provenance and maintenance" greps (`calculateGoaliePoints` now exists — flip that line).
3. `fht-operations`: add a runbook row for `scripts/build_goalie_seasons.py` (PYTHONUTF8 required, minutes, produces `goalie_seasons.csv` + `goalie_nhl_seasons.csv` cache) and `main.py train-goalies`; add to the season-rollover checklist: re-download the two current goalie CSVs, delete `data/raw/goalie_nhl_seasons.csv`, rebuild, retrain.

- [ ] **Step 3: Final full suite + commit**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: only the 1 pre-existing `test_moneypuck` failure.

```powershell
git add PROJECT-PLAN.md .claude/skills/fht-architecture-contract/SKILL.md .claude/skills/fht-draft-campaign/SKILL.md .claude/skills/fht-operations/SKILL.md
git commit -m "docs: record goalie analyzer gates and update skill library"
```

---

## Plan-level acceptance (after all tasks)

- `python main.py draft` produces a VORP-sorted board where goalies and skaters interleave sensibly (GATE G4 recorded).
- `python main.py keeper` (requires Yahoo OAuth; run manually when credentials are handy) recommends from a goalie-inclusive board; a rostered elite goalie can appear in the four.
- Full suite: only the 1 pre-existing known failure.
- All gate numbers live in PROJECT-PLAN.md's Learning Log as text.
