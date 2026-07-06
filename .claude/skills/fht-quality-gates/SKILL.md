---
name: fht-quality-gates
description: Use when about to change scoring/label/domain constants, ML feature or train/val split logic, a model/hyperparameter, or a dependency; when about to commit; when deciding whether a model result is real or a fluke; when adding a test; or when tempted to skip a baseline or peek at the held-out season.
---

# FHT quality gates

This repo is a solo ML side project with no CI and no reviewer. The gate is you, before you
commit. Each class of change below has its own bar — apply the one that matches, not the
loosest one you can argue for.

## 1. Change classification — gate before it lands

| Class | Examples | Gate | Incident behind the rule |
|---|---|---|---|
| **(a) Scoring / label / domain constants** | `SKATER_WEIGHTS` in `src/fantasyPoints.py`, anything feeding `buildLabel` in `src/features/mlFeatures.py` | Highest bar. Update `tests/test_fantasyPoints.py` **first**, watch it fail, then change code. Re-run the season-level acceptance check (2023-24 through the pipeline: Matthews 69G/38A exact, McDavid 32G/100A exact) before trusting anything downstream. | The ML label silently ran on G/A/SOG-only for months because no test pinned the weights (commits 83e9fc1, 2c23433; acceptance numbers recorded in PROJECT-PLAN.md A2, "Acceptance check (passed)"). |
| **(b) Feature / split changes** | anything in `src/features/mlFeatures.py`, `src/features/draft.py` | Leakage review (leakage = information from the future, or from the evaluation season, reaching the training features or the trained model): splits **by season only**, never random rows (train ≤2022 → val 2023 for pickups; train ≤2021 → val 2022+2023 → test 2024 for draft, per PROJECT-PLAN "Design Decisions" #6 and Phase B3). Every feature must look backward only — verify `season_avg_so_far` in `mlFeatures.py:37-39` is still `x.shift(1).expanding().mean()` (shift(1) is the leakage guard; do not remove it). Label (`buildLabel`) must only read future games (`next_5_avg`, a forward window) — never let a feature and the label share a game row. | League-percentile relabeling itself was a leakage-adjacent correctness fix, done in PR #1 (see `src/features/mlFeatures.py` `buildLabel` rationale comment) — self-relative labels let noisy shot-blocking defensemen trigger "heating up" on nothing. |
| **(c) Model / hyperparameter changes** | `src/models/pickups.py`, `src/models/cooling.py`, `src/models/draft.py` | Must beat the recorded baseline (see #2) before a new model replaces a saved one. Record the metric in **text** — PROJECT-PLAN.md Learning Log or a commit message — never only in a `reports/*.png` plot. | Plot-collision: cooling trained after pickups and overwrote `roc_curve.png`, so the file labeled "Pickup Model AUC 0.64" was actually the cooling curve — the real old pickup AUC is unrecoverable (PROJECT-PLAN.md Learning Log, July 2026; fix was per-model filenames, commit 94c59ce). |
| **(d) Pipeline / IO changes** | `main.py`, `src/moneypuck.py`, `src/dataProcessing.py`, `api_export.py` | Run `pytest` plus the cheapest available end-to-end smoke (`python main.py --help`, or `import main` to catch import-time breaks) before committing. | PRs #1 and #2 (bb9bf9d, baa1ab1) both landed without running pytest — bb9bf9d itself broke `tests/test_moneypuck.py`, and PR #2 merged on top without catching it (see Incident 6 below, and `fht-debugging-playbook`). |
| **(e) Stubs / docs / UI** | `ui/pages/*.py` TODO stubs, README, this skill library | Light gate, but update PROJECT-PLAN.md's "Current Phase" section every session (ASSUMED as a standing rule — see §5). | Plan drifted three phases behind the code by the July 2026 review (PROJECT-PLAN.md Learning Log, "The plan doc drifted three phases behind the code"). |
| **(f) Dependency changes** | adding/removing a package in `pyproject.toml` (e.g. optuna, per `fht-research-frontier` item 4) | Install into `.venv`, then freeze the pins (`requirements.txt` + pyproject) **in the same change**; verify `.\.venv\Scripts\python.exe -c "import main"` still succeeds before committing. | requirements.txt drifted from the venv: streamlit was pinned but never actually installed, so the UI skeleton had silently never run (PROJECT-PLAN.md Learning Log, July 2026; fixed in 94c59ce). |

Rule of thumb: the closer a change sits to "what score does a player get" or "what season did
this row come from," the higher the bar. UI copy and doc edits never get to skip the phase-log
update.

## 2. Evidence standards — what counts as proof here

- **Baselines before models, always** (PROJECT-PLAN.md "Design Decisions" #6). Draft: last-season
  PPG and 3-season weighted PPG must be on the scoreboard before XGBoost/Ridge get credit,
  scored on Spearman rank correlation (primary) with MAE (secondary) — PROJECT-PLAN.md #5.
  Pickups: `src/backtest.py`'s top-K free-agent hit rate against the last-10-FP chaser baseline
  and the ~25%-by-construction pool base rate (`src/backtest.py:111-112`) — this is the product
  metric. Global AUC is a training-time diagnostic, not the acceptance metric.
- **Held-out season touched once.** Draft test season is 2024 (PROJECT-PLAN.md Phase B3); pickup
  backtest replays 2025-26 (`SEASON = 2025` in `src/backtest.py:24`) at fixed dates
  (`DEFAULT_DATES`, `src/backtest.py:25`). Re-running against the test season to "see how we did"
  and then tuning against what you saw burns the one held-out look.
- **The eyeball gate is real.** "If the top-20 looks wrong, it is wrong — debug features before
  trusting metrics" (PROJECT-PLAN.md Phase B4, sanity-check bullet). A high Spearman score with
  a 38-year-old on one lucky season sitting in the top 20 is a bug, not a result.
- **`KNOWN_PICKUPS` in `src/backtest.py:38`** (10 consensus 2025-26 waiver-wire gems — Schmaltz,
  Gauthier, Schaefer, Sennecke, Malkin, Zegras, Nelson, Raddysh, Mantha, McCann) is the
  qualitative golden list: if a pickup model buries all ten, distrust the AUC before trusting it.

## 3. Certified / golden inventory (verified 2026-07-05)

- `pytest -v` today: **6 passed, 1 failed** in `tests/` (July 6, 2026: added
  `tests/test_mlFeatures.py` — 2 tests pinning `buildLabel`'s `next_5_avg` target). The failure is
  `tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations` — a live,
  known issue (Incident 6 below). **Do not "fix" this test to match the code** without reading
  the analysis in `fht-debugging-playbook` first — the test encodes the intended cache contract,
  and the code is what broke it.
- Recorded model numbers (July 6, 2026 regression conversion — E-ML item 3, PROJECT-PLAN.md
  Learning Log): both models are now `XGBRegressor` on `next_5_avg`. Pickup val Spearman
  **0.6214**, AUC-equivalent vs `is_heating_up` **0.8465**; cooling val Spearman 0.6063,
  AUC-equivalent 0.7673. Spot-check numbers under the July 6 protocol (drafted-by-proxy
  exemption removed AND pseudo-simulation added to `src/backtest.py` — top-5 recommendations
  per date are removed from later pools, model and chaser shrinking their own pools
  independently): per-date top-15 hit rates **67/60/47/53/47 (mean 55%)**; the 25 simulated
  adds hit **60%** with **2.83 FP/g** avg realized next-5, vs chaser 40% / 2.35 FP/g. The old
  classifier under the same protocol: top-15 mean 52%, adds 60% / 2.84 FP/g — a dead heat; the
  conversion was adopted for equal ranking power plus interpretable FP/g output. These are the
  numbers any new model/hyperparameter change (class (c) above) has to beat. (The July 3
  classifier numbers — 0.7284/0.6425 — were first superseded by a same-day classifier retrain
  on newer data: 0.8517/0.7715.)
- A2 scoring acceptance check (PROJECT-PLAN.md, section A2): 2023-24 season through the pipeline —
  Matthews 69G/38A exact, McDavid 32G/100A exact, McDavid PPP 42 vs official 44 (documented 5on3
  undercount, accepted).

## 4. Testing doctrine (settled)

- pytest is for **pure functions only**: scoring math (`fantasyPoints.py`), aggregation
  (`buildPlayerSeasons`), label construction (`buildLabel`). No tests for API wrappers
  (PROJECT-PLAN.md "Design Decisions" #8) — `nhlAPI.py`, `yahooAPI.py`, `dataProcessing.py`'s
  network calls are explicitly out of scope for pytest.
- TDD is practiced here: PROJECT-PLAN.md Phase A3 records tests written and watched fail before
  the fix landed.
- To add a test: put it in `tests/`, follow `tests/test_fantasyPoints.py`'s style — hand-computed
  expected values in a comment above the assertion (e.g. `test_moneypuck_game_points_with_special_teams`
  spells out `FP = 3*1 + 2*(1+1) + 0.15*4 + ... = 11.25` before asserting it).
- Config: `pytest.ini` sets `pythonpath = .` and `testpaths = tests`. `pyproject.toml` also has a
  `[tool.pytest.ini_options]` block, but `pytest.ini` wins — verified today, pytest prints
  `configfile: pytest.ini (WARNING: ignoring pytest config in pyproject.toml!)`. Don't edit the
  pyproject block expecting it to take effect.
- Run it: `.\.venv\Scripts\python.exe -m pytest -v` — VERIFIED 2026-07-05, output: **4 passed, 1
  failed in 0.58s** (times vary by run; count does not).

## 5. Repo hygiene gates

- Never commit: data files (`data/` is gitignored wholesale), model binaries
  (`models/**/*.pkl` is gitignored, "retrain locally" — repo reality supersedes the stale
  PROJECT-PLAN.md Design Decision #9; the full contradiction analysis lives in
  `fht-architecture-contract`), or credentials (`.env`, `oauth2.json` — both gitignored,
  verified `git ls-files .env oauth2.json` returns nothing). Never quote the contents of
  `.env` or `oauth2.json` in any skill or commit.
- `reports/` is gitignored; plots go there with model-prefixed filenames (e.g.
  `pickup_roc_curve.png`, not `roc_curve.png`) — this is the direct fix for the plot-collision
  incident (#3 above).
- Freeze `requirements.txt`/pyproject pins after any install. Streamlit was pinned but never
  actually installed for a stretch — the UI skeleton had silently never run
  (PROJECT-PLAN.md Learning Log, July 2026).
- Update PROJECT-PLAN.md's "Current Phase" section every session. ASSUMED as a standing rule —
  it is stated as a lesson-learned, not written as a policy anywhere; see
  `.claude/skills/OPEN-QUESTIONS.md` #2 for the caveat.

## 6. Settled decisions — do not relitigate without new evidence

From PROJECT-PLAN.md "Design Decisions Going Forward" (10 items, section starts line 59):
MoneyPuck is the single stats source for modeling (NHL API only for identity/rosters/birthDate);
one canonical scoring function shared by heuristic and ML label; LSTM parked (marginal over
XGBoost, not needed for October goal — `src/models/lstmPickups.py` header comment); draft target
is next-season fantasy **PPG**, not totals; Spearman primary / MAE secondary; baselines before
models, always; train/predict CLI split (`main.py` subcommands); pytest for pure functions only;
repo hygiene (plots→`reports/`, big CSVs local-only — note #9's binary-commit clause is
superseded, see §5); scope simplification (no injury feeds / schedule-strength / prospect tracker
before the three core tools work).

Plus two decisions outside that numbered list: the league-percentile label in `buildLabel`
(`src/features/mlFeatures.py`, rationale comment inline, changed in PR #1 — self-relative
percentiles let noisy shot-blocking defensemen trigger false positives); and no auto-downloader
for MoneyPuck (data-license notice on their site blocks scraping — `checkCurrentFreshness()` nags
instead, `src/moneypuck.py`).

Reopen one of these only with a specific new failure or a measured result that beats the recorded
baseline — not "this feels dated."

## When NOT to use this skill

- Diagnosing *why* something is failing (e.g. the live pytest failure's root cause) →
  `fht-debugging-playbook`.
- How to actually run a command (`train-pickups`, `spot-check`, Streamlit) → `fht-operations`.
- Why an architectural choice was made, module boundaries, IO ownership → `fht-architecture-contract`.
- League rules, scoring formula derivation, MoneyPuck column semantics → `fht-domain-reference`.
- Draft-season roadmap and phase sequencing → `fht-draft-campaign`.
- Ideas beyond the current roadmap (parked features, V2 concepts) → `fht-research-frontier`.

## Provenance and maintenance

- Re-verify the pytest count with `.\.venv\Scripts\python.exe -m pytest -v` — this file states
  4 passed / 1 failed as of 2026-07-05; if that has changed, update this file and check whether
  Incident 6 (`fht-debugging-playbook`) was actually resolved.
- Re-check `.gitignore` for `models/**/*.pkl` and PROJECT-PLAN.md Design Decision #9 before citing
  the binaries-are-gitignored claim — these have already contradicted each other once.
- Re-read PROJECT-PLAN.md's "Current Phase" section (bottom of file) each session; the phase name
  cited in §6 (Phase B, "Draft Analyzer") is a snapshot dated 2026-07-05 and drifts by design.
- If `src/backtest.py`'s baseline print strings, `DEFAULT_DATES`, or `KNOWN_PICKUPS` change,
  re-grep `src/backtest.py` and update §2/§3 to match.
