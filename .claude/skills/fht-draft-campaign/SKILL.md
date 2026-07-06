---
name: fht-draft-campaign
description: Use when working on the draft analyzer or keeper analyzer (PROJECT-PLAN.md Phases B, C, D) -- the player_seasons table, draft features, baselines vs. models, draft_rankings.csv, replacement-value keeper math, or the draft-day Streamlit board and goalie ranking ahead of the October 2026 draft.
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

`buildPlayerSeasons` already exists and reads clean (`src/moneypuck.py:95-136`, landed in PR #2 /
baa1ab1) but has **never been cached or acceptance-checked** -- verify by absence:
`data/processed/player_seasons.csv` does not exist (confirmed today; only
`data/processed/moneypuck_games_2020.csv` is present, 159 MB).

Target build (do not run casually -- reads the 2.6 GB history file; expect a LONG first build):
```python
from src import moneypuck
df = moneypuck.loadGameLogs(min_season=2008)   # NOT the loadGameLogs default (2020) --
                                                 # the draft plan trains on full 2008-2024 history
seasons = moneypuck.buildPlayerSeasons(df)
seasons.to_csv('data/processed/player_seasons.csv', index=False)  # buildPlayerSeasons does NOT
                                                                    # cache itself -- this line
                                                                    # doesn't exist anywhere yet
```
`min_season=2008` also means `loadGameLogs` writes a *new* cache file,
`data/processed/moneypuck_games_2008.csv`, distinct from the existing `..._2020.csv` -- the first
run re-reads the full 2.6 GB file regardless of the 2020 cache's presence.

**GATE B1:** 2008-2024 is 17 seasons + the current season (2025) = 18 seasons. Expect row count
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

`src/features/draft.py::build_draft_features` is WIP (verified by reading it today): it already
builds position one-hots (`pd.get_dummies`), `career_games` (cumsum of `gamesPlayed` per player),
`PP_share` (`totalPPP / totalFP`), and `hitblock_share`. Remaining, per `PROJECT-PLAN.md` B2
(lines 178-187):

- 3-season weighted FP/game (e.g. 50/30/20) and season-over-season delta.
- Regression-to-mean signal: prior-season `xGoalsSurplus` (already computed in
  `buildPlayerSeasons`, `src/moneypuck.py:131`, as `totalGoals - totalXGoals`) -- positive means
  the player ran hot on shooting luck and is more likely to regress down, not up.
- Age at season start: join `data/raw/players_cache.csv::birthDate` (column confirmed present,
  format `YYYY-MM-DD`). **Decision point:** `players_cache.csv` only holds *current* rosters
  (168 KB, ~900 rows, refreshed by the NHL API pipeline), so pre-2015-ish seasons' players --
  especially retired ones -- will not join. This can't be resolved without `player_seasons.csv`
  existing first (Phase B1), so measure the actual join hit rate once you have it:
  ```python
  import pandas as pd
  seasons = pd.read_csv('data/processed/player_seasons.csv')
  cache = pd.read_csv('data/raw/players_cache.csv')
  hit_rate = seasons['playerId'].isin(cache['id']).mean()
  ```
  `PROJECT-PLAN.md:184-185` says "derive or drop -- decide when you see the join hit rate." Don't
  pre-decide; look at the number first.
- Shift the target: each feature row must predict the **next** season's FP/game, not its own.

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

`ui/pages/draft.py` is a comment-only TODO stub today (confirmed by reading it) -- title +
markdown line, then five `# TODO` comments, no logic. Target: Streamlit board loading
`draft_rankings.csv`, sortable, position filter, "mark as drafted" checkboxes backed by
`st.session_state` so the board survives Streamlit's rerun-on-interaction model during a live
draft, plus a best-available-by-position panel. `ui/pages/keeper.py` does not exist yet either
(confirmed) -- planned as your roster with keeper values, top 4 highlighted.

**Goalies v1 = NO ML.** Rank by last-season fantasy points via a `calculateGoaliePoints`
function -- **verified absent today**: `grep -rn "calculateGoaliePoints" **/*.py` finds nothing;
`src/fantasyPoints.py` currently defines only `SKATER_WEIGHTS`, `calculateSkaterPoints`, and
`moneypuckGamePoints`. This needs to be written from scratch using the goalie weights table
already recorded at `PROJECT-PLAN.md:306-314`:

| Stat | Value |
|---|---|
| Games Started (GS) | 0.75 |
| Wins (W) | 2.5 |
| Losses (L) | -1 |
| Goals Against (GA) | -0.5 |
| Saves (SV) | 0.15 |
| Shutouts (SHO) | 3 |

Source the stats from the NHL API landing endpoint (`src/nhlAPI.py`, `/player/{id}/landing`),
mirroring the identity/roster role NHL API already plays elsewhere in this pipeline (MoneyPuck
stays the skater-modeling source; goalies v1 doesn't need MoneyPuck at all since there's no ML
here). Label the output "last season, not a projection" -- do not imply it's forward-looking.

**FINAL GATE:** run a mock draft against last year's results -- would this board (rankings +
keeper recommendations + goalie table) have beaten the actual 2025 draft? This is the end-to-end
test for the whole campaign, not just Phase D.

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
- `grep -rn "calculateGoaliePoints" src/` -- confirm still absent; flips when Phase D's goalie
  scoring is written.
- `test -f src/keeper.py` (or `ls src/keeper.py`) -- confirm still absent; flips when Phase C
  starts.
- `ls data/processed/player_seasons.csv` -- confirm still absent; flips when Phase B1 is built.
- `ls data/raw/keepers.csv` -- confirm still absent/empty; flips once B0 is filled in.
- `.\.venv\Scripts\python.exe -m pytest -v` -- confirm still "4 passed, 1 failed"; flips if the
  `loadGameLogs` guard-ordering bug is fixed.
- `grep -n "NotImplementedError" main.py src/models/draft.py` -- confirm `trainDraft`/`runDraft`
  and `models/draft.py`'s four functions still raise; flips as Phase B3/B4 land.
- Re-read `PROJECT-PLAN.md`'s "Current Phase" section (bottom of file) each session -- it is the
  authoritative statement of where this campaign actually stands, and this skill's phase-by-phase
  structure should track it, not the other way around.
- `.claude/skills/OPEN-QUESTIONS.md` #1 -- if the owner confirms or corrects the "hardest live
  problem" framing, update the `ASSUMED` banner at the top of this file and delete the resolved
  entry from OPEN-QUESTIONS.md.
