---
name: fht-research-frontier
description: Use when improving the pickup or cooling models, tuning hyperparameters, adding predictor features (new model input columns) to the ML pipeline, evaluating whether a proposed model change is a real improvement, deciding what to work on after the draft ships, or feeling tempted to un-park the LSTM or add a new dependency (e.g. optuna).
---

# FHT Research Frontier

This is the after-the-draft, model-improvement layer: open problems where the pickup/cooling
pipeline can advance past its current state, plus the methodology that turns a hunch into an
adopted change here. It does not cover the draft/keeper build itself — see `fht-draft-campaign`,
which has priority until the October 2026 draft.

Every numeric claim below was either verified by reading the named file today or is attributed
to PROJECT-PLAN.md's Learning Log (July 2026 model review) — the Learning Log numbers are the
project's own record, not something re-derived here. Facts tagged **as of 2026-07-05** are
volatile; re-check before relying on them (see Provenance). What "beyond state of the art" means
here is **ASSUMED** per `.claude/skills/OPEN-QUESTIONS.md` #5: not academic SOTA, but beating
this project's own naive baselines on its own product metric — see Methodology (c).

| # | Frontier item | Problem in one line | Effort |
|---|---|---|---|
| 1 | Tune the cooling model | Weakest model (val AUC 0.6425) got zero tuning | Low — port existing search |
| 2 | Trend and deployment features | No delta/PP-TOI features; misses PP1 promotions (Raddysh case) | Medium — new feature code, data on disk |
| 3 | Regress on next-5 FP | Binarized label throws away signal; UI ranks anyway | Medium — new training path |
| 4 | Optuna swap | Random search is sample-inefficient at 20–50 trials | Low — but a dependency change |
| 5 | Parked and gated ideas | Each blocked on a written precondition — check before starting | — |

## Frontier item 1 — Tune the cooling model

**Why current fails:** `src/models/cooling.py` hardcodes `n_estimators=100, max_depth=5,
learning_rate=0.1` (verified, lines 29–34) with no search, while `src/models/pickups.py` runs a
20-iteration `RandomizedSearchCV` over `n_estimators`/`max_depth`/`learning_rate`/`subsample`/
`colsample_bytree` with a `PredefinedSplit` (verified, lines 35–52). Per PROJECT-PLAN's Learning
Log (July 2026), cooling's val AUC is 0.6425 against pickups' 0.7284 (canonical record of
these numbers: `fht-quality-gates`' golden inventory) — the weakest model got zero tuning
effort.

**Asset:** the search harness already exists and works (pickups.py) — this is a port, not new
infrastructure.

**First three steps in this repo:**
1. Copy the `RandomizedSearchCV` + `PredefinedSplit` block from `src/models/pickups.py`
   (lines 35–52) into `src/models/cooling.py`, swapping the label column to `is_cooling_down`.
2. Replace the `n_estimators` grid with early stopping: `n_estimators=2000`,
   `early_stopping_rounds=50` scored against the val fold, so each candidate picks its own tree
   count instead of searching a fixed list (PROJECT-PLAN E-ML item 1).
3. Widen the param space per the plan: `min_child_weight` up to 20–50 (noisy short-horizon
   labels reward heavy regularization), `reg_alpha`, `reg_lambda`, `gamma`, and make
   `learning_rate` log-uniform rather than a three-point grid.

**You have a result when:** cooling's validation AUC is materially above 0.6425 across
expanding-window folds (train ≤2021 → val 2022, train ≤2022 → val 2023; "expanding window"
= the training set grows forward in time and validation is always the next unseen season,
as opposed to a fixed or sliding window — this repo's standard leakage-safe way to validate
across seasons) — not just a single 2023 split, since a single split can overfit the search
itself — with 2025 still held out untouched for the backtest.

## Frontier item 2 — Trend and deployment features

PROJECT-PLAN calls this "the most likely source of real signal," ahead of more tuning.

**Why current fails:** `src/features/mlFeatures.py`'s `buildRollingFeatures` builds rolling
windows (5/10/20 games) but the model only sees raw rolling levels, not deltas — no feature for
"accelerating." The canonical miss is documented in the code: `src/backtest.py`'s
`KNOWN_PICKUPS` dict includes `'Darren Raddysh': 'Hedman injury opened PP1 mid-season, 70P'`
(verified, line 46), and PROJECT-PLAN E-ML item 2 calls a PP1 promotion "the classic breakout
signal the current features miss." Nothing in the feature set represents power-play TOI today.

**Asset:** everything needed is already on disk. MoneyPuck's situation-split rows (including
`5on4`) are retained specifically for this — `src/moneypuck.py`'s `loadGameLogs` keeps all
situation rows rather than collapsing to `'all'` (per the discovery dossier and the module's own
header comments), so PP-TOI features require no new data source, only new feature code.

**First three steps in this repo:**
1. In `src/features/mlFeatures.py`, add explicit trend-delta features: `rolling_5 − rolling_20`
   for `game_fantasy_points` and for `icetime`, alongside the existing rolling columns built by
   `buildRollingFeatures`.
2. Add a `5on4` (power-play) TOI feature sourced from the situation rows already loaded by
   `loadGameLogs`/`loadMoneyPuckData`, plus its own 5-vs-20-game delta, to capture PP1
   promotions like the Raddysh case.
3. For the cooling model specifically, add rolling `xgoals_surplus` (already derived in
   `mlFeatures.py`) and shooting-percentage-vs-career-shooting-percentage as regression-to-mean
   signals — PROJECT-PLAN flags this as the most likely lever for cooling's weaker AUC.

**You have a result when:** `src/backtest.py`'s top-K hit rate for the retrained model beats
both baselines it already prints — the current model's own hit rate and the last-10-FP chaser —
averaged across `DEFAULT_DATES` (five as-of dates spanning 2025-11-01 through 2026-03-01), not
just one favorable date.

## Frontier item 3 — Regress on next-5 FP instead of binarizing

**STATUS: SHIPPED July 6, 2026 (owner-directed).** Both models converted outright to
`XGBRegressor` on `next_5_avg` (no mode flag); consumers convert raw FP/g predictions to 0-1
percentile ranks. Under the corrected spot-check protocol (drafted-by-proxy exemption removed
from `src/backtest.py` the same day, owner decision), regressor and classifier tie at **55% mean
top-15 hit rate** vs ~39% chaser baseline — *equal, not better*, so the "you have a result when"
bar below was not strictly cleared; the owner accepted the conversion for equal ranking power
plus interpretable FP/g output and a continuous target for item 2's feature work. Full numbers
in PROJECT-PLAN.md Learning Log (July 2026, E-ML item 3). The caveat check passed
(`season_avg_so_far` ranks 4th, icetime 1st). The section below is kept for the original
rationale.

**Why current fails:** `buildLabel` in `src/features/mlFeatures.py` computes `next_5_avg` (a
continuous forward-looking average) and then throws away its magnitude, keeping only whether it
crosses the 75th/25th league percentile (`is_heating_up`/`is_cooling_down`). The UI already ranks
players by score, so a continuous target loses nothing and keeps more signal.

Known caveat, which any experiment here must check before declaring victory: the percentile
label may partly learn "is this player already good" rather than "is heating up right now,"
since `season_avg_so_far` is a feature and good players have high season averages and high
future averages. Check whether `season_avg_so_far` dominates
`reports/pickup_feature_importance.png` (regenerated on every `train()` call) before trusting an
AUC or Spearman improvement.

**First three steps in this repo:**
1. Add an `XGBRegressor` training path (new function or a mode flag) in `src/models/pickups.py`
   / `src/models/cooling.py` that fits directly on `next_5_avg` instead of calling
   `buildFeatureMatrix(df, label_col='is_heating_up')`.
2. Score it two ways: Spearman correlation between predicted score and realized `next_5_avg` on
   the validation season, and — primarily — `src/backtest.py`'s top-K hit rate, since that is
   the product metric this project actually cares about (Methodology (c)).
3. Re-run `reports/pickup_feature_importance.png` for the regressor and confirm
   `season_avg_so_far` isn't the whole story; if it is, the "heating up" framing needs a feature
   that isolates recent trend from season-long quality (see item 2).

**You have a result when:** the regression ranker beats the classifier ranker on
`src/backtest.py`'s hit rate — not merely on Spearman or AUC, per the plan's explicit warning
that global AUC alone has already misled this project once (the label-partly-learns-"is-good"
caveat).

## Frontier item 4 — Swap RandomizedSearchCV for Optuna

Cheap and mechanical; do alongside item 1, not instead of it. TPE search is more sample-efficient
than random search at 20–50 trials and gives native log-uniform ranges for `learning_rate`,
removing the need to hand-pick a discrete grid.

**Verified today:** `optuna` does not appear anywhere in `pyproject.toml`'s `dependencies` list
(grepped the full block — no match, **as of 2026-07-05**). Adding it is a real dependency
change, not a code-only one. PROJECT-PLAN's Learning Log records that pin drift has already cost
time once (streamlit was pinned but never actually installed, so the UI skeleton had never run)
— after adding optuna, re-freeze the dependency list from the working venv in the same change.

**First three steps in this repo:**
1. Add `optuna` to `pyproject.toml`'s `dependencies` and install it into `.venv`.
2. Replace `RandomizedSearchCV`/`PredefinedSplit` in `src/models/pickups.py` (and, once ported,
   `cooling.py`) with an Optuna study using the same expanding-window val scoring.
3. Re-freeze the dependency list immediately after installing (Learning Log rule) so the pin
   reflects what's actually importable.

**You have a result when:** the Optuna study reaches an equal-or-better best validation score
than the 20-iteration `RandomizedSearchCV` at the same or lower trial budget, on the same
expanding-window folds used for item 1.

## Frontier item 5 — Parked and gated ideas

Each of these has a written unblock condition; none should be started before its precondition is
met.

- **LSTM (`src/models/lstmPickups.py`):** parked with a July 2026 header comment and a known
  `save(model)` signature bug. Precondition before un-parking: align
  `src/features/lstmFeatures.py` to the canonical `SKATER_WEIGHTS` scoring. Verified today —
  `lstmFeatures.py`'s `loadLSTMData` still computes `game_fantasy_points` as
  `goals*3 + primaryAssists*2 + secondaryAssists*2 + shotsOnGoal*0.15` (lines 37–40): no PPP,
  SHP, hits, blocks, GWG, or +/-. That's the old pre-correction scoring, not
  `src/fantasyPoints.py`'s `SKATER_WEIGHTS`/`moneypuckGamePoints`. Do not touch this before the
  October draft regardless of how tempting a sequence model looks (Methodology (g)).
- **ML-based goalie projection (post-draft only):** what's parked is the eventual ML
  projection for goalies — NOT the non-ML goalie work. Do not confuse the two: writing
  `calculateGoaliePoints` and the last-season goalie ranking table is scheduled,
  milestone-blocking Phase D work due BEFORE the October draft, owned by
  `fht-draft-campaign` — treat that as active, not parked. Precondition for the ML version:
  the non-ML scoring path exists and a draft season of its output has been eyeballed.
  (Verified 2026-07-05: `src/fantasyPoints.py` defines `calculateSkaterPoints` only — no
  `calculateGoaliePoints` yet; the goalie weights (GS, W, L, GA, SV, SHO) live in
  PROJECT-PLAN's League Scoring Rules table with no implementing function.)
- **Schedule context, prospect/callup tracker, PP-unit data, rookie draft projections:** each is
  blocked on a data source that does not exist in this repo (transaction feeds, schedule
  difficulty, PP-unit assignments, junior/AHL stats) — per PROJECT-PLAN's Parked Ideas list.
  These are data-acquisition problems, not modeling problems; do not attempt a modeling workaround
  in place of the missing source.

## Methodology: turning a hunch into an adopted change

These rules are grounded in this project's own incident history (PROJECT-PLAN Learning Log,
July 2026), not generic ML advice.

**(a) Predict the number before running anything.** Write the expected AUC or hit-rate delta
down, in text, in PROJECT-PLAN, before training. A result with no prediction attached can't be
judged as a surprise or a confirmation.

**(b) Baselines go on the scoreboard first.** Settled decision #6: naive baselines (last-10-FP
chaser for pickups; last-season PPG / 3-season weighted PPG for draft) are computed and printed
before any model result is trusted. `src/backtest.py` already prints the last-10-FP baseline and
pool base rate alongside the model's hit rate for this reason.

**(c) The evidence bar is the product metric, not global AUC.** A change is adopted only when it
beats the relevant baseline on the metric that maps to what the tool is actually for:
`src/backtest.py`'s top-K hit rate for pickups, validation Spearman for the draft ranker. Global
AUC has already misled this project once — the percentile label can partly learn "is a good
player" rather than "is heating up" (item 3's caveat), so an AUC gain that doesn't show up in
hit rate is not a result.

**(d) One holdout, touched once.** The 2025 season is the pickup backtest's holdout; test-2024
is the draft model's holdout. Per settled decisions, these are touched once, at the end, after
model selection is finished on train/val splits — never used to pick between candidate models.

**(e) Negative results get recorded, then the idea is retired or parked with a written unblock
condition.** The LSTM is the exemplar: it didn't outperform, it stayed untested through a
signature-rot bug, and rather than deleting or endlessly iterating on it, it was parked with an
explicit condition (align scoring, wait until after the draft) recorded in PROJECT-PLAN.

**(f) Idea lifecycle:** Parked Ideas → numbered item under Phase E-ML → implemented behind the
shared `train(df)`/`predict(df)`/`load()`/`save(model)` module interface (so the UI and CLI never
need to know which model is underneath) → gated against baseline on the product metric → adopted
(retrain, commit the metrics in text, update PROJECT-PLAN) or retired.

**(g) Good ideas here have come from three places, not from adding model complexity:** the July
2026 model review (reading `cooling.py`/`pickups.py` cold and noticing the tuning gap),
`src/backtest.py`'s `KNOWN_PICKUPS` misses (Raddysh/PP1 case), and Learning Log post-mortems. The
LSTM taught the opposite lesson: a more complex architecture, added before simpler features and
tuning were exhausted, produced an untested, buggy, parked module rather than a shipped
improvement.

## When NOT to use this skill

- Building or shipping the draft/keeper analyzers themselves, or anything on the critical path to
  the October 2026 draft — see `fht-draft-campaign`.
- Checking whether a change is allowed to merge (tests, freeze rules, plot-per-model naming,
  other CI-shaped gates) — see `fht-quality-gates`.
- Day-to-day running of the CLI, caches, or Yahoo/NHL API calls — see `fht-operations`.
- Looking up scoring weights, module ownership, or data-model facts (situation rows, GAME_COLUMNS,
  etc.) that this skill assumes as background — see `fht-domain-reference`.
- Diagnosing a specific failing test or bug (e.g. the open `loadGameLogs` cache-guard failure) —
  see `fht-debugging-playbook`.
- Understanding why the codebase is shaped the way it is (module boundaries, the train/predict
  split, why LSTM lives where it does) — see `fht-architecture-contract`.

## Provenance and maintenance

Written 2026-07-05 from a live read of the repo plus PROJECT-PLAN.md's July 2026 Learning Log.
Re-verify before relying on any of these:

- **Cooling still untuned?** Read `src/models/cooling.py` — confirm `n_estimators=100,
  max_depth=5, learning_rate=0.1` are still hardcoded with no search call.
- **Optuna still absent?** Grep `pyproject.toml` for `optuna` — confirm no match, and check the
  venv (`pip show optuna`) in case it was installed without a pin update.
- **LSTM still parked?** Check `src/models/lstmPickups.py` for the parked header and confirm no
  pickups/draft pipeline imports it.
- **lstmFeatures still on old scoring?** Read `loadLSTMData` in `src/features/lstmFeatures.py` —
  confirm `game_fantasy_points` still excludes PPP/SHP/hits/blocks, or has been aligned to
  `SKATER_WEIGHTS` (item-5 precondition satisfied, though still not before the draft).
- **AUCs stale?** 0.7284 (pickup) / 0.6425 (cooling) are July 2026 retrain numbers from the
  Learning Log. If retrained since, pull current numbers from the same log section.
- **calculateGoaliePoints still missing?** Grep `src/fantasyPoints.py` — confirm no goalie
  scoring function exists before treating item 5's goalie gate as still closed.
