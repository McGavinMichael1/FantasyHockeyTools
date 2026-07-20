---
name: fht-operations
description: Use when setting up this repo's environment from scratch, running or retraining the pickup/cooling/draft models, hitting a missing-file or FileNotFoundError for model.pkl or a MoneyPuck CSV, dealing with stale-data warnings or cache confusion, rolling the season constants over each year, or launching the Next.js frontend.
---

# fht-operations

Environment, data acquisition, every CLI command, and every cache/config axis for
this solo fantasy-hockey ML project. Facts below were read from source or produced
by running the read-only form of each command on 2026-07-05, in this repo, on
Windows 11. Anything not actually run is labeled `UNVERIFIED` with the reason.

## 1. Environment

Setup is `uv`-based per `README.md`:

```powershell
uv venv
uv pip install -e .
```

Verified state today: venv at `.venv\`, Python **3.14.3** actually installed
(`pyproject.toml` only requires `>=3.12`). System `python` on this machine resolves
to a *different* interpreter (3.8.2) — always invoke the venv's own binary, never
bare `python`/`py`:

```powershell
.\.venv\Scripts\python.exe main.py --help
```

`pyproject.toml` lists **direct dependencies only, as floors** (July 2026): `pandas`,
`numpy`, `xgboost`, `scikit-learn`, `scipy`, `matplotlib`, `pyarrow`, `rapidfuzz`,
`requests`, `objectpath`, `anthropic`, `yahoo-oauth`, `yahoo-fantasy-api`, plus
`pytest` in the `dev` extra. It used to be a flat 110-pin venv freeze; the resolver
now handles transitives.

**`torch` is NOT installed by default.** The LSTM is parked, torch is ~3 GB, and
nothing on the shipped path imports it, so it lives in an optional extra:

```powershell
uv pip install -e ".[lstm]"
# GPU (CUDA 12.8):
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

`streamlit` is gone entirely — `ui/` was deleted July 2026; the Next.js `frontend/`
is the only UI.

**Discipline rule (Learning Log incident 3, PROJECT-PLAN.md):** when you add a real
new import, add it to `pyproject.toml` AND `requirements.txt` in the same commit.
Do not re-freeze the venv into either file — that is what created the 110-pin list.

## 2. Data acquisition runbook

There is **no auto-downloader, ever** — `src/moneypuck.py`'s header states MoneyPuck
asks scrapers to obtain a data license, so both files are manual browser downloads
from https://moneypuck.com/data.htm (per `README.md` "Data Setup" and
`src/moneypuck.py`):

| Download | Save as | Verified size/mtime (2026-07-05) |
|---|---|---|
| "All Situations, 2008-2024" | `data/raw/2008_to_2024.csv` | 2,620,103,561 bytes (~2.6 GB), Apr 2 |
| "All Situations, Current Season" | `data/raw/moneypuck_current.csv` | 154.8 MB, Apr 3 |

`checkCurrentFreshness()` (`src/moneypuck.py:36`) nags once the current file is
older than `STALE_DAYS = 3`. Verified today:

```powershell
.\.venv\Scripts\python.exe -c "from src import moneypuck; moneypuck.checkCurrentFreshness()"
# -> moneypuck_current.csv is 93 days old - grab a fresh copy in your browser from https://moneypuck.com/data.htm
```

93 days stale is *expected* right now — the 2025-26 season is over and there's no
"current season" data to refresh until the next one starts (~October). Don't treat
this warning as a bug in the offseason.

NHL API data (roster identity only — `players_cache.csv`) self-populates through a
24h file cache on first `pickups`/`api_export.py` run — no manual step. Yahoo is optional: see
`YAHOO_SETUP.md` for the OAuth flow. `oauth2.json` and `.env` are both untracked and
gitignored (verified `git ls-files .env oauth2.json` → empty) — **never print or
commit their contents**. The league id is hardcoded at `src/yahooAPI.py:12`
(`gm.to_league('nhl.l.33072')`); if `pickups`/`api_export.py` run without
`oauth2.json` they degrade gracefully (roster filtering just gets skipped, a
warning is printed).

## 3. Command anatomy

All commands are repo-root relative, run from the venv interpreter.

| Command | Does | Prerequisites | Writes | Status |
|---|---|---|---|---|
| `.\.venv\Scripts\python.exe main.py train-pickups` | Trains pickup (XGBClassifier + `RandomizedSearchCV`, 20 iter, `PredefinedSplit` train≤2022/val 2023) then cooling model (`src/main.py:trainPickups`) | Both MoneyPuck CSVs present | `models/pickups/model.pkl`, `models/cooling/model.pkl`, `reports/pickup_{roc_curve,feature_importance}.png`, `reports/cooling_{roc_curve,feature_importance}.png` | **UNVERIFIED** — not run during authoring (writes model binaries, minutes-long RandomizedSearchCV). Expected output magnitudes: pickup val AUC ≈0.73, cooling ≈0.64 — canonical record of the exact numbers: `fht-quality-gates` golden inventory |
| `.\.venv\Scripts\python.exe main.py pickups` | Heuristic + ML blend ranking of free agents (`main.py:runPickups`, `final_score = 0.3*heuristic + 0.7*ml_score`) | Trained `models/pickups/model.pkl` and `models/cooling/model.pkl` (**currently absent — see below**), both MoneyPuck CSVs, network for the NHL API roster fetch only (~32 team requests via `getAllPlayersWithCache`, seconds not minutes — the old per-player stats fetch is deleted); Yahoo optional | `data/raw/players_cache.csv`, `data/processed/current_players_features.csv` | **UNVERIFIED** — models missing, needs network |
| `.\.venv\Scripts\python.exe main.py spot-check [--date YYYYMMDD] [--top N]` | Offline backtest of the pickup model at fixed dates (default `--top 15`, dates `20251101 20251201 20260101 20260201 20260301` from `src/backtest.py:DEFAULT_DATES`) | `models/pickups/model.pkl` + MoneyPuck cache only, no network | Nothing persisted (prints tables) | **UNVERIFIED** — `models/pickups/model.pkl` absent. Verified `--help` output matches this signature |
| `.\.venv\Scripts\python.exe main.py train-draft` / `draft` / `keeper` | **No longer stubs** (shipped Phase B4/keeper): `train-draft` trains `src/models/draft.py`; `draft` writes the VORP board `data/processed/draft_rankings.csv` (goalie-inclusive since 2026-07-16); `keeper` ranks the Yahoo roster's keepers | `train-draft`: `player_seasons.csv`. `draft`: `player_seasons.csv` + trained draft/goalie models (goalies optional — board degrades to skaters-only). `keeper`: Yahoo OAuth (`oauth2.json`) | `models/draft/model.pkl` (train), `data/processed/draft_rankings.csv` (draft) | Implemented (`main.py` `trainDraft`/`runDraft`/`runKeeper`); no `NotImplementedError` remains |
| `.\.venv\Scripts\python.exe main.py train-goalies` | Trains the goalie draft ranker `src/models/goalieDraft.py` (baselines A/B → Ridge → XGBoost, ships whichever passes GATE G3; as of 2026-07-16 it ships **Baseline B `fp_w3`** — `{'kind': 'baseline_b'}`) | `data/processed/goalie_seasons.csv` present (build it first) | `models/goalieDraft/model.pkl` | **VERIFIED** 2026-07-16: GATE G3 failed → Baseline B shipped; test-2024 untouched |
| `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts/build_goalie_seasons.py` | Merges `data/raw/goalies/*.csv` (MoneyPuck goalie skill stats) with NHL API goalie season records into `goalie_seasons.csv`; fetches NHL records threaded (minutes); prints GATE G1 acceptance checks | The two goalie CSVs in `data/raw/goalies/`; network; **`PYTHONUTF8=1` required** (`getPlayerStats` prints non-ASCII names) | `data/processed/goalie_seasons.csv` (1,702 rows) + permanent cache `data/raw/goalie_nhl_seasons.csv` | **VERIFIED** 2026-07-16: 1,702 rows / 18 seasons (2008–2025), 100% MoneyPuck↔NHL-API merge, Hellebuyck 2023-24 exact |
| `.\.venv\Scripts\python.exe scripts/build_player_seasons.py` | Aggregates game logs to one row per (playerId, season) via `loadGameLogs(min_season=2008)` → `buildPlayerSeasons`; prints GATE B1 acceptance checks | Both MoneyPuck CSVs present | `data/processed/player_seasons.csv` (16,237 rows) + `moneypuck_games_2008.csv` game cache as a side effect | **VERIFIED** July 6 2026: 16,237 rows / 18 seasons (2008–2025), McDavid 2023-24 = 32G/100A. First run reads the full 2.6 GB history (minutes) |
| `.\.venv\Scripts\python.exe scripts/build_birthdates.py` | Fetches `birthDate` for playerIds in `player_seasons` + `goalie_seasons` that the cache lacks (threaded via `dataProcessing.fetchAllPlayers`, 5 workers) | `player_seasons.csv` built; network only if ids are missing | `data/raw/player_birthdates.csv` | **VERIFIED** July 6 2026: 3038/3038, 100% coverage. Since July 2026 it uses `appendMissingBirthDates` (so rookies get picked up on a re-run) and is **resumable** — progress flushes to `.partial` every 100 players, so an interrupted run continues instead of restarting. `player_birthdates.csv` is now committed, so a fresh clone needs zero API calls. `PYTHONUTF8=1` no longer required (per-request prints are `logger.debug` now) |
| `.\.venv\Scripts\python.exe -m pytest -v` | Runs test suite | none | `.pytest_cache/` | **VERIFIED 2026-07-20**: 125 passed, 0 failed in ~2.6s. Both previously-known failures are fixed — a red suite is now a real regression, not expected noise. Config quirk verified: pytest reports `configfile: pytest.ini (WARNING: ignoring pytest config in pyproject.toml!)` — `pytest.ini` wins over `pyproject.toml`'s `[tool.pytest.ini_options]`. README's `uv run pytest` is equivalent when `uv` is on PATH |
| `.\.venv\Scripts\python.exe api_export.py` | Exports `data/processed/frontend_data.json` for the Next.js dashboard | Same as `pickups` (models + MoneyPuck data + network) | `data/processed/frontend_data.json` | **UNVERIFIED** — needs trained models + network |
| `npm install` then `npm run dev` (in `frontend\`) | Installs deps, runs Next.js dev server reading `frontend_data.json` | Node/npm; `api_export.py` already run | `frontend/node_modules/`, `frontend/.next/` | **UNVERIFIED** — verified `frontend/node_modules` does not currently exist (`Glob frontend/node_modules` → no match) |

Verified today: `.\.venv\Scripts\python.exe -c "import main"` succeeds. Since the
July 2026 dependency slim it no longer imports `torch`, so first import is much
faster.
Verified `Get-ChildItem -Recurse models` → only `models\draft\.gitkeep` and
`models\pickups\.gitkeep`, zero `.pkl` files, and **no `models\cooling\` directory
at all** (it's created on first `train-pickups` run via `save()`'s `os.makedirs`).
So on this machine right now, `pickups`/`spot-check`/`api_export.py` will all fail
with `FileNotFoundError` until `train-pickups` runs at least once.

## 4. Cache and artifact catalog

This project's "config" is constants-in-source plus file caches — there is no
config file layer. Force-refresh always means "delete the cache file."

| Cache file | TTL / invalidation | Force refresh |
|---|---|---|
| `data/raw/players_cache.csv` — the pickup path's only NHL API cache (identity/roster only; the old per-player `stats_current.csv`/`stats_last5.csv` fetches are deleted) | 24h wall-clock, checked by `getWithCache` (`src/dataProcessing.py:56`) via `os.path.getmtime` | Delete the file |
| `data/processed/current_players_features.csv` | 24h, checked independently in **two places** with duplicated logic: `main.py:latestGameState` and `api_export.py:latestGameState` | Delete the file |
| `data/processed/moneypuck_games_2020.csv` (pickup pipeline) / `moneypuck_games_2008.csv` (draft pipeline) | Reused whenever its mtime is newer than `moneypuck_current.csv`'s mtime (`src/moneypuck.py:80-83`, `loadGameLogs`) — i.e. it survives until you replace the current-season download with a newer one. The `_2008` variant is a superset of `_2020`; the filename number is `min_season`, a floor, not a single year | Delete the file, or just replace `moneypuck_current.csv` with a fresher download (rebuild re-reads the 2.6 GB history file — minutes) |
| `data/processed/player_seasons.csv` (draft) | No auto-expiry — `buildPlayerSeasons` does not self-cache; the `.to_csv` lives in `scripts/build_player_seasons.py`, run on demand | Delete + re-run the script (re-reads the 2.6 GB history) |
| `data/raw/player_birthdates.csv` (draft age feature) | **Permanent — never expires**, and now **committed to git**, so a fresh clone needs no API calls. birthDates are immutable | Re-run `scripts/build_birthdates.py`: it appends only ids the cache lacks (rookies, goalies). Deleting the file forces a full ~3000-player refetch — rarely what you want |
| `data/raw/goalie_nhl_seasons.csv` (goalie NHL API season records) | **Permanent — never expires.** `dataProcessing` returns it whenever the file exists, so a new season's records are NOT fetched until you delete it (see the goalie rollover step in section 4's checklist) | Delete the file, then rerun `scripts/build_goalie_seasons.py` |
| `data/processed/goalie_seasons.csv` (goalie ranker input) | No auto-expiry — `scripts/build_goalie_seasons.py` writes it on demand | Delete + rerun the build script |
| Yahoo roster lookups | Uncached — hits the API every call | n/a |

Constants catalog (all read from source today):

| Constant | Value | Location |
|---|---|---|
| `CURRENT_SEASON` | 2025 (MoneyPuck season convention — see `fht-domain-reference` §2) | **`src/season.py` — the only definition.** `main.py` and `api_export.py` re-export it |
| `LAST_COMPLETED_SEASON`, split boundaries | 2024; draft train ≤2021 / val (2022, 2023) / test 2024; pickup train ≤2022 / val 2023 | `src/season.py`, derived as offsets; the models import them |
| `SEASON`, `DEFAULT_DATES` | 2025; `[20251101, 20251201, 20260101, 20260201, 20260301]` | `src/backtest.py`, derived via `season.spot_check_dates()` |
| Roster/draft proxy cutoffs | `ROSTER_PROXY_CUTOFF=150`, `DRAFT_PROXY_CUTOFF=150`, `PRIOR_MIN_GAMES=40`, `HOT_PERCENTILE=0.75` | `src/backtest.py:31-34` |
| `20252026` season id (headshot URLs) | Derived — no longer hardcoded | `season.nhl_season_id()`, used by `api_export.get_headshot_url` |
| `STALE_DAYS` | 3 | `src/moneypuck.py:22` |
| Fuzzy-match `score_cutoff` | 85 | `src/yahooAPI.py:31`, `src/keepers.py:53` |
| Pickup blend weights | `0.3 * heuristic + 0.7 * ml_score` | `main.py:112` (`runPickups`), `api_export.py:110` |
| Label quantiles | `hot_quantile=0.75`, `cold_quantile=0.25` | `src/features/mlFeatures.py:44` (`buildLabel`) |
| Model paths | `models/pickups/model.pkl`, `models/cooling/model.pkl`, `models/draft/model.pkl` | `src/models/{pickups,cooling,draft}.py` `MODEL_PATH` |

**Annual rollover checklist** (July 2026: the season constants are no longer
scattered — `src/season.py` owns them):

1. Bump `CURRENT_SEASON` in **`src/season.py`**. That is the only source edit —
   split boundaries, spot-check dates, headshot URLs and season labels all derive
   from it.
2. Run `pytest tests/test_season.py`. It pins the derived boundaries against the
   values the shipped models trained with, so a rollover that silently shifts a
   train/val split fails loudly. **Update those pinned values deliberately** as
   part of the rollover — they are meant to change once a year and never
   otherwise.
3. Re-curate `backtest.KNOWN_PICKUPS` for the new season. It is hand-written from
   that season's waiver results and cannot be derived; a stale list makes the
   "known gems" report meaningless.
4. Create a fresh `data/raw/keepers.csv` (see below).
5. Download a fresh `moneypuck_current.csv`.
6. Re-run `scripts/build_birthdates.py` to pick up the new season's rookies (it
   appends only missing ids, so this is cheap).

**Goalie rollover (added 2026-07-16):** re-download the two *current-season* goalie CSVs into
`data/raw/goalies/` (`goalies_current_seasons.csv` + `goalies_current_gamedata.csv`) from
MoneyPuck; **delete `data/raw/goalie_nhl_seasons.csv`** (it's a permanent cache that never
auto-expires, so the new season's NHL API records won't be fetched until you delete it); rerun
`$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts/build_goalie_seasons.py` to rebuild
`goalie_seasons.csv`; then `.\.venv\Scripts\python.exe main.py train-goalies` to retrain the ranker.

## 5. Traps

- **Running system Python instead of the venv.** Verified `python --version` on
  this machine returns 3.8.2 while `.\.venv\Scripts\python.exe --version` returns
  3.14.3. Always call the venv binary explicitly.
- **Expecting committed model binaries.** Model `.pkl` files are gitignored
  ("retrain locally"); PROJECT-PLAN.md decision #9 says otherwise but is stale —
  see `fht-architecture-contract` for the contradiction analysis. Verified: no
  `.pkl` exists anywhere in `models/` right now, so any fresh clone (this machine
  included) must run `train-pickups` before `pickups`/`spot-check`/
  `api_export.py` will work.
- **`data/` and `reports/` are gitignored** (`.gitignore`: `data/**/*.csv`,
  `data/processed/*.json`, `reports/`) — don't try to `git add` outputs from
  training or data downloads; they won't diff usefully and aren't meant to be
  versioned.
- **First-run NHL fetch is slow and rate-limited (draft/goalie builds only).**
  `src/nhlAPI.py` retries on 429 with a sleep (5s for roster calls, 15s for player
  calls); `scripts/build_birthdates.py` and `scripts/build_goalie_seasons.py` still
  fetch per-player, so a cold run of either is a multi-minute operation. `pickups`
  no longer does per-player fetches — its only NHL API traffic is the ~32-request
  roster cache (`players_cache.csv`), which is near-instant even cold, then
  near-instant for 24h via the caches in section 4.
- **`data/raw/keepers.csv` does not exist yet** (verified via glob) — `main.py
  draft` is a stub anyway, but `src/keepers.py::loadKeepers` will raise if this
  file is missing or empty ("an empty keeper list silently drafts everyone").

## When NOT to use this skill

- Module boundaries, data model, or scoring-formula rationale → `fht-domain-reference`.
- Architecture/module-ownership rules and settled design decisions → `fht-architecture-contract`.
- The failing test, the plot-collision bug, or other live incidents → `fht-debugging-playbook`.
- Test coverage philosophy, what should/shouldn't have a test → `fht-quality-gates`.
- Draft/keeper-analyzer roadmap and Phase B/C work → `fht-draft-campaign`.
- Model-quality or "beyond SOTA" ambitions → `fht-research-frontier`.

## Provenance and maintenance

Re-verify these before trusting this file on a later date:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
Get-ChildItem -Recurse models
Get-ChildItem data\raw, data\processed
Select-String -Path src\season.py -Pattern "CURRENT_SEASON ="
.\.venv\Scripts\python.exe -c "from src import moneypuck; moneypuck.checkCurrentFreshness()"
Get-Item frontend\node_modules -ErrorAction SilentlyContinue
```
