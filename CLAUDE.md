# FantasyHockeyTools

Solo ML fantasy-hockey toolkit for a single Yahoo league (`nhl.l.33072`). Three tools:
pickup analyzer (working prototype), draft analyzer (board + goalie ranker shipped),
keeper analyzer (CLI shipped; goalie-inclusive). See PROJECT-PLAN's Current Phase for
remaining work.

## Skill library (read these, don't relitigate them)

This repo's real documentation lives in `.claude/skills/fht-*`, each scoped to a
question shape:

- **fht-architecture-contract** — module boundaries, settled design decisions, system map. Read before adding a module/feature/data source or touching scoring/splits.
- **fht-operations** — env setup, every CLI command, cache/config, season rollover. Read before running or retraining anything.
- **fht-domain-reference** — MoneyPuck columns, situation rows, scoring semantics, hockey/fantasy terms.
- **fht-draft-campaign** — draft/keeper analyzer roadmap (Phase B/C work items).
- **fht-player-summaries** — generating/refreshing the Claude draft summaries (in-session vs API script) and pushing them through `api_export.py` to the frontend. Read before touching `draft_summaries.json` or the summary prompt.
- **fht-quality-gates** — what to test, how to validate a model result is real.
- **fht-debugging-playbook** — known live issues and root-cause steps.
- **fht-research-frontier** — model-improvement ideas, tuning, what NOT to add (e.g. LSTM stays parked).

`.claude/skills/OPEN-QUESTIONS.md` has unresolved assumptions awaiting owner confirmation.

## Quick start

```powershell
uv venv
uv pip install -e .
.\.venv\Scripts\python.exe main.py train-pickups   # trains models/pickups + models/cooling
.\.venv\Scripts\python.exe main.py pickups         # ranked free-agent recommendations
```

**Always invoke `.\.venv\Scripts\python.exe` explicitly** — system `python` on Windows
dev machines may resolve to an unrelated interpreter.

Requires two manual MoneyPuck CSV downloads first (no auto-downloader exists, by
design — MoneyPuck requires a data license for scrapers):
`data/raw/2008_to_2024.csv`, `data/raw/moneypuck_current.csv` from
https://moneypuck.com/data.htm. See `fht-operations` for the full runbook.

## Architecture at a glance

```
MoneyPuck CSVs  -> src/moneypuck.py (all MoneyPuck IO; processed caches are Parquet)
NHL API         -> src/nhlAPI.py, src/dataProcessing.py (identity/birthDate/roster only)
Yahoo API       -> src/yahooAPI.py (optional roster filtering)
                -> src/fantasyPoints.py (SKATER_WEIGHTS + GOALIE_WEIGHTS — scoring source of truth)
                -> src/features/{mlFeatures,pickups,draft,goalies,shared}.py
                -> src/models/{pickups,cooling,draft,goalieDraft,lstmPickups}.py
                -> main.py (CLI: train-pickups, pickups, train-draft, train-goalies, draft, keeper, spot-check, mock-draft)
                -> src/mockDraft.py (end-to-end backtest: would the board have beaten the real draft?)
                -> scripts/ (one-time builds: build_player_seasons.py, build_birthdates.py)
                -> api_export.py (JSON for frontend/) -> frontend/ (Next.js — the only UI)
```

## Load-bearing decisions (do not relitigate without new evidence)

- MoneyPuck is the single stats source for modeling; NHL API is identity/roster only.
  Owner-approved exception: goalie W/L/SO/GS season records come from the NHL API
  (see `docs/superpowers/specs/2026-07-16-goalie-draft-keeper-design.md`).
- One canonical scoring source per stat type: `fantasyPoints.SKATER_WEIGHTS` and
  `fantasyPoints.GOALIE_WEIGHTS` (goalie `losses` are regulation-only, owner-confirmed).
- LSTM (`src/models/lstmPickups.py`) is intentionally parked until after draft season.
- Draft target is next-season fantasy PPG, not totals (avoids conflating skill with injury luck).
- Pickup/cooling models are XGBoost **regressors** on next-5-game FP/g (converted from
  classifiers July 2026); `predict()` returns projected FP/g, and consumers (`main.py`,
  `api_export.py`) convert to 0-1 percentile ranks for the blend and frontend.
- Splits are season-based, never random rows (train `<=2022`, validate `2023`).
- Model `.pkl` files are gitignored — retrain locally; a fresh clone has no trained
  models and must run `train-pickups` before `pickups`/`spot-check`/`api_export.py` work.
- Draft pipeline has two one-time build prerequisites (gitignored outputs, rebuild per
  season): `scripts/build_player_seasons.py` -> `data/processed/player_seasons.csv` (season
  aggregation), and `scripts/build_birthdates.py` -> `data/raw/player_birthdates.csv` (NHL
  API birthDate cache for the age feature — `players_cache.csv` covers only current roster).
  Draft features read these; they do not self-build. See `fht-draft-campaign`.

Full rationale and file:line citations: `fht-architecture-contract`.

## Known issues

- ~~`UnicodeEncodeError` (cp1252) from `src/nhlAPI.py` response previews~~ — fixed July 2026:
  per-request prints are `logger.debug` now, so `PYTHONUTF8=1` is no longer required.
- ~~2 known pre-existing test failures~~ — both fixed July 2026, suite is fully green.
  `loadGameLogs` now serves a valid cache *before* requiring the 2.6 GB source files
  (the guard-ordering bug), and the token-budget test asserted the *smaller* budget in
  contradiction of its own name and of the deliberate `MAX_TOKENS = 16000` change.
- ~~No CI configured~~ — added July 2026: `.github/workflows/ci.yml` runs pytest plus the
  frontend typecheck and unit tests. It must never train a model: `.pkl` files and the
  MoneyPuck CSVs are gitignored, so CI has neither.
- `train-draft` / `draft` / `keeper` / `train-goalies` / `mock-draft` CLI commands are implemented (draft board shipped Phase B4; goalie ranker shipped 2026-07-16; mock-draft backtest 2026-07-20). Remaining Phase B/C/D work is tracked in `fht-draft-campaign` and PROJECT-PLAN's Current Phase.
- **Keeper cost is understated when picks are traded.** The league rule is "keeping a player costs
  your final 4 picks — whichever picks those happen to be" (owner, 2026-07-20), but
  `keeper.KEEPER_ROUNDS = (18, 17, 16, 15)` assumes an untraded draft. Now quantified in VORP:
  rounds 15–18 price at **0** (dead picks), while the owner's real 2025 final four — picks
  70/71/78/90 — were worth +16.8/+16.1/+11.2/+2.2. Still open; see
  `.claude/skills/OPEN-QUESTIONS.md` #1b. Do NOT conflate it with the units bug below, which is
  a different bug and is fixed.
- ~~`net_keeper_value` mixed units~~ — fixed 2026-07-20: it subtracted `round_pick_costs`' mean
  **absolute** `projected_total` from `raw_keeper_value`, a value-over-replacement, so every
  keeper scored ≈−80 to −115 and the board said keep nobody. `round_pick_costs` now returns VORP,
  slices each round by VORP (the board's own sort order), and floors at 0 — forfeiting a pick
  cannot be a gain. Per-round value now falls monotonically +80.2 (rd 1) → 0 (rd 10) → −25.0 (rd 18).
- **The draft board does not beat hand-drafting.** The 2025 mock draft (the one held-out look,
  now spent) came out at −1.75% over 14 picks — inconclusive. Treat the board as a consistent
  second opinion, not an authority. See `docs/superpowers/plans/2026-07-20-draft-validation-handoff.md`.
- ~~The board drafted 0 centers in 140 picks~~ — fixed 2026-07-20: `MAX_BY_POSITION` capped
  positions but set no **floors**, so a VORP-greedy board produced rosters that could not be
  legally fielded, and `grade()` summed all 14 picks with no legality check. `mockDraft` now
  reserves the tail of the draft for unfilled starting slots (keeper-aware on both floors and
  caps) and reports `lineup_fp` alongside `total_fp`. Replacement ranks are also demand-aware
  (`10 × slots − keepers at that position`). 2025 sweep went −6.48% → −2.84% (all-picks) with all
  10 rosters legal, up from 0 of 10 — directional only, the held-out look was already spent.
- ~~Season constants duplicated across files~~ — fixed July 2026: `src/season.py` owns `CURRENT_SEASON` and derives every split boundary, spot-check date, season label and headshot season id from it. Rollover is a one-line edit there, and `tests/test_season.py` pins the derived values so a silent shift fails loudly. `backtest.KNOWN_PICKUPS` still needs hand re-curation each season — it cannot be derived.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

`pytest.ini` (not `pyproject.toml`'s `[tool.pytest.ini_options]`) is the config
pytest actually reads — it wins when both exist.
