# Fantasy Hockey Add/Drop Analyzer - Project Plan

## Project Overview
**Goal:** Build an ML-powered tool to analyze fantasy hockey free agents and help make add/drop decisions based on projected future value for your specific league's scoring system.

**Key Principle:** Real hockey performance ≠ Fantasy hockey value for your league

**Two Use Cases:**
- **Pickups (in-season):** Find the best available free agents to add to your roster
- **Draft:** Identify keeper candidates and rank players for the draft

**Your Learning Goals:**
- Practice Python project structure and organization
- Work with real-world APIs and messy data
- Apply ML concepts from coursework to a practical problem
- Debug dimensional consistency issues hands-on
- Build something end-to-end from scratch

---

## Project Flow (High-Level)

```
START
  ↓
[1. Data Collection] ← Fetch NHL stats via API
  ↓
[2. Fantasy Point Calculation] ← Apply your league's scoring rules
  ↓
[3. Data Storage & Management] ← Save historical data for training
  ↓
[4. Feature Engineering] ← Create meaningful predictors
  ↓
[5. Model Building] ← Train ML models for predictions
  ↓
[6. Prediction & Recommendations] ← Generate add/drop suggestions
  ↓
[7. UI/Output] ← Display results in usable format
  ↓
END
```

---

## Phase Breakdown

### Phase 0: Project Setup & Planning
**Status:** [x] Complete

**Decisions Made:**
- Virtual environment: `.venv/` inside project root
- Version control: git, hosted on GitHub
- `.gitignore` covers: `.venv/`, `data/**/*.csv`, `__pycache__/`, `.vscode/`, `.DS_Store`
- CSV data files are NOT committed — they are generated artifacts
- `data/raw/` and `data/processed/` folders tracked via `.gitkeep` files
- Module structure:
  - `src/nhlAPI.py` — all HTTP calls to NHLE API
  - `src/dataProcessing.py` — DataFrame logic, caching
  - `main.py` — orchestration / entry point

---

### Phase 1: Data Collection (API Integration)
**Status:** [ ] In Progress

**Objective:** Fetch all active NHL player identities and stats from the NHLE API

#### 1a — Player Roster (Identity Data)
**Status:** [x] Complete

- Fetch all 32 team rosters via `/v1/roster/{teamAbbrev}/current`
- Combine into one DataFrame (forwards + defensemen + goalies per team)
- Cache to `data/raw/players_cache.csv` (24-hour TTL)
- `getAllPlayersWithCache()` in `dataProcessing.py` is the entry point
- `id` column is the primary key linking all other data

**Known issue:** `firstName` and `lastName` columns contain nested dicts like `{'default': 'Ross'}` — needs flattening before use downstream

#### 1b — Current Season Stats
**Status:** [ ] Not Started — **START HERE**

**Objective:** Fetch per-player current season totals for all active players

**Why not the bulk endpoint?**
- `/v1/skater-stats-leaders/current` only returns top performers — these are almost always rostered in your league already
- Need stats for ALL players so availability filtering can happen locally
- Avoids complex cross-referencing to fill in missing mid-tier players

**Implementation plan:**
1. Explore `/v1/player/{id}/landing` in browser for one player — map the exact field names for stats you want
2. Add `getPlayerStats(player_id)` to `nhlAPI.py` — mirrors `getRosterData` pattern (handle 429, return raw JSON)
3. Add `extractCurrentStats(json, player_id)` to `dataProcessing.py` — returns a flat dict for one player
4. Add `makeAllStatsDataFrame(player_ids)` to `dataProcessing.py` — uses `ThreadPoolExecutor` to fetch in parallel
   - `max_workers=10` to start; tune based on 429 frequency
   - Each worker wraps its call in try/except so one failure doesn't crash the run
   - Input: list of player ids from `players_cache.csv`
5. Add `getAllStatsWithCache(player_ids, cache_file='data/raw/stats_current.csv')` — same 24-hour TTL cache pattern as `getAllPlayersWithCache`
6. Wire up in `main.py`

#### 1c — Historical Season Totals (Career Stats)
**Status:** [ ] Not Started

- Same `/v1/player/{id}/landing` endpoint — `seasonTotals` array
- Multiple rows per player (one per past season)
- Cache to `data/raw/stats_historical.csv`
- Relevant for: draft context, career trajectory, consistency analysis

#### 1d — Last 5 Games
**Status:** [ ] Not Started

- Same `/v1/player/{id}/landing` endpoint — recent game log section
- 5 rows per player (individual game stats)
- Cache to `data/raw/stats_last5.csv`
- Relevant for: pickup decisions — recent form is a strong short-term predictor
- Will be aggregated into rolling window features during Phase 4

**Key Technical Challenges:**
- Rate limiting: 429 responses — handled with retry loop + sleep in `getRosterData`, replicate in `getPlayerStats`
- Nested JSON: API returns dicts inside fields (e.g. `{'default': 'Ross'}`) — flatten in extract helpers
- Threading: `concurrent.futures.ThreadPoolExecutor` — `executor.map(fn, player_ids)`

---

### Phase 2: Fantasy Points Calculation
**Status:** [ ] Not Started

**Objective:** Convert real NHL stats into fantasy points based on YOUR league's scoring system

**Tasks:**
- [ ] Document your league's scoring rules clearly
- [ ] Write a function to calculate fantasy points from player stats
- [ ] Validate calculations against your actual league results
- [ ] Handle edge cases (missing stats, games played, etc.)

**Key Technical Challenges:**
- How do you map API stat names to your league's categories?
- How do you handle per-game vs. total stats?
- What about players who change teams mid-season?

**Critical Thinking:**
1. What stats does your league count? (Goals, assists, PPP, SOG, hits, blocks, etc.)
2. What's the point value for each stat category?
3. Are there position-specific scoring differences?
4. Do you need to account for games played?
5. Should you calculate total points or points-per-game?

**Your League Scoring Rules:**

Forwards & Defensemen:
| Stat | Value |
|---|---|
| Goals (G) | 3 |
| Assists (A) | 2 |
| Plus/Minus (+/-) | 0.5 |
| Powerplay Points (PPP) | 1 |
| Shorthanded Points (SHP) | 1 |
| Game-Winning Goals (GWG) | 1 |
| Shots on Goal (SOG) | 0.15 |
| Hits (HIT) | 0.15 |
| Blocks (BLK) | 0.35 |

Goaltenders:
| Stat | Value |
|---|---|
| Games Started (GS) | 0.75 |
| Wins (W) | 2.5 |
| Losses (L) | -1 |
| Goals Against (GA) | -0.5 |
| Saves (SV) | 0.15 |
| Shutouts (SHO) | 3 |

Roster Positions: C, C, LW, LW, RW, RW, D, D, D, D, Util, G, G, BN, BN, BN, BN, BN, IR+, IR+

---

### Phase 3: Data Storage & Historical Tracking
**Status:** [ ] In Progress

**Decisions Made:**
- Format: CSV (works natively with pandas DataFrames)
- Raw data lives in `data/raw/`, processed/ML-ready data in `data/processed/`
- Files are NOT committed to git — generated on demand via cache functions
- Each raw dataset has its own cache file and 24-hour TTL

**Raw data file map:**
| File | Contents | Shape |
|---|---|---|
| `data/raw/players_cache.csv` | Identity/bio for all active players | 1 row per player |
| `data/raw/stats_current.csv` | Current season totals | 1 row per player |
| `data/raw/stats_historical.csv` | Career season-by-season totals | N rows per player |
| `data/raw/stats_last5.csv` | Last 5 individual game stats | 5 rows per player |
| `data/processed/features.csv` | Flattened ML-ready feature matrix | 1 row per player |

**Cache pattern (used consistently across all fetch functions):**
```
if file exists and age < 24 hours:
    return pd.read_csv(cache_file)
else:
    fetch fresh data
    df.to_csv(cache_file, index=False)
    return df
```

**Player availability — NOT stored in data files:**
- Pickup context: unavailable = already on someone's league roster
- Draft context: unavailable = one of the 4 kept players
- Filtering happens in a separate function, not at collection time

---

### Phase 4: Feature Engineering
**Status:** [ ] Not Started

**Objective:** Combine raw data files into one ML-ready feature matrix (`data/processed/features.csv`) — one row per player

**This is where ML gets interesting - and where you'll learn the most!**

**Input files → output:**
- `stats_current.csv` → season total features (goals, assists, ice time, etc.)
- `stats_historical.csv` → career average features, consistency metrics, year-over-year trends
- `stats_last5.csv` → rolling window features (sum, average, trend over last 5 games)

**Feature Ideas to Explore:**
- [ ] Points per game (current season)
- [ ] Goals/assists in last 5 games (sum and trend)
- [ ] Shooting percentage trends
- [ ] Ice time trends (are they getting more/less ice?)
- [ ] Power play opportunity changes
- [ ] Career average points per game
- [ ] Season-over-season improvement rate

**Matrix Dimension Practice:**
- If you have N players and M features, what shape is your feature matrix?
- How do you handle players with different numbers of games played?
- What do you do with missing values (rookies with no career history)?

---

### Phase 5: Model Building & Training
**Status:** [ ] Not Started

**Objective:** Train ML models to predict player fantasy value

**Model Progression (Start Simple!):**
1. Baseline: Use recent average (no ML)
2. Linear Regression: Simple, interpretable
3. Random Forest: Handles non-linearity
4. Gradient Boosting: Often best performance
5. Neural Network: Practice from your course (if you want)

**What are you predicting?**
- Next week's fantasy points?
- Rest of season total points?
- Probability of being a top performer?

**Evaluation Questions:**
1. How do you measure success? (MAE, RMSE, R²?)
2. Are you more concerned with ranking players correctly or exact point predictions?
3. How do you prevent overfitting to past performance?

---

### Phase 1e: Yahoo Fantasy API Integration
**Status:** [ ] Not Started — tackle before ranker

**Objective:** Automatically fetch which players are rostered in your league so the ranker only surfaces genuinely available players

**Why Yahoo and not manual:**
- Rosters change daily (injuries, adds/drops) — a static list is stale within hours
- 10 teams × 15 players = ~150 IDs to maintain manually
- Yahoo has the authoritative source of truth for your league

**Key libraries:**
- `yahoo_fantasy_api` — Python wrapper for Yahoo Fantasy Sports API
- `yahoo_oauth` — handles the OAuth 2.0 token flow

Install both:
```
pip install yahoo_fantasy_api yahoo_oauth
```

**OAuth setup (one-time):**
1. Go to Yahoo Developer Network and create an app
2. Set app type to "Installed" and scope to Fantasy Sports read
3. Download/save your `client_id` and `client_secret`
4. On first run, `yahoo_oauth` opens a browser for login and saves a token file locally
5. Subsequent runs refresh the token automatically — no re-login needed

**What to fetch:**
- All rostered player names/IDs across all teams in your league
- Optionally: your own team's roster separately (for drop candidates)

**Implementation plan:**
1. Add `yahoo_fantasy_api` and `yahoo_oauth` to `requirements.txt`
2. Create `src/yahooAPI.py` — mirrors the pattern of `nhlAPI.py`
3. Write `getRosteredPlayerIds(league)` — returns a set of player IDs currently rostered
4. Write `getMyRoster(league)` — returns your team's roster specifically
5. Cache the result to `data/raw/rostered_players.json` with a short TTL (1-2 hours since rosters change daily)
6. Wire into the ranker as the availability filter

**Key challenge — ID mapping:**
Yahoo uses its own player IDs, not the NHLE IDs you've been using. You'll need to match players by name between the two systems. The `players_cache.csv` has NHLE IDs and names — match on `firstName + lastName` to find the corresponding NHLE ID for each rostered player.

**Credentials storage:**
- Store `client_id` and `client_secret` in a `.env` file — never commit this
- `.env` is already in your `.gitignore`
- Use the `python-dotenv` library to load them

---

### Phase 6: Prediction & Recommendation System
**Status:** [ ] Not Started

**Objective:** Use trained model to generate actionable add/drop recommendations

**Tasks:**
- [ ] Fetch current free agent list via Yahoo API
- [ ] Generate predictions for all available players
- [ ] Rank players by projected value
- [ ] Compare to your current roster
- [ ] Generate add/drop recommendations

**Availability filtering logic (to implement here):**
```
getAvailablePlayers(all_stats_df, rostered_ids)
  → filters out players already rostered in your league via Yahoo API
  → returns ranked list of pickupable players
```

---

### Phase 7: User Interface
**Status:** [ ] Not Started

**Options (Pick One to Start):**
- **Option A: Command Line** — `python main.py`, outputs to terminal (simplest)
- **Option B: Streamlit Web App** — runs on localhost, visual interface, good for data projects

**Recommended:** Start with A, upgrade to B if you want it prettier

---

## Project Milestones & Checkpoints

### Milestone 1: Data Pipeline Working
**Definition of Done:**
- [x] Can fetch active player roster from all 32 teams
- [x] Caching implemented for roster data
- [ ] Can fetch current season stats for all players (threaded)
- [ ] Can fetch last 5 game stats for all players
- [ ] All raw data saving to `data/raw/` correctly

### Milestone 2: Basic ML Model
**Definition of Done:**
- Feature engineering implemented
- At least one model trained
- Can generate predictions
- Have evaluated performance

### Milestone 3: MVP Complete
**Definition of Done:**
- Can input current free agents
- Generates ranked recommendations
- Usable interface (even if basic)
- Actually helps you make decisions!

### Milestone 4: Refinement
**Definition of Done:**
- Multiple models compared
- Better features added
- UI polished
- Deployed for regular use

---

## Technical Debt & Future Enhancements

**Known issues to revisit:**
- [ ] `firstName`/`lastName` columns in `players_cache.csv` are nested dicts — flatten in `makeTeamDataframe` or during feature engineering
- [ ] `players_cache.csv` default path should be `data/raw/players_cache.csv` (currently `data/players_cache.csv`)
- [ ] Debug print statements in `getRosterData` and `makeAllPlayersDataFrame` should be removed or converted to proper logging

**Ideas for V2.0:**
- Trade analyzer
- Lineup optimizer
- Injury impact predictor
- Schedule difficulty analysis
- Keeper value calculator

---

### Prospect & Callup Tracker
**Concept:** Monitor AHL/minor league callups and newly activated players who have fewer than 5 games played in the NHL this season, so you can act on them before they accumulate enough games to appear in the main ranker.

**Why it's valuable:**
- Top prospects (e.g. a first-round pick getting their first NHL callup) are often the best pickups of the season but disappear from the waiver wire within 24-48 hours
- The main ranker filters out players with < 5 games to avoid small sample flukes — but this means genuine callups are invisible until they've played a week
- Early information = competitive edge in a 10-team league

**What to track:**
- Players in `players_cache` with `gamesPlayed < 5` in `stats_current` — these are your callup candidates
- Cross-reference with AHL roster moves (would need an external source)
- Flag players who had 0 games last week and > 0 this week — newly activated

**Implementation approach (when ready):**
1. Add a separate "callup watch list" output alongside the main ranker
2. Sort by `weighted_score` but label clearly as small sample size
3. Optionally pull from an injury/transaction feed to flag the reason for callup

---

### Power Play Opportunity Analyzer
**Concept:** Identify players whose power play role is increasing — either rising specialists or players stepping into a bigger PP role due to injury/lineup changes.

**Why it's valuable:**
- PP specialists are high-value pickups because PPP is worth 1 point in your league and PP opportunities compound (a player on PP1 touches the puck far more)
- When a team's primary PP quarterback (usually a D-man) or PP1 forward gets hurt, someone else steps up — identifying that player early is a big edge
- These opportunities are often invisible in season totals until a few weeks have passed

**What to track:**
- `powerPlayPoints` from `stats_current` → season PP rate (PPP per game)
- `powerPlayGoals` from `last5Games` → recent PP activity (proxy for PP ice time)
- Delta between recent PP rate and season PP rate → rising or falling PP role

**Signal to look for:**
- Player whose last5 PP rate is significantly higher than their season PP rate → stepped into a bigger role recently
- Player on a team where a known PP specialist recently got injured → opportunity alert

**Data needed:**
- Current injury reports (not yet collected — would need a new endpoint or external source)
- Team PP unit composition (not directly available from NHLE API — may need to infer from PP ice time)
- `powerPlayPoints` per game over time (would require game log history, not just last 5)

**Implementation approach (when ready):**
1. Calculate `season_ppp_per_game = powerPlayPoints / gamesPlayed` from `stats_current`
2. Calculate `recent_pp_activity` from `last5Games` using `powerPlayGoals` as proxy
3. Flag players where recent PP rate > 1.5x their season rate as "rising PP role"
4. Cross-reference with team — if multiple players on same team are flagged, one may have taken over from an injured teammate
5. Surface these in the pickup recommender as a separate "PP opportunity" alert

**Known limitations:**
- `powerPlayGoals` is a weaker proxy than `powerPlayPoints` (misses PP assists) — accuracy improves if full PPP per game becomes available
- Injury data requires an additional data source not yet integrated

---

## Learning Log

### March 2026
**What I learned:**
- Separation of concerns: keep API calls (`nhlAPI.py`), data processing (`dataProcessing.py`), and orchestration (`main.py`) in separate modules
- The NHLE stats endpoint does NOT indicate whether a player is currently active — must cross-reference with roster data from all 32 teams
- Claude Code (VS Code) and Claude.ai Projects do NOT share session history — use `PROJECT-PLAN.md` as the shared memory layer, referenced with `@PROJECT-PLAN.md` in Claude Code
- `.gitignore` must match the exact folder name — `.venv/` and `venv/` are different entries
- CSV data files should not be committed — use `.gitkeep` to track empty folders instead
- `to_csv()` returns nothing useful — save as a side effect, then return the DataFrame separately
- Variable name shadowing: naming a variable `time` when `import time` is at the top causes `UnboundLocalError`
- `os.path.getmtime()` returns a past timestamp — subtract from `time.time()` (not the other way around) to get age
- HTTP 429 = rate limited — check `response.status_code` before calling `.json()`, retry with longer sleep
- Raw data and ML features have different natural shapes — store them separately, combine during feature engineering
- `ThreadPoolExecutor` + `executor.map()` replaces sequential `for` loops for parallel API calls

**Challenges faced:**
- Stats endpoint alone insufficient to determine active player status
- 429 rate limiting when fetching 32 team rosters sequentially too fast
- Nested JSON fields (`{'default': 'Ross'}`) in player name columns

**Solutions found:**
- Fetch rosters from all 32 teams to build active player filter
- Added retry loop with `time.sleep(5)` on 429 in `getRosterData`
- `time.sleep(0.5)` between requests as baseline throttle

---

## Resources & References

**APIs:**
- NHLE API (unofficial, no auth): `https://api-web.nhle.com/v1/`
- Key endpoints:
  - Team roster: `/v1/roster/{teamAbbrev}/current`
  - Standings (for team list): `/v1/standings/now`
  - Per-player stats + game log: `/v1/player/{id}/landing`

**Libraries:**
- `requests` — HTTP calls to NHLE API
- `pandas` — DataFrame creation and manipulation
- `concurrent.futures` — `ThreadPoolExecutor` for parallel API calls

**Helpful Documentation:**
- NHLE API community docs: https://gitlab.com/dword4/nhlapi

---

## Current Phase
**I am currently working on:** Phase 1b — Current Season Stats fetch

**Next immediate task:**
- [ ] Explore `/v1/player/{id}/landing` in browser — map the fields you want
- [ ] Add `getPlayerStats(player_id)` to `nhlAPI.py`
- [ ] Add `extractCurrentStats(json, player_id)` to `dataProcessing.py`
- [ ] Add `makeAllStatsDataFrame(player_ids)` with `ThreadPoolExecutor`
- [ ] Add `getAllStatsWithCache(player_ids)` with 24-hour TTL cache
- [ ] Wire up in `main.py` and verify row count + columns

**Blocked on:**
- Nothing currently

---

## Success Criteria

1. Technical goals:
   - [ ] Full data pipeline from API → cache → features → model running end-to-end
   - [ ] Model beats naive "best player available by name recognition" baseline

2. Learning goals:
   - [ ] Comfortable with pandas DataFrame manipulation
   - [ ] Understand how to structure an ML feature matrix

3. Practical goals:
   - [ ] Actually helps me win my fantasy league!
   - [ ] Usable during draft and weekly pickup decisions

---

**Remember:** This is a learning project. It's okay if your first version isn't perfect. The goal is to practice, make mistakes, debug, and learn. You're building real skills by working through real problems!

**When stuck:** Try things, break things, google errors, ask specific questions. That's how you learn.

**When frustrated:** Step back, tackle smaller pieces, review what you've learned so far.

You've got this! 🏒
