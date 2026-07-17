# MoneyPuck-only pickup stats — design

**Date:** 2026-07-17
**Status:** Approved by owner (this session)
**Goal:** Eliminate the ~1400 per-player NHL API landing requests in the pickup
pipeline by sourcing the heuristic ranker's stats from MoneyPuck game logs.
This finishes the settled architecture decision ("MoneyPuck is the single stats
source for modeling") whose stated rationale already included removing the
700-request threaded stats fetch.

Queued sibling projects from the same brainstorm (separate specs, not covered
here): schedule-aware tools (strength of schedule from MoneyPuck team-level
data + backup-goalie weekly streamer, sharing a team-schedule helper), and a
promptable LLM keeper assistant.

## Scope decisions (owner-confirmed)

- **Kill the per-player fetches only.** The 24h-cached ~32-request team-roster
  fetch (`dataProcessing.getAllPlayersWithCache`) stays: it supplies identity —
  canonical `full_name` for Yahoo fuzzy matching, `positionCode`,
  `sweaterNumber`, and players with 0 GP.
- **Drop the +/- column** from the frontend rather than approximating it from
  MoneyPuck on-ice goal columns.
- **Approach:** new aggregation function in `src/moneypuck.py` (the "all
  MoneyPuck IO" module), not a bent `buildPlayerSeasons` and not removing the
  heuristic ranker.
- **ML training path is untouched.** `train-pickups`, `mlFeatures`
  (xGoals, gameScore, Corsi/Fenwick, high-danger, icetime rolling features),
  and the label are exactly as before. Only the heuristic ranker's input
  source changes.

## Data flow

Before:

```
runPickups / export_data
  -> getAllPlayersWithCache()            (32 roster requests, 24h cache)
  -> getAllStatsWithCache(ids)           (~700 landing requests)
  -> getAllLast5WithCache(ids)           (~700 landing requests)
  -> calculateSkaterPoints (no hits/blocks)
  -> rankFreeAgents -> 0.3 heuristic + 0.7 ML blend
```

After:

```
runPickups / export_data
  -> getAllPlayersWithCache()            (32 roster requests, 24h cache — only NHL API use left)
  -> mlFeatures.loadMoneyPuckData()      (reads the existing on-disk game-log cache)
  -> moneypuck.buildPickupStats(game_df, season)
  -> rankFreeAgents -> same 0.3/0.7 blend
```

## New function: `moneypuck.buildPickupStats(game_df, season)`

Input: full-situation game logs (output of `loadGameLogs` /
`mlFeatures.loadMoneyPuckData` — ALL situation rows, per the double-counting
invariant). `season` is passed in by the caller; `moneypuck.py` does not grow
its own copy of the `CURRENT_SEASON` constant.

Behavior: filter to `season`, run `fantasyPoints.moneypuckGamePoints` (collapses
situation rows, derives PPP/SHP, scores with full `SKATER_WEIGHTS` incl.
hits/blocks), then aggregate to one row per `playerId`:

- **Season totals:** `gamesPlayed`, `goals`, `assists`, `points`,
  `shotsOnGoal`, `hits`, `blocks`, `powerPlayPoints`, `shorthandedPoints`,
  `totalFP`, `season_ppg` (= totalFP / gamesPlayed), `avgToiSeconds`
  (mean icetime; formatted to "MM:SS" at export time only).
- **Last-5 totals** (last 5 game rows per player by `gameDate`):
  `last5_goals`, `last5_assists`, `last5_points`, `last5_FP`.
- Carry `name` and `position` from MoneyPuck for fallback display/filtering.

## Consumer changes

- **`src/features/pickups.py::rankFreeAgents`** — new signature: one
  `buildPickupStats` frame + identity frame (`players_cache`) + rostered id
  set. Same formula (`0.6 * season_ppg + 0.4 * last5_FP`), same filters
  (GP >= 5, non-goalie, non-rostered). The heuristic score now uses the same
  scoring approximation as the ML label, closing the documented
  "two scales" weak point.
- **`main.py::runPickups` and `api_export.py::export_data`** — drop the
  `getAllStatsWithCache`/`getAllLast5WithCache` calls and the
  `calculateSkaterPoints` applies; feed `buildPickupStats` output through the
  ranker and export. Callers load the game logs via `loadGameLogs(min_season=2020)`,
  which serves its own on-disk cache — a local file read, never network. (No
  frame-sharing plumbing with `latestGameState`: at worst the cached CSV is
  read twice per run, which is seconds and matches pre-existing behavior.)
- **Frontend export fields** — same field names where possible so the frontend
  contract changes stay minimal: `goals`, `assists`, `points`, `shots`,
  `powerPlayPoints`, `shorthandedPoints`, `avgToi` ("MM:SS" from
  `avgToiSeconds`), `fantasyPoints`, `season_ppg`, `last5_*`. **Removed:**
  `plusMinus` — from the export dicts, `frontend/src/types/player.ts`, and the
  `RinkTable` +/- column. `sweaterNumber` stays (roster cache). GWG was never
  exported/displayed.

## Deletions (dead after this change)

From `src/dataProcessing.py`: `getAllStatsWithCache`, `getAllLast5WithCache`,
`extractCurrentStats`, `extractLast5Stats`, `makeAllStatsDataFrame`,
`makeAllLast5DataFrame`, `parseToi`. **`fetchAllPlayers` stays** — grep shows
`makeAllBirthDatesDataFrame` (the birthdate cache builder) still uses it; only
the goalie season builder has its own worker loop. Cache files
`data/raw/stats_current.csv` / `stats_last5.csv` are no longer written (delete
locally; they were never committed).

From `src/fantasyPoints.py`: `calculateSkaterPoints` and its unit test —
grep-verified its only consumers are the deleted paths. `SKATER_WEIGHTS` is
untouched and remains the single scoring source of truth (used by
`moneypuckGamePoints`). Update the header comment that says "GWG and plusMinus
are only available from the NHL API path" to reflect that the NHL API skater
scoring path no longer exists.

## Accepted behavior changes

1. **Heuristic scoring swap:** loses plusMinus (0.5/unit) and GWG (1/unit),
   gains hits (0.15) and blocks (0.35). This is the same documented ~5%
   approximation the ML label has always used. Rank shifts in the heuristic
   component are expected and intended (blocks-heavy defensemen score a bit
   higher, sheltered plus-minus merchants a bit lower).
2. **Freshness now rides entirely on the manual `moneypuck_current.csv`
   download.** The NHL fetch used to provide same-day season totals even with
   a stale MoneyPuck file. The ML score (70% of the blend) already had this
   dependency, and `checkCurrentFreshness` warns after 3 days. Accepted.
3. **+/- display column removed** from the frontend pickup/cooling tables.

## Error handling

- `buildPickupStats` on an empty/missing current season (e.g. off-season with
  an old file) returns an empty frame; callers keep their existing
  empty-result behavior. No new failure modes: the MoneyPuck files are already
  hard prerequisites for the ML path in the same commands.
- Yahoo roster filtering keeps its existing try/except-and-continue behavior.

## Testing

- **Unit:** `buildPickupStats` on a small synthetic full-situation fixture —
  asserts no situation double-counting (totals match the 'all' rows), correct
  last-5 windowing by date (player with >5 and <5 games), PPP/SHP derivation,
  and `season_ppg` math.
- **Update:** remove/replace tests referencing deleted `dataProcessing`
  functions and `calculateSkaterPoints`.
- **End-to-end gate:** run `main.py pickups` and `api_export.py` before and
  after on the same cached data. Top-20 lists should be recognizably similar —
  rank shifts from the scoring swap are expected; a wholesale reshuffle means
  a bug (likely a join or double-count). Verify no per-player NHL requests
  fire when the roster cache is warm, and that `frontend_data.json` validates
  against the updated `player.ts` type (no `plusMinus`).

## Docs to touch

- `CLAUDE.md` known-issues note about the 700-request UnicodeEncodeError
  workaround (the per-player fetch that triggered it is gone; the roster fetch
  can still print non-ASCII previews, so the `PYTHONUTF8` note shrinks but
  does not disappear).
- `.claude/skills/fht-architecture-contract` system map + weak-points table
  (two-scales row) and `fht-operations` cache catalog (removed caches).
