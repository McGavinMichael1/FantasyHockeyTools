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
  rolling-window features (5/10/20 games), continuous `next_5_avg` regression target
  (league-percentile binary labels kept for diagnostics/LSTM)
  - `src/models/pickups.py` — XGBoost regressor + RandomizedSearchCV (Spearman), season-based splits
  - `src/models/cooling.py` — XGBoost regressor; low projected next-5 FP/g = drop candidate
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
- [ ] MoneyPuck-only pickup pipeline hardcodes season `20252026` in `api_export.py` headshot URL (Phase E)
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
- [x] In `src/moneypuck.py`: `buildPlayerSeasons(game_df) -> DataFrame`, one row per
      (playerId, season), aggregating from game logs (source: `2008_to_2024.csv` + current file):
      games played, total FP (from A2), FP per game, goals, assists, SOG, hits, blocks, PPP, SHP,
      avg icetime, avg gameScore, xGoals, goals − xGoals (shooting luck), high-danger share
- [x] Cache to `data/processed/player_seasons.csv` via `scripts/build_player_seasons.py`
      (16,237 rows, ~5 MB — rebuild on demand with `min_season=2008`)
- [x] **Acceptance check:** 16,237 rows / 18 seasons = 902 per season (≈ expected); McDavid
      2023-24 spot-check 76 GP / 32 G / 100 A / 42 PPP — matches hockey-reference exactly

#### B2 — Draft features (implement the existing stub `src/features/draft.py::build_draft_features`)
One row per (playerId, season) = "what you knew at draft time," predicting the season *ahead*:
- [x] Prior-season: FP/game, games played, TOI/game, PP share of FP, hits+blocks share of FP
      (own-season columns — row *is* the concluded season, so no shift; `PP_share`, `hitblock_share`)
- [x] Trajectory: 3-season weighted FP/game (`fp_w3`, 50/30/20), season-over-season delta (`fp_delta`)
- [x] Regression-to-mean signals: prior-season `goals − xGoals` (== own-season `xGoalsSurplus` column)
- [x] Age at season start (`age_at_season_start`) — **derived from NHL API landing `birthDate`, NOT
      `players_cache.csv`**: cache join hit only 18.4% on training seasons (retired players absent),
      so built `data/raw/player_birthdates.csv` for all 3038 players → 100% coverage
- [x] Position one-hot (`pos_*`, via `pd.get_dummies` concat — keeps raw `position` for B4/C)
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
      > **SUPERSEDED 2026-07-16:** goalies now have a trained ranker (not last-season-only, and
      > interleaved with skaters by VORP rather than shown as a separate table) — see
      > `docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md` and the goalie
      > analyzer Learning Log entry / Current Phase items below. `GOALIE_WEIGHTS` +
      > `calculateGoaliePoints` shipped in `src/fantasyPoints.py`; the ranker is
      > `src/models/goalieDraft.py`.
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
3. **Reformulate as regression, grade with the backtest:** ✅ DONE July 6, 2026 — see Learning Log
   - [x] Try `XGBRegressor` on `next_5_avg` FP directly instead of the binarized 75th/25th
         percentile labels — binarizing throws away signal, and the UI ranks anyway
   - [x] Evaluate with Spearman vs realized next-5 FP and, primarily, `backtest.py`'s
         top-K-of-free-agent-pool hit rate — that's the product metric, not global AUC
         (result: spot-check mean 40% vs classifier's 41% — similar, both >> 32% baseline)
   - [x] Caveat to watch: the league-percentile label partly learns "is good" rather than
         "is heating up" (check whether `season_avg_so_far` dominates feature importance);
         regression + ranking within the FA pool sidesteps this (checked: ranks 4th, icetime 1st)

#### E-UX — Explainable pickup scores (frontend "why", from July 2026 UX review)
Net-new feature, **not** debt: the frontend surfaces model scores as bare bars with no legend and
no reasoning, so the recommendations can't be trusted or acted on. Deferred behind the draft on
purpose. Scoped July 6, 2026 — implementation notes preserved so it isn't re-derived.

1. **Score legend (frontend-only, ~1–2h).** Define the three scores where they're shown
   (`frontend/src/components/PlayerGrid.tsx` headers + a filter-bar popover). What they actually
   are today (post E-ML item 3, July 2026): **Score** = `final_score` = `0.3 × heuristic_norm +
   0.7 × ml_score` (`api_export.py`); **Heat** = `ml_score` = percentile rank of XGBoost-projected
   next-5-game FP/g; **Cool** = `cooling_score` = inverted percentile of the cooling regressor's
   projection (lowest projected next-5 FP/g = 1.0); heuristic = `0.6 × season PPG +
   0.4 × last-5 FPTS` (`src/features/pickups.py:30`). No backend change, no retrain.
2. **Faithful per-row "why" (backend + frontend, ~1 day).** Chose the model-faithful path over
   heuristic chips: the box-score columns shown in the grid are *not* the model's inputs (model
   trains on MoneyPuck `rolling_*` features — `mlFeatures.py:20-42`), so a "why" eyeballed from
   visible stats can contradict the ranking it's explaining.
   - Compute exact tree-SHAP contributions where the model already runs (`api_export.py:88`):
     `model.get_booster().predict(dmatrix, pred_contribs=True)` on the same `X`. **No new
     dependency** (native XGBoost — respects decision #10 / the optuna caution in
     `fht-research-frontier`), no retrain (reads the saved `.pkl`).
   - Emit a `reasons` list per player (top ±2–3 drivers). Main authoring work = a feature→plain-
     English map (`rolling_5_icetime` → "Ice time up (last 5)", `rolling_10_gameScore` → "Strong
     two-way play", etc.).
   - **Honesty detail:** contributions faithfully explain **Heat** (`ml_score`), not the blended
     **Score**. Attach the "why" to Heat/Cool and show the heuristic as its own line — don't
     pretend the drivers explain the 30/70 blend.
   - Frontend: add `reasons` to `frontend/src/types/player.ts`; render top-2 driver chips in a
     new "Why" column + click-row-to-expand for the full ± breakdown (keeps table density down,
     per the same UX review).
   - **Prereq:** models are gitignored — a fresh clone must `train-pickups` before `api_export.py`
     can compute contributions.
3. **Sequencing dependency:** the legend/"why" copy describes *what the model predicts*. If E-ML
   item 3 (regress on `next_5_avg` instead of the binarized top/bottom-quartile label) lands
   first, "Heat = P(top quartile)" becomes "Heat = projected next-5 FP" — do E-UX after E-ML
   settles, or keep the legend copy in sync with whatever the model actually outputs.

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

### July 2026 (E-ML item 3: regression conversion)
**Pre-registered prediction (written before training the regressor):** converting pickups +
cooling from binary classifiers to `XGBRegressor` on `next_5_avg` should keep ranking quality
roughly flat — val AUC-equivalent (regressor score vs the old binary label) within ±0.02 of the
classifier, and mean spot-check top-15 hit rate ≥ the classifier's, with the win (if any) coming
from the continuous target preserving magnitude information the binarized label threw away.

**Same-day classifier baseline (retrained July 6 on current data — data files newer than the
July 3 numbers above):** pickup val AUC **0.8517** (train 0.8509), cooling val AUC **0.7715**.
Spot-check top-15 hit rates @ 2025-11-01/12-01/01-01/02-01/03-01: **60/47/33/13/53% (mean 41%)**
vs last-10-FP baseline 40/27/20/13/60% (mean 32%), pool base rate ~12%.

**Regression results (July 6, 2026):** pickup regressor val Spearman **0.6214** (train 0.6210),
val AUC-equivalent vs `is_heating_up` **0.8465** (classifier: 0.8517); cooling regressor val
Spearman 0.6063, AUC-equivalent vs `is_cooling_down` **0.7673** (classifier: 0.7715). Spot-check
top-15 hit rates: **53/33/33/27/53% (mean 40%)** vs the classifier's 41% mean — matched the
prediction (similar, within ±0.02 AUC-equivalent; hit-rate delta −1.4pp is within top-15 noise),
and still well above the last-10-FP baseline (32% mean). Feature-importance caveat checked:
`season_avg_so_far` ranks 4th (178), behind rolling icetime (310) — the regressor is not just
learning "is already good". Both models now ship as `XGBRegressor` on `next_5_avg`; `predict()`
returns projected next-5 FP/g, and `main.py`/`api_export.py` convert to 0-1 percentile ranks
(cooling inverted) so the heuristic blend and frontend score bars are unchanged.

**Spot-check protocol change (July 6, 2026):** removed the drafted-by-proxy exemption from
`src/backtest.py` — prior-season stars (Malkin, Nelson, McCann, Schmaltz) were genuinely on
waivers, so exempting them hid the KNOWN_PICKUPS cases the backtest exists to grade. Only the
current-season-pace roster proxy (top 150) remains. Under the corrected pool (447-471 players,
base rate 12-16%), regressor and classifier are a statistical dead heat: regressor
**67/53/47/53/53 (mean 55%)** vs classifier **67/60/40/53/53 (mean 55%)**, both well above the
last-10-FP chaser (~39-40%). Conclusion: the regression conversion is not worse — equal ranking
power with a more interpretable output (projected FP/g) and a continuous target for future
feature work (E-ML item 2). (The naive-baseline prints differ by ±1 hit between runs due to
unstable sort tie-breaking on `rolling_10_game_fantasy_points`; cosmetic only.)

**Spot-check pseudo-simulation added (July 6, 2026):** `runSpotChecks` now replays the season
in date order — the top `PICKUPS_PER_DATE` (5) recommendations at each date are treated as
picked up and removed from later pools, model and chaser each shrinking their own pool
independently. This stops a model from re-crediting the same hot player at every date and adds
a season-level product metric: hit rate and avg realized next-5 FP/g of the 25 simulated adds.
**Current numbers to beat (regressor):** per-date top-15 hit rates 67/60/47/53/47 (**mean
55%**); simulated adds **60% hit rate, 2.83 FP/g avg** vs chaser 40% / 2.35 FP/g. Classifier
under the same sim: top-15 mean 52%, adds 60% / 2.84 FP/g — still a dead heat on adds,
regressor slightly ahead on top-15. Caveat, accepted for now: with the drafted-proxy exemption
gone, early-season sim adds include slow-starting superstars (Q. Hughes, Panarin, Ovechkin on
Nov 1) who would never be on real waivers — absolute numbers are optimistic, but the
model-vs-baseline comparison stays fair since both draw from the same pool.

### July 2026 (Phase B1: player_seasons cache built)
**GATE B1 passed (July 6, 2026).** Ran `scripts/build_player_seasons.py`
(`loadGameLogs(min_season=2008)` → `buildPlayerSeasons` → `data/processed/player_seasons.csv`).
Result: **16,237 rows across 18 seasons (2008–2025), 902 rows/season** — squarely in the expected
~900-skaters band, so situation rows were *not* double-counted (aggregation correctly routed
through `moneypuckGamePoints`). McDavid 2023-24 spot-check: **76 GP / 32 G / 100 A / 42 PPP** —
G and A match hockey-reference exactly; PPP reads 42 vs official 44, the known/accepted 5-on-3
undercount. Side effect: first run also wrote the game-level cache `moneypuck_games_2008.csv`
(distinct from the pre-existing `moneypuck_games_2020.csv`). `buildPlayerSeasons` still does not
self-cache — the `.to_csv` lives in the build script, run on demand. Next: B2 will refactor
`build_draft_features` to read this season table directly instead of rebuilding it internally.

### July 2026 (Phase B2: draft features complete)
**All B2 features landed and verified against `player_seasons.csv` (July 6, 2026).**
`build_draft_features` refactored to take the season table directly (no more internal
`buildPlayerSeasons` rebuild every call). Features: `career_games`, `PP_share`, `hitblock_share`,
`fp_delta` (season-over-season), `fp_w3` (50/30/20 weighted), position one-hot, `age_at_season_start`,
plus the `target_fpPerGame` = `shift(-1)` next-season target.

**Framing correction (matters for every feature):** the row *is* the most-recent-concluded season
("what you knew at draft time"), so own-season stats are legitimate features — **no `shift(1)` on
features**. Only the *target* shifts (`shift(-1)`, next season). Backward lags (`shift(1)`/`shift(2)`)
appear only inside trajectory features that deliberately look back. Verified on McDavid: 2022 target
(5.392) == 2023 `fpPerGame` exactly; `fp_w3(2023)` == 0.5·2023+0.3·2022+0.2·2021 exactly. NaN counts
reconcile to the row: `fp_delta` NaN = 3038 (one per player's first season); `fp_w3` NaN = 5496
(first two seasons of 3+ season players + all rows of shorter-tenure players).

**Shift discipline is `groupby('playerId')`-scoped, always.** A plain `.shift()` bleeds a value across
the player boundary (pulls the previous *player's* season). Every lag must be `g[col].shift(n)`.
Corollary learned the hard way: `g['col']` bare is a `SeriesGroupBy` (can't do arithmetic); a method
like `.shift()`/`.diff()` "cashes it in" to a `Series`. Current-season terms use the plain column (no
lag → no groupby); only lag terms touch `g`.

**Age: `players_cache.csv` is the wrong source; NHL API landing is right.** Measured the join hit
rate first (per the plan's "decide when you see it"): `players_cache` is current-roster only, so it
covered just **18.4%** of training-season (≤2021) rows and 27.2% overall — retired players simply
aren't in it, and the coverage ramps season-by-season with attrition (2008: 1%, 2025: 67%). Dropping
NaN-age rows would have discarded 82% of training data. Fix: `birthDate` from the NHL API
`/player/{id}/landing` endpoint covers retired players too. Added `dataProcessing.getAllBirthDatesWithCache`
(reuses the threaded `fetchAllPlayers` pattern, caches permanently since birthDates are immutable) and
`scripts/build_birthdates.py`; fetched all 3038 players → **100% age coverage**, zero absurd ages
(min 18.05, max 47.68 = Chelios 2008-09). `age_at_season_start` uses a real fractional age at an Oct-1
season start, not year subtraction. **Lesson reinforced:** when a join is the data source, measure the
hit rate before committing to it — the "obvious" cache can be catastrophically incomplete for
historical rows.

**Fixed a latent infinite-loop in `nhlAPI.getPlayerStats`** while there: its `while True` only broke on
200/429, so any persistent 404/500 spun forever — invisible at one-off call volume, a guaranteed hang
over 3038 calls. Now bounded (raises after 3 unexpected statuses; the `fetchAllPlayers` worker catches
and skips). Affects the pickup pipeline too, strictly for the better.

### July 2026 (PP_share unit fix)
**`PP_share` was mixing units — corrected to fantasy points (July 7, 2026).** The B2 feature computed
`totalPPP / totalFP`, i.e. the raw powerplay-*point* count (each PP goal or assist = 1) over total
*fantasy* points. The PPP league weight happens to be 1, so it was dimensionally legal but understated
PP reliance ~3× and — worse for the model — couldn't tell a goal-heavy PP producer from an assist-heavy
one at equal PPP (a PP goal is worth 3+1 fantasy, an assist 2+1). It was also inconsistent with its
sibling `hitblock_share`, which already converts to fantasy units (`hits*0.15 + blocks*0.35`). Fix:
carry the 5on4 scoring breakdown through the pipeline — `moneypuckGamePoints` now emits `powerPlayGoals`
/ `powerPlayAssists` (summed I_F_goals / primary+secondary assists on 5on4 rows), `buildPlayerSeasons`
aggregates `totalPPGoals` / `totalPPAssists`, and `draft.py` computes
`(totalPPGoals*3 + totalPPAssists*2 + totalPPP*1) / totalFP`. Class-(a) change: pinned in
`tests/test_fantasyPoints.py` first (watched fail), then implemented; `player_seasons.csv` rebuilt
(GATE B1 re-passed, McDavid 32G/100A/42PPP unchanged). Eyeball check on 2023: McDavid PP_share 0.10→0.32,
PP specialists (Stamkos, Q. Hughes, Burakovsky) top the list, range 0–0.47, none >1. No model retrain
needed — `train-draft`/`draft` are still stubs. Lesson: a share/ratio feature must have matching units
in numerator and denominator; "the weight is 1 so it cancels" is a coincidence, not a design.

### July 2026 (Phase B3: draft model — GATE B3 passed)
**Feature hardening first (July 15, 2026), before any training:** target masked for gap seasons
(`shift(-1)` only counts as "next season" when `season+1` actually follows — otherwise a 2019 row
was being trained to predict 2021), `fp_w3` weights renormalized over available seasons (was NaN
for every 1-2 season player, which also made Baseline B blind to sophomores), `totalFP` division
guarded, and `target_gamesPlayed` added (same gap mask) so training can require ≥20 GP on the
label side too.

**GATE B3 results (July 15, 2026), train ≤2021 (7,723 rows) → val 2022+2023 (1,206 rows), rows
filtered to ≥20 GP both sides + non-null target:**

| Ranker | val Spearman | val MAE |
|---|---|---|
| Baseline A (last-season FP/g) | 0.7963 | 0.3686 |
| Baseline B (fp_w3 50/30/20) | 0.7965 | 0.3537 |
| Ridge (impute+standardize) | 0.8213 | 0.3287 |
| **XGBoost (shipped)** | **0.8259** | **0.3277** |

**GATE B3: PASS** — XGBoost beats both baselines on val Spearman. Best params: n_estimators=100,
max_depth=5, learning_rate=0.05, subsample=0.7, colsample_bytree=0.7 (RandomizedSearchCV n_iter=20,
PredefinedSplit on the season boundary, Spearman scorer, `refit=False` so the val number comes from
a train-only fit — the auto-refit best_estimator_ would have been scored on rows it trained on).
Final saved model refits on train+val. Ridge coefficient signs all sane: fp_w3 +0.29 and fpPerGame
+0.19 dominate, age −0.14, xGoalsSurplus slightly negative (regression-to-mean works as designed).
Baselines landed *above* the expected 0.6–0.75 band (season-level PPG is stickier than expected);
0.826 is nowhere near the 0.95+ leakage-alarm threshold. **Test-2024 has NOT been touched** — it
gets its one look after B4 wiring, then never again.

`src/models/draft.py` implemented on the pickups pattern; `save()` persists
`{'model', 'feature_cols'}` so `predict()` reindexes to the exact training columns (missing pos_*
→ 0, missing numeric column → raise). `predict()` applies no GP filter by design — at draft time
we still want a projection for an injury-shortened season. Consequence seen in the eyeball smoke
(top-10 on 2024 rows: McDavid, MacKinnon, Kucherov, Draisaitl, Matthews — correct elites): a
couple of small-sample rows (e.g. Taylor Ward at 5.05 FP/g in a handful of games) crack the list,
so **B4 rankings need a display-side GP floor** on the feature season.

### July 2026 (Goalie analyzer — GATES G1, G3, G4)
**Shipped 2026-07-16 (branch `codex/keeper-analyzer`, commits d6aa10e..770e427). Design spec:
`docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md`.** Goalies went from "no
scoring path" to a full draft/keeper ranker interleaved with skaters by VORP. Scoring is
`fantasyPoints.GOALIE_WEIGHTS` + `calculateGoaliePoints` (single source of truth, same discipline
as `SKATER_WEIGHTS`; `losses` is regulation-only — owner-confirmed the league doesn't record OT/SO
losses, so no `otLosses` term). Data flows `data/raw/goalies/*.csv` (MoneyPuck skill stats) merged
with NHL API season records into `data/processed/goalie_seasons.csv`; the ranker is
`src/models/goalieDraft.py`; CLI is `main.py train-goalies`.

**GATE G1 (data build, 2026-07-16): PASSED.** `scripts/build_goalie_seasons.py` produced **1,702
rows across 18 seasons (2008–2025)** at a **100.0% MoneyPuck↔NHL-API merge hit rate**. Hellebuyck
2023-24 spot-check matched hockey-reference exactly: GP 60, GS 60, W 37, L 19 (regulation-only), SO
5, SV 1656, FP 310.9 (5.18/gm). (The Phase D plan's "~1,400–1,700" upper estimate was slightly
stale — the actual count is 1,702.)

**GATE G3 (model, 2026-07-16): FAILED → shipped Baseline B.** Val Spearman: Baseline A (last-season
FP/g) **0.2784**, Baseline B (`fp_w3` 50/30/20) **0.4130**, XGBoost **0.3460**. XGBoost beat A but
not B, so the gate failed and **Baseline B (`fp_w3`) ships as the goalie ranker** — the saved
payload is `{'kind': 'baseline_b'}` and `predict()` returns `fp_w3`. Ridge coefficient signs are
sane (`fp_w3` +0.153, `gs_share` +0.073). Test-2024 was **never touched** (the gate failed, so the
one-look rule never triggered). Lesson: goalie season-over-season predictability is far below
skaters' (~0.41 vs ~0.80 val Spearman) — workload volatility (who gets the starts) dominates, so a
trajectory baseline is the honest ranker and ML polish didn't earn its place here.

**GATE G4 (eyeball, 2026-07-16): PASSED.** Top-10 goalies on the VORP board are all workhorse
starters: Vasilevskiy, Hellebuyck, Oettinger, Sorokin, Shesterkin, Thompson, Saros, Swayman,
Gustavsson, Vejmelka (`projected_gp` 51–60 against a 65-start cap). The first goalie (Vasilevskiy)
lands at #13 overall by VORP — goalies and skaters interleave sensibly rather than sitting in a
separate table. Degraded skaters-only mode verified (missing `goalie_seasons.csv` or no trained
goalie model → board drops goalies and prints how to enable them).

### July 2026 (Keeper roster advisor — conversational Phase C overlay)
**Shipped 2026-07-17 (branch `codex/keeper-roster-advisor`). Design spec:
`docs/superpowers/specs/2026-07-17-keeper-roster-advisor-design.md`; plan:
`docs/superpowers/plans/2026-07-17-keeper-roster-advisor.md`.** Added a live, multi-turn keeper
advisor to The Rink that grounds every answer in the full roster, deterministic keeper math, and
league rules, with optional current web research — and labels any recommendation that diverges from
the model.

Architecture keeps Python as the only owner of hockey data and scenario arithmetic. `main.py keeper`
now writes a versioned, content-addressed `data/processed/keeper_advisor_context.json` (built by
`src/keeper_advisor.py::build_context`; `context_id` is a SHA-256 over decision data, so it ignores
timestamps but changes when any keeper value/projection/scenario changes). Non-finite decision data
is rejected up front (inf → `ValueError`); absent values (NaN) stay legal. A server-only Next.js
route (`frontend/src/app/api/keeper-chat/route.ts`) reads that artifact, runs a no-web classification
pass, selects only the relevant deterministic context, and calls Anthropic's Messages API with web
search enabled **only** when the classifier says current information is material. The browser renders
and locally persists conversations keyed by `context_id`; it never receives the raw context or the
API key.

The **model-divergence contract is server-derived, not model-authored**: `keeperAdvisorService`
compares the provider's recommended four to the official scenario and computes stance
(agrees/diverges/conditional), the primary out→in swap (weakest removed official keeper by
`keeper_rank` → highest incoming `raw_keeper_value`), and the exact keeper-value cost. The LLM
cannot mutate `keeper_rankings.csv`, projections, or keeper constants — it's an advisory overlay.
Research metadata comes from actual tool execution, not model prose; web results are treated as
untrusted evidence that cannot override system instructions. Memory is local and context-keyed:
newest 12 turns sent per request, bounded classifier summary stored separately, stale-context
conversations kept read-only. The old one-time cached keeper summary
(`scripts/build_keeper_summary.py`) is retired; `api_export.py` now exports advisor readiness
metadata (`advisor_ready`/`advisor_context_id`/`advisor_generated_at`/`advisor_roster`) instead.

**Gates (2026-07-17): Python 65 passed + the 2 known pre-existing failures (`test_draft_summaries`
token budget, `loadGameLogs` cache-guard order) — no new failures. Frontend 44 unit tests pass,
`tsc --noEmit` clean, `next build` emits `/keeper` (static) and `/api/keeper-chat` (dynamic).** The
live three-turn acceptance (Task 10 step 6) is **pending manual owner acceptance** — it needs
`ANTHROPIC_API_KEY` + `KEEPER_ADVISOR_MODEL` in the environment and makes a paid call, so it was not
run autonomously. Note the frontend test harness required two files the plan didn't enumerate
(`src/types/cssModules.d.ts` for `tsc`, and `test-setup.cjs`/`test-css-stub.cjs` to stub CSS-module
imports under `node --test`); no new npm dependency was added.

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
- [x] B1: `buildPlayerSeasons` + `scripts/build_player_seasons.py` — cached
      `data/processed/player_seasons.csv` (16,237 rows), GATE B1 passed July 6, 2026
- [x] B2: draft features in `src/features/draft.py::build_draft_features` — **done July 6, 2026**.
      Takes `player_seasons` directly; `fp_delta`, `fp_w3`, position one-hot, `age_at_season_start`
      (NHL API birthDate, 100% coverage), prior-season base cols, `target_fpPerGame` = `shift(-1)`.
      All verified on real data; see Learning Log.
- [x] B3: baselines → Ridge → XGBoost in `src/models/draft.py` — **GATE B3 passed July 15, 2026**
      (val Spearman: baselines 0.7963/0.7965, Ridge 0.8213, XGBoost 0.8259; see Learning Log).
      Model saved to `models/draft/model.pkl`. Test-2024 still untouched — one look, after B4.
- [x] B4 wiring + frontend (July 15, 2026): `main.py train-draft`/`draft` live;
      `draft` writes `data/processed/draft_rankings.csv` (704 players, ≥20 GP display floor,
      draft-day age = feature-season age + 1). Missing `keepers.csv` now warns loudly and ranks
      everyone (pre-draft-day mode) instead of raising — fill it on draft day to filter keepers.
      `api_export.py` embeds the CSV as a `draft` section in `frontend_data.json`; The Rink UI
      gained a "Draft board" tab (`frontend/src/components/rink/DraftBoard.tsx`, `?view=draft`).
      Top-20 eyeball gate: PASS (MacKinnon/McDavid/Draisaitl/Kucherov/Celebrini; no small-sample
      or aging flukes). NOTE: local clone was 1 commit behind origin/main (The Rink refactor,
      7c7a454) and the draft tab was first built against the deleted classic UI — pull before
      building on the frontend.
- [x] B5 draft explainability + confidence + Claude summaries (July 15, 2026): per-player
      explanation shipped end to end. `src/draft_explain.py` holds two pure, pytested functions —
      `top_factors` (names/ranks SHAP contributions) and `compute_confidence` (transparent 0–100
      weighted average: history depth 0.25, feature-season GP 0.30, peak-age band 0.20,
      |projection − fp_w3| stability 0.25; missing age/fp_w3 go neutral, never penalized).
      `src/models/draft.py::shap_contributions` wraps the booster's native `pred_contribs=True`
      (no new modelling dependency). `main.py draft` now writes `confidence` + `factor_1..6`
      (JSON `{label, value}` cells, top 3 positive then top 3 negative) into `draft_rankings.csv`.
      `scripts/build_draft_summaries.py` is the canonical summary producer (claude-opus-4-8 +
      `web_search_20260209`, resumable, needs `ANTHROPIC_API_KEY`); `data/processed/draft_summaries.json`
      is the contract, so a Claude Code session is a valid alternative producer on a Pro sub.
      `api_export.py` merges it; The Rink's draft board gained a Conf column + expandable detail.
      Gates: confidence behaves as designed (Tkachuk's 28-game season = 78, the top-20 low;
      Celebrini 20yo = 84 and Kucherov 33yo = 83 both age-penalized; Suzuki 75 GP/age 27 = 100).
      Top-20 order unchanged. Summary eyeball gate: PASS on 5 spot-checks (MacKinnon's playoff
      knee cleared, Draisaitl's 65 GP was a March lower-body injury not decline, Kucherov is the
      reigning Hart winner the model marks down hardest on age) — all added real context rather
      than restating stats. New dependency `anthropic==0.116.0`, pinned in pyproject + requirements.
- [ ] **B4 remainder:** the ONE-time test-2024 confirm (do it deliberately — it burns the only
      held-out look), then fill `data/raw/keepers.csv` on draft day (B0).
- [ ] **B5 remainder:** generate the full top-200 summary batch before draft day (script needs an
      API key the owner doesn't have — plan on a Claude Code session in chunks), then re-run
      `api_export.py`. Only 5 of 704 players have summaries today.

**Goalie analyzer — DONE 2026-07-16** (part of Phase D, ahead of the UI work; branch
`codex/keeper-analyzer`, commits d6aa10e..770e427; spec
`docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md`):
- [x] Goalie scoring: `fantasyPoints.GOALIE_WEIGHTS` + `calculateGoaliePoints` (regulation-only
      losses, owner-confirmed).
- [x] G1 data build: `scripts/build_goalie_seasons.py` merges `data/raw/goalies/*.csv` (MoneyPuck)
      with NHL API season records → `data/processed/goalie_seasons.csv` (1,702 rows / 18 seasons,
      100% merge hit rate; Hellebuyck 2023-24 exact). Permanent cache `data/raw/goalie_nhl_seasons.csv`.
- [x] Goalie features `src/features/goalies.py`; ranker `src/models/goalieDraft.py` +
      `main.py train-goalies`.
- [x] G3 model gate: FAILED (XGBoost 0.346 beat Baseline A 0.278 but not Baseline B 0.413) →
      shipped Baseline B (`fp_w3`) as the ranker. Test-2024 untouched.
- [x] G4 eyeball gate: PASS — top-10 all workhorse starters, first goalie #13 overall by VORP,
      goalies interleave with skaters; skaters-only degrade mode verified.
- [x] Goalies are full keeper candidates (goalie-inclusive keeper board) + goalie rows/VORP
      ordering on The Rink draft board.

**Keeper roster advisor — DONE 2026-07-17** (conversational Phase C overlay; branch
`codex/keeper-roster-advisor`; spec `docs/superpowers/specs/2026-07-17-keeper-roster-advisor-design.md`):
- [x] `main.py keeper` builds a content-addressed `data/processed/keeper_advisor_context.json`
      (`src/keeper_advisor.py`); best-effort so keeper rankings always survive an advisor failure.
- [x] Server-only chat: classification pass → deterministic context selection → Anthropic Messages
      API, web search gated behind `needs_current_research`. Route `/api/keeper-chat`.
- [x] Server-derived model-divergence contract (stance + out→in swap + exact keeper-value cost);
      LLM cannot mutate deterministic keeper data. Research metadata from real tool execution.
- [x] Browser chat persisted locally by `context_id`; stale-context conversations read-only. Cached
      keeper summary retired; `api_export.py` exports advisor readiness metadata.
- [x] Gates: Python 65 passed + 2 known pre-existing failures; frontend 44 tests / `tsc --noEmit` /
      `next build` all clean.
- [ ] **Remainder:** live three-turn acceptance (Task 10 step 6) — pending owner run; needs
      `ANTHROPIC_API_KEY` + `KEEPER_ADVISOR_MODEL` and makes a paid call.

**Blocked on:** nothing. (C1 still needs my league's keeper-cost rules from Yahoo settings to
validate the advisor's pick-cost assumptions; the advisor ships with `keeper_tenure: "unknown"`
surfaced as a context warning until then.)
