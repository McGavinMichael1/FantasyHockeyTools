# Data Flow Analysis for `python main.py pickups`

## Summary
✅ **GOOD NEWS**: API calls are properly cached. No redundant network requests.
⚠️ **INEFFICIENCY**: MoneyPuck data processing happens every run (not cached).

## Detailed Data Flow

### 1. NHL API Data (via dataProcessing.py)
**Location**: Lines 47-52 in main.py

```python
allPlayerData = dataProcessing.getAllPlayersWithCache()      # ~900 players
stats_df = dataProcessing.getAllStatsWithCache(allPlayerData['id'])  # ~900 API calls
last5_df = dataProcessing.getAllLast5WithCache(allPlayerData['id'])  # ~900 API calls
```

**Caching**: ✅ 24-hour cache
- `data/raw/players_cache.csv` - All NHL roster data
- `data/raw/stats_current.csv` - Current season stats
- `data/raw/stats_last5.csv` - Last 5 games stats

**Result**: After first run, no API calls for 24 hours (unless cache deleted)

---

### 2. MoneyPuck Data (via mlFeatures.py)
**Location**: Line 61 in main.py → `latestGameState()` → `loadMoneyPuckData()`

```python
def latestGameState():
    df = mlFeatures.loadMoneyPuckData()  # <-- Loads & processes 2020-2025 data
    df = mlFeatures.buildRollingFeatures(df)  # <-- Computes rolling stats
    # ... filters to current season players with 20+ GP
```

**Caching**:
- ✅ Raw CSV files cached: `data/processed/moneypuck_games_2020.csv`
- ❌ Processed features NOT cached - recomputed every run

**What happens every `pickups` run**:
1. Load cached CSV (~5 seasons of game logs)
2. Process through `fantasyPoints.moneypuckGamePoints()` - collapses situation rows
3. Compute rolling features (5/10/20 game windows) for all players
4. Filter to current season

**Processing time**: Depends on data size, but could be 5-30 seconds

---

### 3. Yahoo Fantasy API (via yahooAPI.py)
**Location**: Lines 54-56 in main.py

```python
lg = yahooAPI.getLeague()
rostered_names = yahooAPI.getRosteredIds(lg)
rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)
```

**Caching**: ❌ No cache - fetches every run
**Impact**: Minimal - just roster info (~200 players across ~10 teams)

---

## Is Data Pulled Multiple Times Per Run?

### NHL API: NO ✅
- Each dataset cached separately
- Cache checked before making API calls
- Only fetches if cache older than 24 hours

### MoneyPuck: NO (for raw data) ✅
- Raw CSV files cached until you download fresh data
- But **processed features recomputed every run** ⚠️

### Yahoo API: YES (but minimal) ⚠️
- No caching, but only ~3 API calls per run
- Fast API, not a bottleneck

---

## Optimization Opportunities

### High Impact
**Cache processed MoneyPuck features**

Current inefficiency at [main.py:32-40](main.py#L32-L40):
```python
def latestGameState():
    df = mlFeatures.loadMoneyPuckData()  # Loads full dataset
    df = mlFeatures.buildRollingFeatures(df)  # Expensive computation
    current_df = df[df['season'] == CURRENT_SEASON].copy()
    # ... aggregate to player level
```

**Solution**: Cache the final `current_players` dataframe
- Similar to how NHL data is cached (24 hour expiry)
- Would skip all MoneyPuck processing on subsequent runs
- Cache file: `data/processed/current_players_features.csv`

### Medium Impact
**Cache Yahoo roster data**
- 1-hour cache for roster info
- Minimal gain, but reduces API dependency

---

## Current Behavior Summary

When you run `python main.py pickups`:

| Data Source | First Run | Subsequent Runs (< 24h) |
|-------------|-----------|-------------------------|
| NHL Rosters | API call  | Cached ✅ |
| NHL Stats   | ~900 API calls | Cached ✅ |
| NHL Last 5  | ~900 API calls | Cached ✅ |
| MoneyPuck Raw | Loads CSV | Loads cached CSV ✅ |
| MoneyPuck Processing | Computes features | **Recomputes features** ⚠️ |
| Yahoo Roster | API call | **API call** ⚠️ |

**Total time**:
- First run: 5-10 minutes (NHL API rate limiting)
- Subsequent runs: 10-60 seconds (MoneyPuck processing dominates)

With optimization: 1-2 seconds for cached runs
