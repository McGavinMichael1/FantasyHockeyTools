# FantasyHockeyTools

Solo ML fantasy-hockey toolkit for a single Yahoo league (`nhl.l.33072`). Three tools:
pickup analyzer (working prototype), draft analyzer (Phase B, in progress), keeper
analyzer (Phase C, not started).

## Skill library (read these, don't relitigate them)

This repo's real documentation lives in `.claude/skills/fht-*`, each scoped to a
question shape:

- **fht-architecture-contract** — module boundaries, settled design decisions, system map. Read before adding a module/feature/data source or touching scoring/splits.
- **fht-operations** — env setup, every CLI command, cache/config, season rollover. Read before running or retraining anything.
- **fht-domain-reference** — MoneyPuck columns, situation rows, scoring semantics, hockey/fantasy terms.
- **fht-draft-campaign** — draft/keeper analyzer roadmap (Phase B/C work items).
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
MoneyPuck CSVs  -> src/moneypuck.py (all MoneyPuck IO)
NHL API         -> src/nhlAPI.py, src/dataProcessing.py (identity/birthDate/roster only)
Yahoo API       -> src/yahooAPI.py (optional roster filtering)
                -> src/fantasyPoints.py (SKATER_WEIGHTS — single scoring source of truth)
                -> src/features/{mlFeatures,pickups,draft,shared}.py
                -> src/models/{pickups,cooling,draft,lstmPickups}.py
                -> main.py (CLI: train-pickups, pickups, train-draft, draft, spot-check)
                -> scripts/ (one-time builds: build_player_seasons.py, build_birthdates.py)
                -> api_export.py (JSON for frontend/) -> frontend/ (Next.js) and ui/ (Streamlit, mostly stub)
```

## Load-bearing decisions (do not relitigate without new evidence)

- MoneyPuck is the single stats source for modeling; NHL API is identity/roster only.
- One canonical scoring function: `fantasyPoints.SKATER_WEIGHTS`.
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

- `main.py pickups` / `api_export.py` crash with `UnicodeEncodeError` (cp1252) on Windows
  consoles when the NHL API caches rebuild — `src/nhlAPI.py` prints response previews
  containing non-ASCII player names. Workaround: `$env:PYTHONUTF8='1'` before running.
- Test suite currently has 1 known failure: `tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations` (guard-ordering bug in `src/moneypuck.py::loadGameLogs`). See `fht-debugging-playbook`.
- No CI configured.
- `train-draft` / `draft` CLI commands are stubs (`raise NotImplementedError`) — Phase B is in progress, see `fht-draft-campaign`.
- Season constants (`CURRENT_SEASON`, `20252026` literals) are duplicated across `main.py`, `api_export.py`, `src/backtest.py`, `src/dataProcessing.py` — must be bumped in every location each season rollover.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

`pytest.ini` (not `pyproject.toml`'s `[tool.pytest.ini_options]`) is the config
pytest actually reads — it wins when both exist.
