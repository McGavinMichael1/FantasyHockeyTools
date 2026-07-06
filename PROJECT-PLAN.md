# Fantasy Hockey Tools - Project Plan

> Rewritten July 2026 after a state-of-the-repo review. The old plan (see git history)
> described phases that are long done. This version records what's actually built,
> what to simplify, and the road to a **draft analyzer + keeper analyzer before the
> October draft**.

## Project Overview
**Goal:** ML-powered fantasy hockey toolkit for my Yahoo league (nhl.l.33072):
1. **Pickup analyzer** (in-season) — rank available free agents by short-term value *(working prototype)*
2. **Draft analyzer** — project next-season fantasy value to rank draft targets *(build by late Sept)*
3. **Keeper analyzer** — decide which 4 players to keep *(build by late Sept)*

**Key Principle:** Real hockey performance ≠ fantasy value for *this* league's scoring.

**Learning Goals:** Python project structure, real-world APIs and messy data, applied ML
(feature engineering, leakage-safe splits, evaluation), end-to-end product thinking.

---

## Current State (as of July 3, 2026)

### What's built and working
- **NHL API pipeline** (`src/nhlAPI.py`, `src/dataProcessing.py`): all 32 rosters,
  per-player current-season + last-5 stats, threaded fetch, 24h CSV caching, name flattening
- **Fantasy points** (`src/fantasyPoints.py`): skater scoring from NHL API stats
- **Yahoo integration** (`src/yahooAPI.py`): OAuth, rostered-player fetch, fuzzy name → NHLE id
  matching with rapidfuzz
- **Heuristic ranker** (`src/features/pickups.py::rankFreeAgents`): season PPG + last-5 blend,
  filters rostered/goalies/small samples
- **ML pickup models** on MoneyPuck game-level data (`src/features/mlFeatures.py`):
  rolling-window features (5/10/20 games), "heating up" / "cooling down" labels vs. own baseline
  - `src/models/pickups.py` — XGBoost classifier + RandomizedSearchCV, season-based splits
  - `src/models/cooling.py` — XGBoost cooling-down classifier
  - `src/models/lstmPickups.py` — LSTM sequence model (experimental, has a bug — see below)
- **Blended output** (`main.py`): 0.3 × heuristic + 0.7 × ML score, prints top 20
- **Streamlit skeleton** (`ui/app.py`, `ui/pages/`): pages exist but are TODO stubs
- **Data on disk** (`data/raw/`, gitignored):
  - `moneypuck_2020_2024.csv`, `moneypuck_current.csv` — game-level skater logs (ML training)
  - `2008_to_2024.csv` (2.6 GB) — full-history MoneyPuck game logs, **all situations** — this is
    the draft-model training set
  - `players_cache.csv` — identity incl. `birthDate` (age features) and `positionCode`

### Known bugs / debt (fix in Phase A)
- [x] `requirements.txt` missing packages — *fixed July 2026: frozen from venv (streamlit had
      never even been installed — the UI skeleton had never run)*
- [x] **ML label ≠ league scoring** — *fixed July 2026: `fantasyPoints.moneypuckGamePoints`
      scores with full league weights (hits, blocks, PPP/SHP from situation rows);
      `SKATER_WEIGHTS` is the single source of truth, pinned by pytest*
- [x] **LSTM save bug** — *fixed (1-line) but model stays PARKED*
- [x] `cooling.py` plot collisions — *plots now `reports/{model}_*.png` with correct titles*
- [x] `main.py` retrains every run — *now `python main.py train-pickups | pickups`*
- [ ] `extractCurrentStats` hardcodes season `20252026` (Phase E)
- [x] Empty V2 stub files — *deleted*
- [ ] Goalies: no scoring path, no model, filtered out of ranker (Phase D)

---

## Design Decisions Going Forward (the "do differently" list)

1. **MoneyPuck is the single stats source for all modeling.** The NHL API stays for what it's
   uniquely good at: player identity, `birthDate`, `positionCode`, active rosters. Deriving season
   totals and last-N form from MoneyPuck game logs removes the duplicated fantasy-point logic and
   (eventually) the 700-request threaded stats fetch.
2. **One canonical scoring function**, full league rules, used by *both* the heuristic ranker and
   ML labels. Approximation, documented: GWG (1 pt, rare) and +/- (0.5) are excluded — MoneyPuck
   doesn't carry them directly and they're small relative to G/A/SOG/HIT/BLK/PPP.
3. **Park the LSTM.** It's a great learning artifact but it's buggy, marginal over XGBoost, and
   not needed for the October goal. Keep the file, fix it *after* draft season if curiosity strikes.
   XGBoost is the product model.
4. **Draft model predicts per-game rate, not totals.** Target = next-season fantasy **PPG**
   (totals conflate skill with injury luck). Display projected totals as `PPG × 78` for readability.
5. **Ranking is what matters.** Primary metric = Spearman rank correlation on a held-out season;
   MAE secondary. A draft tool that orders players correctly wins even if point values are off.
6. **Baselines before models, always.** "Last season's PPG" and "3-season weighted PPG" must be on
   the scoreboard before any ML model claims credit.
7. **Train/predict separation**: `main.py train-pickups | train-draft | pickups | draft | keeper`
   subcommands (argparse). Streamlit is the product interface; scripts are the workbench.
8. **Add pytest for pure functions only** — scoring math, season aggregation, label construction.
   Cheap to write, catches the exact class of bug found in this review (wrong scoring formula),
   and it's a core skill. No need to test API wrappers.
9. **Repo hygiene**: plots → `reports/` (gitignored); model binaries stay committed (small,
   convenient); the 2.6 GB CSV stays local-only (already gitignored).
10. **Simplification accepted**: no injury feeds, no schedule-strength, no prospect tracker until
    the three core tools work end to end. (Ideas preserved in "Parked Ideas" below.)

---

## Roadmap

```
Phase A: Foundation cleanup        July 6  – July 19
Phase B: Draft analyzer            July 20 – Aug 23
Phase C: Keeper analyzer           Aug 24  – Sept 6
Phase D: Draft UI + goalies        Sept 7  – Sept 20
  (buffer: Sept 21 → draft day)
Phase E: In-season pickups v2      Oct+
```

---

### Phase A: Foundation Cleanup (July 6 – 19)
**Status:** [ ] Not started — **START HERE**

#### A1 — Fix requirements + delete dead stubs
- [ ] `pip freeze` the venv into `requirements.txt` (or hand-add the missing five); verify a fresh
      `pip install -r requirements.txt` in a scratch venv imports everything `main.py` needs
- [ ] Delete `src/features/mlFeaturesV2.py` and `src/models/pickupsV2.py`
- [ ] Add `reports/` for plots; point `plt.savefig` calls there; gitignore it; fix the copy-pasted
      "Pickup Model" titles in `cooling.py`

#### A2 — Canonical league scoring from MoneyPuck (the important one)
- [x] New module `src/moneypuck.py` owning all MoneyPuck IO:
      `loadGameLogs(min_season)` keeps **all** situation rows, reads the 2.6 GB history file
      with `usecols`, caches the filtered concat to `data/processed/`
      **No auto-downloader** — MoneyPuck's data page redirects scrapers to a data-license
      notice; refreshing `moneypuck_current.csv` stays a manual browser download, and
      `checkCurrentFreshness()` nags when the file is > 3 days old
- [x] In `src/fantasyPoints.py`, `moneypuckGamePoints(df) -> DataFrame` (one row per
      player-game with `powerPlayPoints`, `shorthandedPoints`, `fantasyPoints` added):

```
FP = 3·I_F_goals + 2·(I_F_primaryAssists + I_F_secondaryAssists)
   + 0.15·I_F_shotsOnGoal + 0.15·I_F_hits + 0.35·shotsBlockedByPlayer
   + 1·PPP + 1·SHP
where per game: PPP = I_F_points summed over situation == '5on4'
                SHP = I_F_points summed over situation == '4on5'
(5on3 points land in situation 'other' — slight PPP undercount, accepted)
```

  Practical shape: pivot situation rows to columns per (playerId, gameId), then compute one FP
  per player-game. This replaces `game_fantasy_points` inside `mlFeatures.loadMoneyPuckData`.
- [x] **Acceptance check (passed):** 2023-24 season through the new pipeline — Matthews
      69G/38A and McDavid 32G/100A match official numbers exactly; McDavid PPP 42 vs
      official 44 = the documented 5on3 undercount; top-10 FP list is the expected elite tier

#### A3 — First tests
- [x] pytest installed; `pytest.ini` sets `pythonpath = .` and `testpaths = tests`
- [x] `tests/test_fantasyPoints.py` — hand-computed FP for special-teams, no-special-teams,
      and multi-player/multi-game cases (TDD: watched them fail first)
- [x] `tests/test_moneypuck.py` — season filter, situation retention, cache reuse
- [x] `pytest -v` → 5 passed

#### A4 — Train/predict CLI split
- [x] `main.py` now argparse subcommands: `train-pickups`, `pickups`; room for
      `train-draft` / `draft` / `keeper` in Phase B/C
- [x] Retrained pickup + cooling models on the corrected FP label (see Learning Log for AUC)
- [x] LSTM parked with note; the `save(model)` signature crash fixed (1 line) while parking

---

### Phase B: Draft Analyzer (July 20 – Aug 23)
**Status:** [ ] Not started

**Objective:** rank skaters by projected next-season fantasy PPG, trained on 2008–2024 history.
This is a *season-level regression* — simpler than the pickup classifier, and offseason-friendly
(no live data needed).

#### B0 — League-wide keeper input (manual, since Yahoo doesn't expose it until draft day)
- [ ] Fill in `data/raw/keepers.csv` (one Yahoo display name per row, `player_name` column)
      before running the draft ranker each year -- keeper lists change year to year and
      Yahoo's API doesn't reflect them until the draft actually happens
- [ ] `src/keepers.py::loadKeepers()` reads the file; `filterOutKeepers()` fuzzy-matches
      names against a players DataFrame (same rapidfuzz approach as
      `yahooAPI.getRosteredNHLIds`) and drops them from the draft pool
- [ ] Distinct from Phase C's `src/keeper.py` -- that one decides which of *my* players
      are worth keeping; this one just removes *everyone's* keepers from the draft pool

#### B1 — Player-season aggregation table
- [ ] In `src/moneypuck.py`: `buildPlayerSeasons(game_df) -> DataFrame`, one row per
      (playerId, season), aggregating from game logs (source: `2008_to_2024.csv` + current file):
      games played, total FP (from A2), FP per game, goals, assists, SOG, hits, blocks, PPP, SHP,
      avg icetime, avg gameScore, xGoals, goals − xGoals (shooting luck), high-danger share
- [ ] Cache to `data/processed/player_seasons.csv` (this is small — a few MB — rebuild on demand)
- [ ] **Acceptance check:** row count ≈ (number of seasons × ~900 skaters); spot-check one player's
      season line vs hockey-reference

#### B2 — Draft features (implement the existing stub `src/features/draft.py::build_draft_features`)
One row per (playerId, season) = "what you knew at draft time," predicting the season *ahead*:
- [ ] Prior-season: FP/game, games played, TOI/game, PP share of FP, hits+blocks share of FP
- [ ] Trajectory: 3-season weighted FP/game (e.g. 50/30/20), season-over-season delta
- [ ] Regression-to-mean signals: prior-season `goals − xGoals` (positive = ran hot, likely to fall)
- [ ] Age at season start (join `players_cache.csv::birthDate`; for retired/old seasons players
      missing from the cache, derive age from MoneyPuck name+history or drop — decide when you
      see the join hit rate)
- [ ] Position one-hot
- [ ] Rookies/no-history players: **excluded in v1** (they need a different data source — parked)

#### B3 — Baselines, then model (`src/models/draft.py` — the stub interface is already right)
- [ ] Target: next-season FP/game, restricted to player-seasons with ≥ 20 GP in both seasons
- [ ] Splits by season: train ≤ 2021 → val 2022+2023 → test 2024 (never random rows — leakage)
- [ ] Baseline 1: predict last season's FP/game unchanged. Baseline 2: 3-season weighted average.
      Record Spearman + MAE for both **first**
- [ ] Model 1: Ridge regression (interpretable — look at coefficients, sanity-check signs)
- [ ] Model 2: XGBoost regressor (reuse the RandomizedSearchCV pattern from `pickups.py`)
- [ ] Keep whichever beats the baselines on val; confirm once on test-2024 and stop touching it
- [ ] `train(df)` saves to `models/draft/model.pkl`; `predict(df)` returns FP/game Series

#### B4 — 2026-27 projections
- [ ] Feature rows from the 2025-26 season → predict → join names/positions/age →
      `data/processed/draft_rankings.csv` with: name, pos, age, projected FP/game,
      projected total (×78), last-season FP/game, delta
- [ ] `python main.py draft` prints top 100
- [ ] **Sanity check:** eyeball top 20 — McDavid-tier players on top, no 38-year-olds ranked on
      one lucky season. If it looks wrong, it is wrong — debug features before trusting metrics.

---

### Phase C: Keeper Analyzer (Aug 24 – Sept 6)
**Status:** [ ] Not started

**Keeper value = projected value − what a replacement would give you.** A 60-FP/season player is
worthless as a keeper if the draft is full of 60-FP players at his position.

#### C1 — Document league keeper rules (do this first — it changes the math)
> **TODO (me, from Yahoo league settings):**
> - How many keepers? (plan history says 4)
> - Do keepers cost a draft pick / round? Which round?
> - Any restrictions (rounds drafted, years kept)?

#### C2 — Replacement value (`src/keeper.py`)
- [ ] From `draft_rankings.csv`, compute positional replacement level: with 10 teams and starting
      slots 2C / 2LW / 2RW / 4D + 2 Util, replacement ≈ the projected FP of the (10 × slots + Util
      share)-th ranked player at each position (e.g. ~25th C, ~45th D). Implement as
      `replacementLevel(rankings_df) -> dict[pos, fp]`
- [ ] `keeperValue(player) = projected_total − replacement[pos]` (VORP)
- [ ] If keepers cost a draft pick: subtract the projected value of the player you'd otherwise get
      at that pick (approximate: the Nth-best available in `draft_rankings.csv`)
- [ ] `python main.py keeper` → my roster (via existing `yahooAPI` + fuzzy matching) ranked by
      keeper value, recommend top 4

---

### Phase D: Draft-Day UI + Goalies (Sept 7 – 20)
**Status:** [ ] Not started

- [ ] `ui/pages/draft.py`: load `draft_rankings.csv`; sortable table; position filter;
      **"mark as drafted"** checkboxes backed by `st.session_state` so the board stays usable
      live during the draft; best-available-by-position panel
- [ ] `ui/pages/keeper.py`: my roster with keeper values, top-4 highlighted
- [ ] Goalies v1 = **no ML**: fetch goalie season stats from the NHL API landing endpoint
      (W/L/GA/SV/SO — the fields are in the league scoring table below), apply
      `calculateGoaliePoints`, rank by last-season fantasy points, show as its own table with a
      "last season, not a projection" label. Good enough to not draft blind at 2 G slots.
- [ ] Run a **mock draft against last year's results** as the end-to-end test: would this board
      have beaten my actual 2025 draft?

---

### Phase E: In-Season Pickups v2 (Oct+, after the draft)
- [ ] Wire the (retrained, corrected-label) pickup model into `ui/pages/pickups.py`
- [ ] Fix the hardcoded `20252026` season id (derive from date, or config constant)
- [ ] Weekly rhythm: manually download fresh `moneypuck_current.csv` (license — see decision
      notes) → `python main.py pickups` (or the Streamlit page)
- [ ] Revisit: heuristic/ML blend weights, cooling-model surfacing for *drop* candidates,
      un-park the LSTM if still curious (fix the `save(model)` signature bug first)

#### E-ML — Pickup + cooling model improvements (suggested order, from July 2026 model review)
1. **Tuning (cheap, mechanical — do first):**
   - [ ] Tune the cooling model at all — `cooling.py` is hardcoded (`n_estimators=100,
         max_depth=5, lr=0.1`) while pickups gets a 20-iter search; reuse the same search
   - [ ] Replace the `n_estimators` grid with early stopping: `n_estimators=2000`,
         `early_stopping_rounds=50` against the val set, let each candidate pick its tree count
   - [ ] Widen the search space: `min_child_weight` (up to 20–50 — noisy labels reward heavy
         regularization), `reg_alpha`, `reg_lambda`, `gamma`; make `learning_rate` log-uniform
   - [ ] Swap RandomizedSearchCV for Optuna (TPE) — more sample-efficient at 20–50 trials,
         native continuous/log ranges
   - [ ] Validate across seasons, not just 2023: expanding-window folds (≤2021→2022, ≤2022→2023,
         optionally fold in 2024), pick hyperparams by mean AUC; keep 2025 held out for backtest
2. **Features (most likely source of real signal):**
   - [ ] Trend deltas: `rolling_5 − rolling_20` for fantasy points and icetime — "heating up"
         and "coach is promoting him" as explicit features instead of splits the trees must learn
   - [ ] PP deployment: 5on4 TOI from MoneyPuck situation rows + its 5-vs-20 delta — a PP1
         promotion (e.g. the Raddysh/Hedman-injury case in `backtest.py`) is the classic
         breakout signal the current features miss
   - [ ] Regression-to-mean: rolling sum of `xgoals_surplus`, rolling sh% vs career sh% —
         should help the weaker cooling model most (0.64 val AUC vs pickups' 0.73)
   - [ ] Schedule context (games next 7 days, rest days, back-to-backs) — parked-ideas overlap;
         only if the above pans out
3. **Reformulate as regression, grade with the backtest:**
   - [ ] Try `XGBRegressor` on `next_5_avg` FP directly instead of the binarized 75th/25th
         percentile labels — binarizing throws away signal, and the UI ranks anyway
   - [ ] Evaluate with Spearman vs realized next-5 FP and, primarily, `backtest.py`'s
         top-K-of-free-agent-pool hit rate — that's the product metric, not global AUC
   - [ ] Caveat to watch: the league-percentile label partly learns "is good" rather than
         "is heating up" (check whether `season_avg_so_far` dominates feature importance);
         regression + ranking within the FA pool sidesteps this

---

## League Scoring Rules (reference — unchanged)

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

Roster: C, C, LW, LW, RW, RW, D, D, D, D, Util, G, G, BN×5, IR+×2 — 10 teams, 4 keepers.

**ML-label approximation (decision #2):** GWG and +/- are excluded from MoneyPuck-derived scoring;
both are small and partly luck-driven. Documented, accepted.

---

## Milestones

- **M1 (July 19):** Foundations clean — correct scoring everywhere, tests green, CLI split,
  fresh-clone install works
- **M2 (Aug 23):** Draft model beats both baselines on Spearman for held-out 2024; 2026-27
  rankings CSV generated and sanity-checked
- **M3 (Sept 6):** Keeper recommendations for my actual roster
- **M4 (Sept 20):** Draft-day Streamlit board + goalie table; mock-draft tested. **Draft-ready.**
- **M5 (Oct):** Pickups running weekly in the UI

---

## Parked Ideas (V2 — not before the draft)
- LSTM pickup model (exists, parked with known save() bug)
- Prospect & callup tracker (< 5 GP watchlist; needs transaction feed)
- Power play opportunity analyzer (last-5 PP rate vs season PP rate; needs PP unit data)
- Trade analyzer, lineup optimizer, injury feeds, schedule difficulty
- Rookie draft projections (needs junior/AHL data source)

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

### April 2026
- Built first ML models: XGBoost heating-up/cooling-down classifiers on MoneyPuck rolling windows,
  plus an experimental LSTM; blended heuristic + ML scores in `main.py`

### July 2026 (state review on return)
**What the review found — lessons for next time:**
- The plan doc drifted three phases behind the code. Update "Current Phase" *every session* —
  it's the whole point of the shared memory layer
- The ML label silently diverged from league scoring (G/A/SOG only). Lesson: any constant that
  encodes domain rules (scoring weights) must live in ONE module, and a unit test should pin it
- A function signature changed (`save`) without updating its caller — untested code paths rot
  invisibly; even one smoke test would have caught it
- `requirements.txt` drifted from the venv — freeze after every new install (streamlit turned
  out to have never been installed at all: the UI skeleton had never actually run)
- Empty "V2" placeholder files are a smell: evolve modules in place, git keeps the history

**Phase A results (July 3):**
- Corrected-label retrain: pickup model **val AUC 0.7284**, cooling model val AUC 0.6425
  (train AUC 0.7332 — small train/val gap, not badly overfit)
- The old committed roc_curve.png said "AUC 0.64" under a "Pickup Model" title — but cooling
  trained last and overwrote the file, so that was really the *cooling* curve. The plot-collision
  bug destroyed the only record of the old pickup AUC. Lesson: metrics belong in text/logs you
  can diff, not just in overwritable images
- Fuller label (hits/blocks/PPP/SHP) appears *more* learnable than G/A/SOG — makes sense:
  hits and blocks are stable role-driven stats, less shooting-luck noise
- MoneyPuck's data page now redirects automated scrapers to a data-license notice — so no
  auto-downloader; refreshing `moneypuck_current.csv` stays a manual browser download
  (`moneypuck.checkCurrentFreshness()` nags when it's stale)

---

## Resources & References
- NHLE API (no auth): `https://api-web.nhle.com/v1/` — roster: `/v1/roster/{team}/current`,
  player landing: `/v1/player/{id}/landing`; community docs: https://gitlab.com/dword4/nhlapi
- MoneyPuck data downloads (game-level skater CSVs, all situations): https://moneypuck.com/data.htm
- Yahoo: `yahoo_fantasy_api` + `yahoo_oauth`, league id `nhl.l.33072`, creds in `oauth2.json`
  (gitignored ✓)

---

## Current Phase
**I am currently working on:** Phase B — Draft Analyzer (Phase A completed July 3, 2026)

**Next immediate task:**
- [ ] B0: fill in `data/raw/keepers.csv`, implement `src/keepers.py`
- [ ] B1: `buildPlayerSeasons(game_df)` in `src/moneypuck.py` — aggregate game logs to one row
      per (playerId, season), cache to `data/processed/player_seasons.csv`
- [ ] B2: draft features in `src/features/draft.py::build_draft_features`

**Blocked on:** nothing. (C1 needs my league's keeper-cost rules from Yahoo settings before Phase C.)
