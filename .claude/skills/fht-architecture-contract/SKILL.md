---
name: fht-architecture-contract
description: Use when about to add a module, product feature, or data source; when changing scoring, features, or train/test splits; when unsure where new logic belongs in the pipeline; or when tempted to relitigate a settled decision (MoneyPuck as stats source, single scoring function, LSTM parked, PPG draft target, season-based splits, no auto-downloader).
---

# FHT architecture contract

This is a solo ML fantasy-hockey toolkit (Yahoo league nhl.l.33072) with three tools: pickup
analyzer (working prototype), draft analyzer (Phase B, in progress), keeper analyzer (Phase C,
not started). Read this before touching scoring, features, splits, or module boundaries.

## 1. System map (as of 2026-07-05)

```
DATA SOURCES                      MODULES                              ENTRY POINTS
MoneyPuck CSVs (manual DL)  ---->  src/moneypuck.py (all MoneyPuck IO)
  data/raw/2008_to_2024.csv        src/fantasyPoints.py (SKATER_WEIGHTS,
  data/raw/moneypuck_current.csv     canonical scoring)          ---->  main.py (argparse CLI:
                                    src/features/mlFeatures.py           train-pickups, pickups,
NHL API (api-web.nhle.com)  ---->  src/nhlAPI.py (raw calls)             train-draft, draft,
  identity/birthDate/roster        src/dataProcessing.py (fetch/cache)   spot-check)
                                    src/keepers.py (keepers.csv IO)
Yahoo Fantasy API           ---->  src/yahooAPI.py (OAuth, roster)  ---->  api_export.py (JSON
                                    src/backtest.py (spot-check)            for frontend/)
                                    src/features/{shared,pickups,     ---->  ui/ (Streamlit,
                                      draft}.py (feature building)         mostly stub)
                                    src/models/{pickups,cooling,      ---->  frontend/ (Next.js,
                                      draft,lstmPickups}.py (train/          reads frontend_data.json)
                                      predict/load/save)
```

Working product: `src/moneypuck.py`, `src/fantasyPoints.py`, `src/features/mlFeatures.py`,
`src/models/pickups.py`, `src/models/cooling.py`, `src/backtest.py`, `main.py:runPickups`,
`src/features/pickups.py::rankFreeAgents` (`src/features/pickups.py:24-36`), `ui/app.py` (title
page only).

Stubs — raise `NotImplementedError` or are TODO-only, verified by reading each file:
- `src/features/shared.py:15-21` (`build_shared_features`)
- `src/features/pickups.py:15-22` (`build_pickup_features`)
- `src/models/draft.py:15-41` (`train`, `predict`, `load`, `save` — all four)
- `main.py:127-132` (`trainDraft`), `main.py:135-149` (`runDraft`)
- `ui/pages/pickups.py` and `ui/pages/draft.py` — comment-only TODO lists, no logic
- `src/features/draft.py` (`build_draft_features`) is WIP, not a stub: it builds position
  one-hots, `career_games`, `PP_share`, `hitblock_share` from `buildPlayerSeasons`, but has no
  trajectory/age/target features yet (Phase B2 remainder).
- `src/models/lstmPickups.py` — intentionally parked (see decisions table), not broken.

## 2. Load-bearing decisions

Each traces to `PROJECT-PLAN.md` "Design Decisions Going Forward" (lines 59-85) or a code
comment documenting an incident. Do not relitigate without new evidence.

| Decision | Rationale (verified) |
|---|---|
| MoneyPuck is the single stats source for modeling; NHL API only for identity/`birthDate`/`positionCode`/rosters | `PROJECT-PLAN.md:61-64`; removes duplicated fantasy-point logic and the 700-request threaded stats fetch |
| One canonical scoring function, `fantasyPoints.SKATER_WEIGHTS` (`src/fantasyPoints.py:1-14`) | Header comment states it is "the single source of truth." Incident: the ML label silently diverged to G/A/SOG-only for months before this was enforced (see `PROJECT-PLAN.md` Learning Log) — the fix was one dict + tests, not scattered constants |
| LSTM parked; XGBoost is the product model | `PROJECT-PLAN.md:68-70`; `src/models/lstmPickups.py` header dated July 2026 says keep parked until after draft season |
| Train/predict CLI split (`train-pickups`/`pickups`/`train-draft`/`draft`) | `PROJECT-PLAN.md:77`; `main.py:152-173` — Streamlit is meant to be the product interface, scripts are the workbench |
| Model modules share `train(df)`/`predict(df)`/`load()`/`save(model)` | Stated verbatim in `src/models/draft.py:1-8`; implemented identically in `src/models/pickups.py` and `src/models/cooling.py` |
| Draft target = next-season fantasy PPG, not totals | `PROJECT-PLAN.md:71-72`: totals conflate skill with injury luck; display as `PPG x 78` |
| Splits are season-based, never random rows | `src/backtest.py:1-8` comment: model trains on `<=2022`, validates `2023`; every rolling feature only looks backward so features can be built once and sliced by date without leakage |
| Spearman is the primary metric; baselines before models | `PROJECT-PLAN.md:73-76` |
| No MoneyPuck auto-downloader | `src/moneypuck.py:1-6`: MoneyPuck requires a data license for scrapers; refresh is a manual browser download from moneypuck.com/data.htm |

## 3. Invariants (checkable rules)

- **Situation rows.** MoneyPuck game logs carry one row per player-game per game "situation"
  (`all`, `5on4`, `4on5`, ...). `buildPlayerSeasons` and `moneypuckGamePoints` require ALL
  situation rows as input — the `'all'` row already totals the situation-specific rows, so
  summing raw rows yourself double-counts every stat (`src/moneypuck.py:98-102`,
  `src/fantasyPoints.py:31-36`).
- **No leakage in rolling features.** Every rolling/expanding feature in
  `buildRollingFeatures` must only look backward. `season_avg_so_far` is
  `shift(1).expanding().mean()` (`src/features/mlFeatures.py:37-40`) — preserve the `shift(1)`
  in any new feature of this kind.
- **Labels come from the future only.** `buildLabel` computes `next_5_avg` via a
  reverse-rolling-then-shift trick over *future* games (`src/features/mlFeatures.py:45`), then
  ranks it as a percentile within season across the league (not self-relative — a self-relative
  threshold let shot-blocking defensemen trigger "heating up" on ordinary noise; see the comment
  at `src/features/mlFeatures.py:46-50`).
- **Scoring weights come from one place.** Anything computing fantasy points must read
  `fantasyPoints.SKATER_WEIGHTS`, never a local copy. Two scoring paths exist and are expected
  to differ slightly: `calculateSkaterPoints` (NHL-API path, `src/fantasyPoints.py:17-26`) and
  `moneypuckGamePoints` (MoneyPuck path, `src/fantasyPoints.py:29-57`).
- **Caches are gitignored, not committed.** `data/**/*.csv`, `data/processed/*.json`, and
  `models/**/*.pkl` are all in `.gitignore` (`.gitignore:25-26,39`). The `.pkl` line's comment
  is "retrain locally" — this **contradicts** the stale `PROJECT-PLAN.md:82-83` claim that
  "model binaries stay committed." `.gitignore`/reality wins: a fresh clone has no trained
  models and must run `train-pickups` before `pickups` works.

## 4. Known weak points

| Issue | Location |
|---|---|
| Season constants duplicated across entry points | Three copies of the season id (`main.py`, `api_export.py`, `src/backtest.py`) plus two hardcoded `20252026` literals. The authoritative file:line catalog — and the annual-rollover checklist that maintains it — lives in `fht-operations`' constants catalog; don't maintain a second copy here. |
| `latestGameState()` duplicated | `main.py:36-66` and `api_export.py:28-49` — identical cache/compute logic, two copies |
| NHL-API scoring path omits hits/blocks | `calculateSkaterPoints` (`src/fantasyPoints.py:17-26`) has no `hits`/`blocks` terms because the NHL landing endpoint doesn't return them; `moneypuckGamePoints` does include them. The heuristic (`rankFreeAgents`) and ML score are therefore on different scales and are only blended after each is independently normalized (`main.py:108-112`, `api_export.py:99-102`) |
| No CI | Verified: no `.github/workflows/`, no CI config in the repo |
| Test suite fails on `main` | `.\.venv\Scripts\python.exe -m pytest -v` → 4 passed, 1 failed (verified 2026-07-05): `tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations`. Root cause is a guard ordering bug in `src/moneypuck.py::loadGameLogs` (raises `FileNotFoundError` at line 76 before the cache-hit check at lines 80-83). See `fht-debugging-playbook` for the full analysis — do not re-diagnose here. |
| Goalies have no scoring path | No goalie weights or function exist in `src/fantasyPoints.py`; `rankFreeAgents` explicitly filters goalies out (`src/features/pickups.py:32`) |

## When NOT to use this skill

- Running commands, setting up the venv, refreshing MoneyPuck data, or managing caches ->
  `fht-operations`.
- Hockey/scoring/MoneyPuck domain semantics (what a "situation" column means in fantasy terms,
  league rule specifics) beyond the invariants above -> `fht-domain-reference`.
- How a change gets validated (which tests to add, what "done" means) -> `fht-quality-gates`.
- Something is broken and you need root-cause steps (e.g. the failing test above) ->
  `fht-debugging-playbook`.
- Executing Phase B (draft ranker) or Phase C (keeper analyzer) work items ->
  `fht-draft-campaign`.
- Ideas for improving model performance (feature ideas, tuning, architecture changes) ->
  `fht-research-frontier`.

## Provenance and maintenance

Facts here drift. Re-verify with:
- `pytest`: `.\.venv\Scripts\python.exe -m pytest -v` (repo root) — confirm pass/fail counts still match "4 passed, 1 failed."
- `CURRENT_SEASON`/season-string duplication: `grep -rn "CURRENT_SEASON = 2025\|20252026" main.py api_export.py src/backtest.py src/dataProcessing.py`.
- `.gitignore` model-binary line: `grep -n "models" .gitignore` — confirm `models/**/*.pkl` still present and still contradicts `PROJECT-PLAN.md`'s decision 9.
- Stub status: `grep -rn "NotImplementedError" src/features/shared.py src/features/pickups.py src/models/draft.py main.py` — confirm the same functions still raise.
- Settled decisions text: re-read `PROJECT-PLAN.md` lines 59-85 ("Design Decisions Going Forward") in case the owner amends them.
- `ASSUMED` labels: this skill makes none directly, but see `.claude/skills/OPEN-QUESTIONS.md` for unresolved audience/priority assumptions that other sibling skills carry.
