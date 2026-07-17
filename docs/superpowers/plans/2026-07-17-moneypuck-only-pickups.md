# MoneyPuck-Only Pickup Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~1400 per-player NHL API landing requests in the pickup pipeline with MoneyPuck-derived stats via a new `moneypuck.buildPickupStats` aggregation.

**Architecture:** A new aggregation in `src/moneypuck.py` turns the (already cached) full-situation game logs into one row per player with current-season totals + last-5 totals, scored by the existing `fantasyPoints.moneypuckGamePoints`. `rankFreeAgents` slims to consume that frame; `main.py`/`api_export.py` drop the NHL stats fetches; the frontend drops the `+/-` column. The only NHL API use left in the pickup path is the 24h-cached ~32-request team-roster identity fetch.

**Tech Stack:** Python 3 / pandas / pytest (backend), Next.js + TypeScript (frontend). Spec: `docs/superpowers/specs/2026-07-17-moneypuck-only-pickups-design.md`.

## Global Constraints

- Always invoke Python as `.\.venv\Scripts\python.exe` (Windows; system `python` may be an unrelated interpreter).
- Set `$env:PYTHONUTF8='1'` before running `main.py pickups` / `api_export.py` (known cp1252 console issue).
- `pytest` baseline on main: **2 pre-existing failures** (`test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations`, `test_draft_summaries.py::test_all_summary_calls_allow_the_larger_token_budget`). "Tests pass" means: no NEW failures beyond these two.
- MoneyPuck game frames carry one row per player-game per situation; anything aggregating them must route through `fantasyPoints.moneypuckGamePoints` first (the `'all'` row already totals the others — summing raw rows double-counts).
- `SKATER_WEIGHTS` in `src/fantasyPoints.py` is untouched — it stays the single scoring source of truth.
- `src/moneypuck.py` must NOT grow its own copy of the `CURRENT_SEASON` constant — callers pass the season in.
- **KEEP `dataProcessing.fetchAllPlayers`** — `makeAllBirthDatesDataFrame` still uses it (the spec's original deletion list was corrected on this point).
- The ML training path (`train-pickups`, `src/features/mlFeatures.py`, models) is out of scope — do not touch it.
- No new dependencies.

---

### Task 1: `moneypuck.buildPickupStats`

**Files:**
- Modify: `src/moneypuck.py` (add function after `buildPlayerSeasons`, ~line 145)
- Test: `tests/test_moneypuck.py` (append new tests)

**Interfaces:**
- Consumes: `fantasyPoints.moneypuckGamePoints(games_df)` (existing — collapses situation rows, adds `powerPlayPoints`, `shorthandedPoints`, `fantasyPoints` columns).
- Produces: `buildPickupStats(game_df: pd.DataFrame, season: int) -> pd.DataFrame` with one row per `playerId` and columns: `playerId, name, position, gamesPlayed, goals, assists, points, shots, hits, blocks, powerPlayPoints, shorthandedPoints, fantasyPoints, season_ppg, avgToiSeconds, last5_goals, last5_assists, last5_points, last5_fantasyPoints`. Tasks 2-4 rely on these exact column names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_moneypuck.py`:

```python
def _pickup_row(playerId, gameId, gameDate, situation='all', season=2025,
                name='Player One', position='C', icetime=1200,
                goals=0, pA=0, sA=0, sog=0, hits=0, blocks=0, points=0):
    """Minimal full-situation game-log row for buildPickupStats tests."""
    return {
        'playerId': playerId, 'gameId': gameId, 'gameDate': gameDate,
        'season': season, 'name': name, 'position': position,
        'situation': situation, 'icetime': icetime,
        'I_F_goals': goals, 'I_F_primaryAssists': pA,
        'I_F_secondaryAssists': sA, 'I_F_shotsOnGoal': sog,
        'I_F_hits': hits, 'shotsBlockedByPlayer': blocks,
        'I_F_points': points,
    }


def test_build_pickup_stats_season_totals_no_double_count():
    # Player 1, one game with situation rows: the 5on4 row must feed PPP,
    # not be summed into the season totals (the 'all' row already totals it).
    # FP = 3*1 + 2*1 + 0.15*3 + 0.15*2 + 0.35*1 + 1*1(PPP)
    #    = 3 + 2 + 0.45 + 0.30 + 0.35 + 1 = 7.10
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015, goals=1, pA=1, sog=3, hits=2,
                    blocks=1, points=2),
        _pickup_row(1, 100, 20251015, situation='5on4', goals=1, points=1),
    ])
    result = moneypuck.buildPickupStats(df, season=2025)

    assert len(result) == 1
    row = result.iloc[0]
    assert row['gamesPlayed'] == 1
    assert row['goals'] == 1
    assert row['assists'] == 1
    assert row['points'] == 2
    assert row['shots'] == 3
    assert row['hits'] == 2
    assert row['blocks'] == 1
    assert row['powerPlayPoints'] == 1
    assert row['fantasyPoints'] == pytest.approx(7.10)
    assert row['season_ppg'] == pytest.approx(7.10)
    assert row['avgToiSeconds'] == pytest.approx(1200)


def test_build_pickup_stats_last5_window_is_last_five_by_date():
    # 7 games: season totals cover all 7, last5_* only the 5 most recent.
    # Each game: 1 goal (FP 3). Last-5 FP = 15, season FP = 21.
    rows = [_pickup_row(1, 100 + i, 20251001 + i, goals=1, points=1)
            for i in range(7)]
    result = moneypuck.buildPickupStats(pd.DataFrame(rows), season=2025)

    row = result.iloc[0]
    assert row['gamesPlayed'] == 7
    assert row['goals'] == 7
    assert row['fantasyPoints'] == pytest.approx(21)
    assert row['last5_goals'] == 5
    assert row['last5_fantasyPoints'] == pytest.approx(15)
    assert row['season_ppg'] == pytest.approx(3.0)


def test_build_pickup_stats_filters_to_requested_season():
    df = pd.DataFrame([
        _pickup_row(1, 100, 20241015, season=2024, goals=5, points=5),
        _pickup_row(1, 200, 20251015, season=2025, goals=1, points=1),
    ])
    result = moneypuck.buildPickupStats(df, season=2025)

    assert len(result) == 1
    assert result.iloc[0]['goals'] == 1
    assert result.iloc[0]['gamesPlayed'] == 1


def test_build_pickup_stats_empty_season_returns_empty_frame():
    df = pd.DataFrame([_pickup_row(1, 100, 20241015, season=2024)])
    result = moneypuck.buildPickupStats(df, season=2025)
    assert len(result) == 0


def test_build_pickup_stats_keeps_players_separate():
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015, goals=2, points=2),
        _pickup_row(2, 100, 20251015, name='Player Two', position='D',
                    hits=4, blocks=3),
    ])
    result = moneypuck.buildPickupStats(df, season=2025).set_index('playerId')

    assert result.loc[1, 'goals'] == 2
    assert result.loc[2, 'goals'] == 0
    assert result.loc[2, 'hits'] == 4
    assert result.loc[2, 'position'] == 'D'
    # FP: player 2 = 0.15*4 + 0.35*3 = 1.65
    assert result.loc[2, 'fantasyPoints'] == pytest.approx(1.65)
```

Note: `tests/test_moneypuck.py` already imports `pandas as pd`, `pytest`, and `from src import moneypuck` — check its header and only add missing imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_moneypuck.py -v -k build_pickup_stats`
Expected: 5 FAILED with `AttributeError: module 'src.moneypuck' has no attribute 'buildPickupStats'`

- [ ] **Step 3: Implement `buildPickupStats`**

Add to `src/moneypuck.py` directly after `buildPlayerSeasons` (before `loadGoalieSeasons`):

```python
def buildPickupStats(game_df, season):
    """One row per player for the pickup heuristic: season totals plus
    last-5-game totals for the given season, scored with full league weights
    (incl. hits/blocks; no plusMinus/GWG -- the accepted MoneyPuck
    approximation).

    game_df must contain ALL situation rows (loadGameLogs output) --
    moneypuckGamePoints collapses them; summing raw rows double-counts.
    The season id is a parameter so this module doesn't grow its own copy
    of the CURRENT_SEASON constant.
    """
    season_games = game_df[game_df['season'] == season]
    if season_games.empty:
        return pd.DataFrame(columns=[
            'playerId', 'name', 'position', 'gamesPlayed', 'goals',
            'assists', 'points', 'shots', 'hits', 'blocks',
            'powerPlayPoints', 'shorthandedPoints', 'fantasyPoints',
            'season_ppg', 'avgToiSeconds', 'last5_goals', 'last5_assists',
            'last5_points', 'last5_fantasyPoints'])
    games = fantasyPoints.moneypuckGamePoints(season_games)
    games = games.sort_values(['playerId', 'gameDate'])
    games['assists'] = games['I_F_primaryAssists'] + games['I_F_secondaryAssists']

    totals = games.groupby('playerId').agg(
        name=('name', lambda s: s.mode().iloc[0]),
        position=('position', lambda s: s.mode().iloc[0]),
        gamesPlayed=('gameId', 'nunique'),
        goals=('I_F_goals', 'sum'),
        assists=('assists', 'sum'),
        points=('I_F_points', 'sum'),
        shots=('I_F_shotsOnGoal', 'sum'),
        hits=('I_F_hits', 'sum'),
        blocks=('shotsBlockedByPlayer', 'sum'),
        powerPlayPoints=('powerPlayPoints', 'sum'),
        shorthandedPoints=('shorthandedPoints', 'sum'),
        fantasyPoints=('fantasyPoints', 'sum'),
        avgToiSeconds=('icetime', 'mean'),
    ).reset_index()
    totals['season_ppg'] = totals['fantasyPoints'] / totals['gamesPlayed'].replace(0, 1)

    last5 = (games.groupby('playerId').tail(5)
             .groupby('playerId').agg(
                 last5_goals=('I_F_goals', 'sum'),
                 last5_assists=('assists', 'sum'),
                 last5_points=('I_F_points', 'sum'),
                 last5_fantasyPoints=('fantasyPoints', 'sum'),
             ).reset_index())
    return totals.merge(last5, on='playerId', how='left')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_moneypuck.py -v`
Expected: the 5 new tests PASS; the one pre-existing failure (`test_load_game_logs_filters_season_and_keeps_situations`) still fails — leave it.

- [ ] **Step 5: Commit**

```powershell
git add src/moneypuck.py tests/test_moneypuck.py
git commit -m "feat: add moneypuck.buildPickupStats season + last-5 aggregation"
```

---

### Task 2: Slim `rankFreeAgents` to the MoneyPuck frame

**Files:**
- Modify: `src/features/pickups.py:24-36`
- Test: Create `tests/test_pickup_features.py`

**Interfaces:**
- Consumes: the `buildPickupStats` output frame from Task 1 (columns `playerId, name, position, gamesPlayed, season_ppg, last5_fantasyPoints, ...`), plus the identity frame from `dataProcessing.getAllPlayersWithCache()` + `flattenPlayerNames` (columns `id, full_name, positionCode, sweaterNumber, ...`).
- Produces: `rankFreeAgents(pickup_stats_df, players_df, rostered_nhle_ids) -> pd.DataFrame` sorted by `weighted_score` desc, keyed by `playerId` (the old frame's `player_id` key is gone — Tasks 3-4 merge on `playerId`). Adds `weighted_score`; fills `full_name`/`positionCode` from MoneyPuck `name`/`position` when the roster cache lacks the player.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pickup_features.py`:

```python
import pandas as pd

from src.features import pickups


def _stats_row(playerId, name='Skater Guy', position='C', gamesPlayed=10,
               season_ppg=2.0, last5_fantasyPoints=8.0):
    return {
        'playerId': playerId, 'name': name, 'position': position,
        'gamesPlayed': gamesPlayed, 'season_ppg': season_ppg,
        'last5_fantasyPoints': last5_fantasyPoints,
    }


def _players_df():
    return pd.DataFrame([
        {'id': 1, 'full_name': 'Roster Name One', 'positionCode': 'C'},
        {'id': 2, 'full_name': 'Goalie Person', 'positionCode': 'G'},
        {'id': 3, 'full_name': 'Rostered Star', 'positionCode': 'L'},
        {'id': 4, 'full_name': 'Small Sample', 'positionCode': 'D'},
    ])


def test_rank_free_agents_scores_and_sorts():
    stats = pd.DataFrame([
        _stats_row(1, season_ppg=2.0, last5_fantasyPoints=8.0),   # 0.6*2 + 0.4*8 = 4.4
        _stats_row(5, name='Cache Miss', position='D',
                   season_ppg=5.0, last5_fantasyPoints=20.0),      # 11.0, not in players_df
    ])
    result = pickups.rankFreeAgents(stats, _players_df(), rostered_nhle_ids=set())

    assert list(result['playerId']) == [5, 1]
    assert result.iloc[0]['weighted_score'] == 11.0
    assert result.iloc[1]['weighted_score'] == 4.4


def test_rank_free_agents_falls_back_to_moneypuck_identity():
    # Player 5 is missing from the roster cache: display fields fall back
    # to MoneyPuck's name/position instead of being dropped or NaN.
    stats = pd.DataFrame([_stats_row(5, name='Cache Miss', position='D')])
    result = pickups.rankFreeAgents(stats, _players_df(), rostered_nhle_ids=set())

    assert len(result) == 1
    assert result.iloc[0]['full_name'] == 'Cache Miss'
    assert result.iloc[0]['positionCode'] == 'D'


def test_rank_free_agents_filters_goalies_rostered_and_small_samples():
    stats = pd.DataFrame([
        _stats_row(1),                    # keep
        _stats_row(2, position='G'),      # goalie (via roster positionCode)
        _stats_row(3),                    # rostered
        _stats_row(4, gamesPlayed=4),     # GP < 5
    ])
    result = pickups.rankFreeAgents(stats, _players_df(), rostered_nhle_ids={3})

    assert list(result['playerId']) == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pickup_features.py -v`
Expected: FAIL (old signature: `rankFreeAgents() missing 1 required positional argument` or KeyError on the old merge keys).

- [ ] **Step 3: Rewrite `rankFreeAgents`**

Replace `rankFreeAgents` in `src/features/pickups.py` (keep the module docstring and the `build_pickup_features` stub above it untouched):

```python
def rankFreeAgents(pickup_stats_df, players_df, rostered_nhle_ids):
    """Heuristic free-agent ranking over MoneyPuck-derived pickup stats
    (moneypuck.buildPickupStats output). players_df is the NHL roster
    identity frame; players missing from it (e.g. recently moved) fall back
    to MoneyPuck's name/position instead of being dropped.
    """
    df = pd.merge(pickup_stats_df, players_df,
                  left_on='playerId', right_on='id', how='left')
    df['full_name'] = df['full_name'].fillna(df['name'])
    df['positionCode'] = df['positionCode'].fillna(df['position'])

    df['weighted_score'] = 0.6 * df['season_ppg'] + 0.4 * df['last5_fantasyPoints']

    df = df[df['positionCode'] != 'G']  # remove goalies
    df = df[~df['playerId'].isin(rostered_nhle_ids)]  # remove rostered players
    df = df[df['gamesPlayed'] >= 5]  # remove small sample size players

    return df.sort_values('weighted_score', ascending=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pickup_features.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```powershell
git add src/features/pickups.py tests/test_pickup_features.py
git commit -m "feat: rankFreeAgents consumes MoneyPuck pickup stats"
```

---

### Task 3: Wire `main.py runPickups` to MoneyPuck

**Files:**
- Modify: `main.py:79-127` (`runPickups`)

**Interfaces:**
- Consumes: `moneypuck.loadGameLogs(min_season=2020)` (cached on-disk read), `moneypuck.buildPickupStats(game_df, CURRENT_SEASON)` (Task 1), `pickups.rankFreeAgents(pickup_stats, allPlayerData, rostered_nhle_ids)` (Task 2).
- Produces: same CLI output shape as before (top-pickups + cooling tables). The `combined` frame is now keyed on `playerId` (was `player_id`).

- [ ] **Step 1: Replace the NHL stats fetch block**

In `runPickups`, replace lines 82-88 (the `# Heuristic ranker on NHL API data` block through the two `calculateSkaterPoints` applies) with:

```python
    # Identity/roster only -- the sole remaining NHL API use in this path
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)

    # Heuristic stats from MoneyPuck: full league scoring incl. hits/blocks
    # (no plusMinus/GWG -- the same accepted approximation as the ML label)
    game_df = moneypuck.loadGameLogs(min_season=2020)
    pickup_stats = moneypuck.buildPickupStats(game_df, CURRENT_SEASON)
```

The Yahoo try/except block (lines 90-102) stays exactly as-is. Then change line 104 to:

```python
    results = pickups.rankFreeAgents(pickup_stats, allPlayerData, rostered_nhle_ids)
```

- [ ] **Step 2: Fix the downstream merge key**

Replace the `combined` merge (lines 124-125):

```python
    combined = results.merge(current_players[['playerId', 'ml_score', 'pred_next5_fp']],
                             on='playerId', how='left')
```

The two print blocks at the end of `runPickups` reference only columns that still exist (`full_name`, `positionCode`, `weighted_score`, `pred_next5_fp`, `ml_score`, `final_score`, `display_name`, `cooling_*`, `gamesPlayed`) — leave them unchanged.

- [ ] **Step 3: Verify end-to-end**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe main.py pickups`
Expected:
- NO per-player fetch output (no `Status code for <id>` lines beyond the roster fetch, and none at all if `players_cache.csv` is <24h old).
- Both tables print. Off-season note: rankings are frozen at end-of-season data; top-20 should still be recognizable NHL names, similar to the pre-change list (rank shifts from the hits/blocks-vs-plusMinus/GWG swap are expected; a wholesale reshuffle is a bug).

Also run the full suite: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: no new failures beyond the 2 pre-existing ones.

- [ ] **Step 4: Commit**

```powershell
git add main.py
git commit -m "feat: runPickups sources heuristic stats from MoneyPuck"
```

---

### Task 4: Wire `api_export.py` to MoneyPuck and drop `plusMinus`

**Files:**
- Modify: `api_export.py` (`export_data`, lines 224-330 region; add one helper)

**Interfaces:**
- Consumes: `moneypuck.loadGameLogs`, `moneypuck.buildPickupStats` (Task 1), `rankFreeAgents` (Task 2).
- Produces: `frontend_data.json` pickup/cooling entries WITHOUT `plusMinus`, with `avgToi` as `"MM:SS"` derived from `avgToiSeconds`. Task 6 updates the TypeScript type to match.

- [ ] **Step 1: Add the TOI formatting helper**

Add near the top of `api_export.py` (after `get_headshot_url`):

```python
def _format_toi(seconds) -> str:
    """Mean icetime in seconds -> 'MM:SS' for display."""
    if pd.isna(seconds):
        return '0:00'
    minutes, secs = divmod(int(round(float(seconds))), 60)
    return f"{minutes}:{secs:02d}"
```

- [ ] **Step 2: Replace the NHL stats fetch in `export_data`**

Replace lines 228-241 (from `# Get all player data from NHL API` through the second `calculateSkaterPoints` apply) with:

```python
    # Identity/roster only -- the sole remaining NHL API use in this path
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)

    # Heuristic stats from MoneyPuck (full league scoring incl. hits/blocks)
    game_df = moneypuck.loadGameLogs(min_season=2020)
    pickup_stats = moneypuck.buildPickupStats(game_df, CURRENT_SEASON)
```

Change the ranker call (line 256) to:

```python
    results = pickups.rankFreeAgents(pickup_stats, allPlayerData, rostered_nhle_ids)
```

And the combined merge (lines 278-283) to:

```python
    combined = results.merge(
        current_players[['playerId', 'ml_score', 'cooling_score']],
        on='playerId',
        how='left'
    )
```

- [ ] **Step 3: Rewrite the pickup_list loop fields**

Replace the `pickup_list.append({...})` dict with (note: `plusMinus` is GONE, count stats use `int(round(...))` because MoneyPuck sums are floats):

```python
        pickup_list.append({
            'id': int(row['playerId']),
            'full_name': row['full_name'],
            'positionCode': row['positionCode'],
            'headshot': get_headshot_url(int(row['playerId'])),
            'sweaterNumber': int(row['sweaterNumber']) if not pd.isna(row.get('sweaterNumber')) else 0,
            'gamesPlayed': int(row['gamesPlayed']),
            'goals': int(round(row['goals'])),
            'assists': int(round(row['assists'])),
            'points': int(round(row['points'])),
            'powerPlayPoints': int(round(row['powerPlayPoints'])),
            'shorthandedPoints': int(round(row['shorthandedPoints'])),
            'shots': int(round(row['shots'])),
            'avgToi': _format_toi(row['avgToiSeconds']),
            'fantasyPoints': float(row['fantasyPoints']),
            'season_ppg': float(row['season_ppg']),
            'last5_goals': int(round(row['last5_goals'])),
            'last5_assists': int(round(row['last5_assists'])),
            'last5_points': int(round(row['last5_points'])),
            'last5_fantasyPoints': float(row['last5_fantasyPoints']),
            'weighted_score': float(row['weighted_score']),
            'ml_score': float(row['ml_score']),
            'final_score': float(row['final_score']),
            'cooling_score': float(row.get('cooling_score', 0)),
            'rostered': False,
        })
```

- [ ] **Step 4: Rewrite the cooling-list stats source**

Replace the `stats_merged`/`last5_merged` setup (lines 323-330) with a single lookup built from `pickup_stats` (which covers ALL current-season players, rostered included — `rankFreeAgents` filters, `buildPickupStats` doesn't):

```python
    stats_lookup = pickup_stats.merge(
        allPlayerData[['id', 'full_name', 'positionCode', 'sweaterNumber']],
        left_on='playerId', right_on='id', how='left'
    ).set_index('playerId')
```

Replace the cooling loop body:

```python
    for _, row in cooling_df.iterrows():
        player_id = int(row['playerId'])
        if player_id not in stats_lookup.index:
            continue
        ps = stats_lookup.loc[player_id]
        cooling_list.append({
            'id': player_id,
            'full_name': row.get('full_name') if not pd.isna(row.get('full_name')) else ps['name'],
            'positionCode': row.get('positionCode') if not pd.isna(row.get('positionCode')) else ps['position'],
            'headshot': get_headshot_url(player_id),
            'sweaterNumber': int(ps['sweaterNumber']) if not pd.isna(ps.get('sweaterNumber')) else 0,
            'gamesPlayed': int(row['gamesPlayed']),
            'goals': int(round(ps['goals'])),
            'assists': int(round(ps['assists'])),
            'points': int(round(ps['points'])),
            'powerPlayPoints': int(round(ps['powerPlayPoints'])),
            'shorthandedPoints': int(round(ps['shorthandedPoints'])),
            'shots': int(round(ps['shots'])),
            'avgToi': _format_toi(ps['avgToiSeconds']),
            'fantasyPoints': float(ps['fantasyPoints']),
            'season_ppg': float(ps['season_ppg']),
            'last5_goals': int(round(ps['last5_goals'])),
            'last5_assists': int(round(ps['last5_assists'])),
            'last5_points': int(round(ps['last5_points'])),
            'last5_fantasyPoints': float(ps['last5_fantasyPoints']),
            'weighted_score': 0,
            'ml_score': float(row.get('ml_score', 0)),
            'final_score': 0,
            'cooling_score': float(row['cooling_score']),
            'rostered': player_id in rostered_nhle_ids,
        })
```

- [ ] **Step 5: Remove the now-unused `fantasyPoints` import**

`api_export.py` line 12 (`from src import fantasyPoints`) has no remaining users in this file after Step 2 — delete it. Verify: `.\.venv\Scripts\python.exe -c "import api_export"` succeeds.

- [ ] **Step 6: Verify end-to-end**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe api_export.py`
Expected: export completes; then check the payload:

```powershell
.\.venv\Scripts\python.exe -c "import json; d = json.load(open('data/processed/frontend_data.json', encoding='utf-8')); p = d['pickups'][0]; assert 'plusMinus' not in p, 'plusMinus leaked'; assert ':' in p['avgToi']; print('OK', len(d['pickups']), 'pickups,', len(d['cooling']), 'cooling'); print(p['full_name'], p['fantasyPoints'], p['avgToi'])"
```

Expected: `OK 50 pickups, ...` and a sane top pickup (real name, plausible FP, TOI like `17:32`).

- [ ] **Step 7: Commit**

```powershell
git add api_export.py
git commit -m "feat: api_export sources pickup/cooling stats from MoneyPuck, drops plusMinus"
```

---

### Task 5: Delete the dead NHL stats-fetch code and `calculateSkaterPoints`

**Files:**
- Modify: `src/dataProcessing.py` (delete lines 69-155 region, selectively)
- Modify: `src/fantasyPoints.py` (delete `calculateSkaterPoints`, update header comment)
- Modify: `tests/test_fantasyPoints.py` (delete the `calculateSkaterPoints` test)
- Modify: `main.py` (remove unused `fantasyPoints` import if now unused)

**Interfaces:**
- Consumes: nothing new.
- Produces: `dataProcessing` keeps `fetchAllPlayers`, `getWithCache`, `getAllPlayersWithCache`, `flattenPlayerNames`, all birthdate + goalie-season functions. `fantasyPoints` keeps `SKATER_WEIGHTS`, `GOALIE_WEIGHTS`, `calculateGoaliePoints`, `moneypuckGamePoints`.

- [ ] **Step 1: Delete from `src/dataProcessing.py`**

Delete these functions (and nothing else): `extractCurrentStats`, `parseToi`, `extractLast5Stats`, `makeAllStatsDataFrame`, `getAllStatsWithCache`, `makeAllLast5DataFrame`, `getAllLast5WithCache`.

**KEEP** `fetchAllPlayers` (used by `makeAllBirthDatesDataFrame` at line 160-161) and `getWithCache` (used by `getAllPlayersWithCache`).

- [ ] **Step 2: Delete `calculateSkaterPoints` and update the scoring header**

In `src/fantasyPoints.py`: delete the `calculateSkaterPoints` function (lines 17-26). Replace the header comment (lines 1-3) with:

```python
# League scoring weights for skaters — the single source of truth.
# plusMinus and GWG stay listed for completeness but MoneyPuck data doesn't
# carry them, so moneypuckGamePoints (the only skater scoring path) omits
# them — a documented ~5% approximation.
```

In `tests/test_fantasyPoints.py`: delete `test_calculate_skater_points_full_league_scoring` (lines 7-19).

- [ ] **Step 3: Remove dangling imports and references**

Run: `.\.venv\Scripts\python.exe -m pyflakes main.py api_export.py src/dataProcessing.py src/fantasyPoints.py` — or if pyflakes isn't installed, grep:

```powershell
Select-String -Path main.py,api_export.py -Pattern "calculateSkaterPoints|getAllStatsWithCache|getAllLast5WithCache"
```

Expected: no matches. In `main.py`, check whether `from src import fantasyPoints` (line 10) still has users in the file; if not, delete the import line.

- [ ] **Step 4: Delete the orphaned cache files (local, untracked)**

```powershell
Remove-Item data/raw/stats_current.csv, data/raw/stats_last5.csv -ErrorAction SilentlyContinue -Confirm:$false
```

- [ ] **Step 5: Run the full suite and both entry points**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: no new failures beyond the 2 pre-existing ones; count drops by 1 (deleted skater-points test).

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe main.py pickups`
Expected: works as in Task 3 Step 3.

- [ ] **Step 6: Commit**

```powershell
git add src/dataProcessing.py src/fantasyPoints.py tests/test_fantasyPoints.py main.py
git commit -m "refactor: delete dead NHL per-player stats fetch and calculateSkaterPoints"
```

---

### Task 6: Remove `+/-` from the frontend

**Files:**
- Modify: `frontend/src/types/player.ts:15`
- Modify: `frontend/src/components/rink/RinkTable.tsx:46-53`

**Interfaces:**
- Consumes: the `plusMinus`-free export from Task 4.
- Produces: `Player` type without `plusMinus`; RinkTable without the `+/-` column.

- [ ] **Step 1: Remove `plusMinus` from the Player type**

In `frontend/src/types/player.ts`, delete line 15 (`  plusMinus: number;`).

- [ ] **Step 2: Remove the `+/-` column from RinkTable**

In `frontend/src/components/rink/RinkTable.tsx`, delete the whole column object at lines 46-53:

```tsx
    {
      key: 'plusMinus',
      label: '+/−',
      title: 'Plus-minus',
      numeric: true,
      sortValue: (p) => p.plusMinus,
      render: (p) => (p.plusMinus > 0 ? `+${p.plusMinus}` : p.plusMinus),
    },
```

- [ ] **Step 3: Verify no other references and the build passes**

```powershell
Select-String -Path frontend/src -Pattern "plusMinus" -Recurse
```
Expected: no matches.

Run: `cd frontend; npm run build`
Expected: Next.js build succeeds with no TypeScript errors. (If `node_modules` is missing, `npm install` first.)

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/types/player.ts frontend/src/components/rink/RinkTable.tsx
git commit -m "feat: drop plus-minus column (no longer in the data source)"
```

---

### Task 7: Update docs and skills

**Files:**
- Modify: `CLAUDE.md` (known-issues + architecture sketch)
- Modify: `.claude/skills/fht-architecture-contract/SKILL.md` (system map, weak-points table)
- Modify: `.claude/skills/fht-operations/SKILL.md` (cache catalog — remove `stats_current.csv`/`stats_last5.csv` rows if listed)

**Interfaces:** none — docs only.

- [ ] **Step 1: Update `CLAUDE.md`**

- In "Known issues", shrink the UnicodeEncodeError entry: the per-player fetch is gone; only the ~32-request roster-cache rebuild can still print non-ASCII previews, so keep the `$env:PYTHONUTF8='1'` workaround note but drop the "700+" framing.
- In "Architecture at a glance", the NHL API line already says "identity/birthDate/roster only" — now accurate; no change needed unless it mentions stats.
- If the pickups quick-start text mentions NHL API stats fetching, align it.

- [ ] **Step 2: Update `fht-architecture-contract`**

- Weak-points table: delete the "NHL-API scoring path omits hits/blocks … two scales" row (resolved: the heuristic and ML score now share the MoneyPuck scoring path).
- Invariants: update "Two scoring paths exist" under "Scoring weights come from one place" — there is now ONE skater scoring path (`moneypuckGamePoints`); `calculateSkaterPoints` is deleted.
- System map: note `buildPickupStats` in the `src/moneypuck.py` line.
- Load-bearing decisions table: the MoneyPuck-single-source row's rationale ("removes … the 700-request threaded stats fetch") is now realized — update tense.

- [ ] **Step 3: Update `fht-operations`**

Search for `stats_current.csv` / `stats_last5.csv` in the cache catalog and remove those rows; note that the pickup path's only NHL API cache is now `players_cache.csv` (24h).

- [ ] **Step 4: Commit**

```powershell
git add CLAUDE.md .claude/skills/fht-architecture-contract .claude/skills/fht-operations
git commit -m "docs: reflect MoneyPuck-only pickup pipeline in CLAUDE.md and skills"
```

---

## Final verification (after all tasks)

- [ ] `.\.venv\Scripts\python.exe -m pytest -v` — no new failures vs the 2-failure baseline.
- [ ] Cold-cache request check: delete `data/raw/players_cache.csv`, run `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe main.py pickups`, and confirm the only NHL API traffic is the ~32 roster fetches (one `Fetching data for team:` line per team, no `Status code for <player_id>` lines).
- [ ] Before/after comparison: the top-20 pickup list should be recognizably similar to the pre-change list (same tier of players; modest rank shifts from the scoring swap are expected — blocks-heavy defensemen up slightly, plus-minus merchants down slightly).
- [ ] `frontend_data.json` has no `plusMinus` key anywhere: `Select-String -Path data/processed/frontend_data.json -Pattern "plusMinus"` → no matches.
