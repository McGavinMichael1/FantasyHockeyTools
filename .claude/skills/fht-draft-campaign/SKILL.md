---
name: fht-draft-campaign
description: Use when working on the draft analyzer or keeper analyzer (PROJECT-PLAN.md Phases B, C, D) -- the player_seasons table, draft features, baselines vs. models, draft_rankings.csv, replacement-value keeper math, the mock-draft backtest, or the draft-day board (Next.js) and goalie ranking ahead of the October 2026 draft.
---

# FHT draft campaign

**Framing is `ASSUMED`** (see `.claude/skills/OPEN-QUESTIONS.md` #1): this treats "ship the draft
analyzer + keeper analyzer before the October 2026 draft" as the hardest live problem. Evidence is
strong (`PROJECT-PLAN.md` "Current Phase" says Phase B as of 2026-07-05, and PR #2 just landed
draft-ranker groundwork) but the owner has not explicitly confirmed this is the priority over,
say, fixing the failing test first. If that priority is wrong, this whole runbook is misaimed --
check with the owner before a long session.

This is an executable runbook, not a summary. Each phase has a GATE: an expected observation, and
a branch for what to do if you see something else. Work phases in order; do not skip a gate.
All facts below were verified in the repo on 2026-07-05 -- re-verify anything load-bearing before
you rely on it, since code moves faster than this file.

## Phase 0 -- Preconditions gate

Check these before starting Phase B work; all are cheap and read-only.

1. **Data files present.**
   ```
   ls -la data/raw/2008_to_2024.csv data/raw/moneypuck_current.csv
   ```
   Expect `2008_to_2024.csv` ~2.6 GB (2,620,103,561 bytes, verified) and `moneypuck_current.csv`
   ~155 MB. If either is missing, Phase B1 cannot run -- MoneyPuck has no auto-downloader (data
   license); the owner must manually download from https://moneypuck.com/data.htm. Do not attempt
   to script a downloader.

2. **pytest status known.** `.\.venv\Scripts\python.exe -m pytest -v` currently reports **4
   passed, 1 failed** (verified today) -- the known `loadGameLogs` cache-guard-ordering bug
   (`tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations`; full
   root-cause analysis lives in `fht-debugging-playbook`, do not re-diagnose it here). Phase B1
   calls `loadGameLogs` directly, so decide with the owner whether to fix the guard-ordering bug
   first. The bug only bites when source files are missing/replaced mid-run; it does not block a
   normal build where both files already exist, so it is safe to proceed with Phase B1 without
   fixing it -- but flag the decision, don't silently skip it.

3. **C1 keeper rules -- the single owner-input dependency.** `PROJECT-PLAN.md` lines 215-219: 4
   keepers is known (`PROJECT-PLAN.md:316`, "Roster: ... 10 teams, 4 keepers"). Whether keepers
   cost a draft pick/round, and any restrictions, is **UNKNOWN** and blocks Phase C2's pick-cost
   subtraction term. This cannot be verified from the repo -- it requires the owner to check Yahoo
   league settings for `nhl.l.33072`. Flag it now so it isn't rediscovered as a surprise at Phase C.

## Phase B1 -- player_seasons table

**DONE (2026-07-06): GATE B1 passed.** Build the cache with the runbook script -- do NOT hand-roll a
snippet anymore:
```
.\.venv\Scripts\python.exe scripts/build_player_seasons.py
```
It runs `loadGameLogs(min_season=2008)` -> `buildPlayerSeasons` -> `data/processed/player_seasons.csv`
and prints the GATE B1 acceptance checks. `buildPlayerSeasons` (`src/moneypuck.py:95-136`, landed
PR #2) still does NOT self-cache -- the `.to_csv` lives only in that script. `min_season=2008` (not
`loadGameLogs`' default of 2020) also writes a *new* game cache `data/processed/moneypuck_games_2008.csv`,
a superset of `..._2020.csv` (the filename number is `min_season`, a floor); the first run re-reads
the full 2.6 GB history regardless (minutes). Rebuild on demand each season or if `player_seasons.csv`
is deleted. Full runbook row: `fht-operations` section 3.

**GATE B1 result (2026-07-06): PASSED** -- 16,237 rows / 18 seasons (2008–2025), 902/season; McDavid
2023-24 = 32G/100A/42PPP (exact). The rationale below is retained as the acceptance reference for
future rebuilds. 2008-2024 is 17 seasons + the current season (2025) = 18 seasons. Expect row count
roughly `18 x ~900 skaters` ~= 15,000-17,000 rows.
- If you see 2-3x that row count -> situations were double-counted, meaning
  `moneypuckGamePoints` was not applied before aggregation (it collapses situation rows to one
  row per player-game; summing raw situation rows double-counts because the `'all'` row already
  totals the rest -- see `fht-domain-reference` and the header comment at
  `src/moneypuck.py:95-102`). `buildPlayerSeasons` already calls `moneypuckGamePoints` internally,
  so this failure mode would mean someone bypassed it, not a bug in the existing function.
- Spot-check one player-season against hockey-reference.com by hand.
- Re-run the 2023-24 acceptance numbers already validated for game-level scoring
  (`PROJECT-PLAN.md:133-135`, Learning Log): Matthews 69G/38A and McDavid 32G/100A should match
  exactly when summed to season level; McDavid PPP should read 42 vs the official 44 (documented
  5-on-3 undercount, accepted -- do not chase this discrepancy further).

## Phase B2 -- draft features

**DONE (2026-07-06):** `src/features/draft.py::build_draft_features` now takes the `player_seasons`
table directly (no internal `buildPlayerSeasons` rebuild) and builds every B2 feature: position
one-hots (`pd.get_dummies` concat, keeps raw `position` for B4/C), `career_games`, `PP_share`,
`hitblock_share`, `fp_delta` (season-over-season), `fp_w3` (50/30/20 weighted), `age_at_season_start`,
plus the `target_fpPerGame` = `shift(-1)` target. All verified on real data (PROJECT-PLAN Learning
Log). What each feature is, per `PROJECT-PLAN.md` B2:

- 3-season weighted FP/game (`fp_w3`, 50/30/20) and season-over-season delta (`fp_delta`). Both
  use `groupby('playerId')`-scoped lags -- a plain `.shift()` bleeds a value across the player
  boundary. Lag terms only; current-season terms stay the plain column.
- Regression-to-mean signal: prior-season `xGoalsSurplus` (already computed in
  `buildPlayerSeasons`, `src/moneypuck.py:131`, as `totalGoals - totalXGoals`) -- positive means
  the player ran hot on shooting luck and is more likely to regress down, not up. Under the
  own-season framing (below) this is just the row's own `xGoalsSurplus` column, no shift.
- Age at season start (`age_at_season_start`): **RESOLVED (2026-07-06) -- derived from the NHL API
  landing `birthDate`, NOT `players_cache.csv`.** The hit-rate check settled the "derive or drop"
  fork: `players_cache.csv` is current-roster only, so it covered just **18.4%** of training-season
  (<=2021) rows and 27.2% overall -- retired players aren't in it (coverage ramps 2008: 1% -> 2025:
  67%). Dropping NaN-age rows would have discarded 82% of training data. Fix:
  `scripts/build_birthdates.py` fetches `birthDate` for all 3038 players from `/player/{id}/landing`
  (covers retired players) into the **permanent** cache `data/raw/player_birthdates.csv` -> **100%
  coverage**. `build_draft_features` *reads* that cache (never fetches) and computes a fractional age
  at an Oct-1 season start. Lesson: measure a join's hit rate before trusting the "obvious" cache as
  a source. Runbook row: `fht-operations` section 3.
- Target: `target_fpPerGame` = `g['fpPerGame'].shift(-1)` -- each row predicts the **next** season's
  FP/game, not its own. The row *is* the concluded season ("what you knew at draft time"), so own-
  season stats are legitimate features with **no `shift(1)`**; only the target shifts.

**GATE B2 (leakage rule):** no feature may use same-season-or-later information relative to the
season it predicts. This mirrors the `shift(1)` discipline already used in
`src/features/mlFeatures.py`'s `season_avg_so_far` for the pickup model
(`fht-architecture-contract` section 3) -- the draft table needs the same discipline at the
season grain instead of the game grain. Also restrict training rows to seasons with >= 20 GP in
**both** the feature season and the target season (excludes injury-shortened seasons from
distorting FP/game on both sides).

## Phase B3 -- baselines, then models

`src/models/draft.py` is an all-`TODO`/`NotImplementedError` stub with the right interface
(`train`/`predict`/`load`/`save`, verified by reading it today, matches
`src/models/pickups.py`'s and `src/models/cooling.py`'s shape). Order is **mandatory, settled**:

1. **Baseline A:** predict last season's FP/game, unchanged.
2. **Baseline B:** 3-season weighted average (reuses the B2 trajectory feature). Record Spearman
   + MAE for both baselines on val, in text, **before** touching a model.
3. **Ridge regression.** Sanity-check coefficient signs: age should be negative at the old end,
   prior FP/game strongly positive. If a sign looks wrong, that's a feature bug, not a modeling
   choice to shrug off.
4. **XGBoost regressor.** Reuse the `RandomizedSearchCV` + `PredefinedSplit` pattern already
   proven in `src/models/pickups.py:25-56` (confirmed today: `param_dist` grid over
   `n_estimators`/`max_depth`/`learning_rate`/`subsample`/`colsample_bytree`, `n_iter=20`,
   `scoring='roc_auc'` there -- swap to a regression scorer here, e.g. Spearman or negative MAE).

**Splits (never random rows):** train <= 2021, val 2022+2023, test 2024.

**GATE B3:** a model ships only if it beats **both** baselines on val Spearman. Then confirm once
on test-2024 and stop touching test -- re-touching test-2024 after seeing its score is the
project's explicit anti-pattern (see Fenced-off wrong paths below).
- If no model beats both baselines -> **ship Baseline B as the ranker.** This is an explicit,
  legitimate branch, not a failure state: a correct ordering is the product; ML is optional
  polish on top of it.
- Expected magnitude (label this `ASSUMED` -- domain experience, not repo history): Spearman for
  a last-season-PPG-style baseline on this kind of task typically lands ~0.6-0.75. If a model
  reports 0.95+, suspect leakage (a feature that peeked at the target season) before celebrating --
  check the shift discipline from GATE B2 first.

## Phase B4 -- 2026-27 projections

Build feature rows from the 2025-26 season, predict, join name/position/age, and write
`data/processed/draft_rankings.csv` with columns: name, pos, age, projected FP/game, projected
total (`PPG x 78`), last-season FP/game, delta. Wire `python main.py draft`
(`main.runDraft`, `main.py:135-149`) -- **currently raises `NotImplementedError`**, confirmed by
reading the code (do not run it expecting output). It already calls
`keepers.loadKeepers()` at line 142, which **raises** if `data/raw/keepers.csv` is empty or
missing (confirmed absent from disk today) -- "an empty keeper list silently drafts everyone"
per the `ValueError` message it raises (`src/keepers.py:36`). Fill that CSV (one Yahoo display name per
row under a `player_name` column) before `draft` can run end to end.

**GATE B4 (eyeball gate -- this is a real gate, not a formality):** top-20 of
`draft_rankings.csv` must be McDavid-tier elites, and no 38-year-old should rank highly on one
lucky season. Per `PROJECT-PLAN.md:204-205`: "if it looks wrong, it is wrong -- debug features
before trusting metrics." A model that passes GATE B3's Spearman bar but fails this eyeball check
has a bug the metric didn't catch (common culprit: age join silently failed and everyone got a
default/median age).

## Phase C -- keeper analyzer

`src/keeper.py` **does not exist yet** (confirmed by file check today) -- distinct from
`src/keepers.py`, which already exists and only removes *other teams'* announced keepers from the
draft pool (`src/keepers.py:9-11`, its own docstring makes this distinction explicit). Phase C's
`src/keeper.py` decides which of **your own** roster's players are worth keeping.

**GATE C: blocked until C1.** Keeper math cannot proceed without the pick-cost answer flagged in
Phase 0 step 3. Everything below is planned shape, not runnable yet.

Per `PROJECT-PLAN.md` C2 (lines 221-228), from `draft_rankings.csv`:
- `replacementLevel(rankings_df) -> dict[pos, fp]`: with 10 teams and starting slots
  2C/2LW/2RW/4D + 2 Util, replacement level per position ~= the projected FP of the
  `(10 x slots + Util share)`-th ranked player at that position -- roughly the 25th C, 45th D
  (Util share split across positions, exact split is an implementation choice, not settled).
- `keeperValue(player) = projected_total - replacement[pos]` (VORP-style).
- If C1 confirms keepers cost a pick: subtract the projected value of the Nth-best-available
  player in `draft_rankings.csv` at the pick that would be spent.
- Output: your own roster (via existing `yahooAPI` OAuth + fuzzy name matching, same
  `rapidfuzz.process.extractOne` pattern already used in `src/yahooAPI.py` and
  `src/keepers.py:53`), ranked by keeper value, top 4 recommended.

## Phase D -- draft-day UI + goalies

**Shipped 2026-07-20.** The UI is the Next.js `frontend/`, not Streamlit -- `ui/` was deleted in
the July 2026 sustainability pass.

- Board: `frontend/src/components/rink/DraftBoard.tsx`, fed by `api_export.py` ->
  `data/processed/frontend_data.json`. Sortable, position filter, expandable per-player detail.
- Live draft mode: "mark as drafted" per row, VORP recomputed against the *remaining* pool, and a
  positional-run strip. The math is `frontend/src/lib/liveDraft.ts` (kept out of the component so
  `tsconfig.test.json` can compile it -- that config includes `src/lib` but not
  `src/components/rink`). It mirrors `src/keeper.py::replacement_levels`; keep the two in step.
- Picks persist to `localStorage`, hydrated in an effect rather than during render (no
  `localStorage` on the server -> SSR mismatch).
- Keeper board: `frontend/src/app/keeper/page.tsx` plus the advisor chat.

**Goalie ranker -- SHIPPED 2026-07-16** (full spec:
`docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md`; gates G1/G3/G4 recorded in the
PROJECT-PLAN Learning Log). The old "v1 = no ML, last-season-only, separate table" plan is
superseded -- goalies are now VORP-interleaved with skaters on the same board.

- **Scoring:** `fantasyPoints.GOALIE_WEIGHTS` + `calculateGoaliePoints` (`src/fantasyPoints.py`) --
  now the single goalie scoring source of truth, same discipline as `SKATER_WEIGHTS` (GS 0.75, W
  2.5, L -1, GA -0.5, SV 0.15, SHO 3). `losses` is **regulation-only** (owner-confirmed 2026-07-16:
  the league doesn't record OT/SO losses; use the NHL API `losses` field as-is, never add
  `otLosses`).
- **Data:** contrary to the old "no MoneyPuck" plan, it *does* use MoneyPuck goalie skill stats.
  `data/raw/goalies/*.csv` (MoneyPuck) is merged with NHL API goalie season records
  (`src/moneypuck.py::loadGoalieSeasons` + `src/dataProcessing.py`'s permanent
  `data/raw/goalie_nhl_seasons.csv` cache) into `data/processed/goalie_seasons.csv` by
  `scripts/build_goalie_seasons.py`. Features: `src/features/goalies.py`.
- **Ranker:** `src/models/goalieDraft.py`, wired to `main.py train-goalies`. GATE G3 **failed**
  (XGBoost val Spearman 0.346 beat Baseline A 0.278 but not Baseline B `fp_w3` 0.413), so it ships
  **Baseline B** -- the saved payload is `{'kind': 'baseline_b'}` and `predict()` returns `fp_w3`.
  This is the explicit "ship the baseline" branch of GATE B3/G3, not a failure state. Goalie
  season-over-season predictability is far below skaters' (~0.41 vs ~0.80 val Spearman) because
  workload volatility dominates.
- **Board:** `main.py draft` interleaves goalies with skaters by VORP (first goalie ~#13 overall,
  GATE G4 PASS); missing `goalie_seasons.csv` or an untrained goalie model degrades to skaters-only
  with a printed hint. Goalies are also full keeper candidates on the keeper board.

**FINAL GATE:** run a mock draft against last year's results -- would this board (rankings +
keeper recommendations + goalie table) have beaten the actual 2025 draft? This is the end-to-end
test for the whole campaign, not just Phase D.

Harness shipped 2026-07-20: `src/mockDraft.py`, `main.py mock-draft --year YYYY`.

**The 2025 mock draft IS the one-time test-2024 confirm.** They are not separate items. A board
built for the Oct 2025 draft uses season-2024 features graded on season-2025 outcomes -- exactly
`season.DRAFT_TEST_SEASON`. Running it spends the held-out look permanently, so pre-register the
prediction first (see `fht-quality-gates`) and get owner sign-off. `mockDraft.leakage_warning()`
flags contaminated years in code; 2024 is contaminated by construction (the model trained on
those outcomes) and is only useful for checking the harness.

Rehearsing on 2024 first was what caught three scoring bugs -- goalies graded zero because
`player_seasons.csv` is skaters-only, off-board picks graded zero despite producing, and the mock
board skipping the games-played floors the live board applies. All three inflated the board's
margin. Do not skip the rehearsal.

## Fenced-off wrong paths

- **Random-row train/val/test splits.** Settled: leaks future information into training via
  shared player-seasons or adjacent seasons. Always split by season boundary.
- **Predicting totals instead of PPG.** Settled: totals conflate skill with injury-luck (a great
  player who gets hurt looks bad by total, indistinguishable from a mediocre healthy one).
- **Including rookies in draft v1.** Parked, not forgotten: rookies have no prior-season row to
  build features from, and no junior/AHL data source is wired up. Don't improvise a workaround
  mid-campaign; it's an explicit scope cut.
- **Auto-downloading MoneyPuck.** Forbidden: MoneyPuck's data page redirects automated scrapers
  to a data-license notice (`src/moneypuck.py:1-6`). Refresh is always a manual browser download.
- **Tuning on test-2024 more than once.** Confirm once, then stop -- repeated peeks turn test
  into a second validation set and invalidate the Spearman number you'll report.
- **Summing raw MoneyPuck situation rows** instead of routing through `moneypuckGamePoints` /
  `buildPlayerSeasons`. Double-counts every stat (see GATE B1).
- **Un-parking the LSTM (`src/models/lstmPickups.py`) for this campaign.** Settled: parked until
  after draft season regardless of curiosity: it's a pickup-model artifact, not a draft-model one,
  and XGBoost is the product model for both.

## Validation and promotion

Every gate's numbers (row counts, Spearman/MAE, join hit rates, eyeball verdicts) get recorded in
`PROJECT-PLAN.md`'s Learning Log, and the relevant phase checkbox gets ticked, and the "Current
Phase" section gets updated. The per-session Current-Phase update is **ASSUMED** as a standing
rule -- it comes from a Learning-Log lesson ("the plan doc drifted three phases behind the
code... update Current Phase every session"), not a written policy, and the owner has not
confirmed it (see `.claude/skills/OPEN-QUESTIONS.md` #2). Treat it as current practice. Route the
actual evidence standard (what counts as "recorded," what a gate pass looks like in writing)
through `fht-quality-gates`.

## When NOT to use this skill

- Improving the pickup/cooling models (tuning, new features, Optuna, regression reformulation) --
  that's `PROJECT-PLAN.md` Phase E-ML, a different campaign: `fht-research-frontier`.
- Running commands, managing the venv, refreshing MoneyPuck data, or cache mechanics in general
  (not specific to the player_seasons build above) -> `fht-operations`.
- What "done" means for a change, or how to write/run the relevant tests -> `fht-quality-gates`.
- Hockey/MoneyPuck domain semantics (situation rows, scoring approximations) beyond what's
  restated here for gate context -> `fht-domain-reference`.
- Something is broken and needs root-cause steps (e.g. the failing `loadGameLogs` test) ->
  `fht-debugging-playbook`.
- Module boundaries, the system map, or settled architectural decisions in general ->
  `fht-architecture-contract`.

## Provenance and maintenance

Facts here drift as phases complete. Re-verify with:
- `grep -rn "calculateGoaliePoints" src/` -- **now EXISTS** (shipped 2026-07-16 in
  `src/fantasyPoints.py` alongside `GOALIE_WEIGHTS`); the goalie ranker lives in
  `src/models/goalieDraft.py`.
- `test -f src/keeper.py` (or `ls src/keeper.py`) -- **now EXISTS** (keeper analyzer shipped;
  goalie-inclusive as of 2026-07-16). The Phase C body prose below still reads "does not exist yet"
  and is stale — trust the code and PROJECT-PLAN's Current Phase over that section.
- `ls data/processed/player_seasons.csv` -- **now EXISTS** (B1 done 2026-07-06, built by
  `scripts/build_player_seasons.py`). Also `ls data/raw/player_birthdates.csv` (B2 age cache, built
  by `scripts/build_birthdates.py`) -- both flip back to absent only if deleted for a rebuild.
- `ls data/raw/keepers.csv` -- confirm still absent/empty; flips once B0 is filled in.
- `.\.venv\Scripts\python.exe -m pytest -v` -- as of 2026-07-20: **125 passed, 0 failed**. Both
  long-standing failures were fixed in the July 2026 sustainability pass, so the suite is now a
  real signal: treat any red as a regression, not as expected noise.
- `grep -n "NotImplementedError" main.py src/models/draft.py` -- **no longer raises**:
  `trainDraft`/`runDraft`/`runKeeper` and `models/draft.py`'s four functions are all implemented
  (Phase B3/B4 landed). The Phase B3/B4 body prose still says "raises `NotImplementedError`" and is
  stale.
- Re-read `PROJECT-PLAN.md`'s "Current Phase" section (bottom of file) each session -- it is the
  authoritative statement of where this campaign actually stands, and this skill's phase-by-phase
  structure should track it, not the other way around.
- `.claude/skills/OPEN-QUESTIONS.md` #1 -- if the owner confirms or corrects the "hardest live
  problem" framing, update the `ASSUMED` banner at the top of this file and delete the resolved
  entry from OPEN-QUESTIONS.md.
