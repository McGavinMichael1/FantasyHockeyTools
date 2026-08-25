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
MoneyPuck CSVs  -> src/moneypuck.py (all MoneyPuck IO; processed caches are
                   version-tagged Parquet: moneypuck_games_v2_{season}.parquet)
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
- **The draft board is roster-aware as of 2026-08-24.** Picks are a **pick log**
  (`{id, pick, mine}`, `localStorage` key `fht.draftLog.v2`, migrating `fht.draftedIds.v1`), not a
  flat id set — which is what lets the board know *your* roster. Built on that: a roster panel vs.
  `keeper.STARTING_SLOTS`, an "on the clock" shortlist, undo, a keyboard loop (`/` focus, `⏎`
  taken, `⇧⏎` mine, `Ctrl/Cmd+Z` undo), tier chips, a last-season stat line, and multi-select
  position filters. Two rules to keep: **all new draft logic goes in `frontend/src/lib`**, never in
  the components (the runner is bare `node --test` with no DOM, so `src/lib` is the only testable
  surface); and **tiers (`lib/tiers.ts`) are a display heuristic, not a model output** — gap-based
  clustering of projections, never presented as or fed into a projection.
- **`best_available` lives in two languages, pinned by one fixture.** `mockDraft.best_available`
  (promoted from `_best_available`) and `frontend/src/lib/bestAvailable.ts` are both run against
  `tests/fixtures/best_available_cases.json` — 13 cases plus the league slot constants themselves.
  The live board must work on draft day with no Python running, hence the duplication. Change the
  rule in one place and the other language's test fails. Do not "fix" one side alone.
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
- **Deployment features shipped for pickups; the luck family was tested and rejected**
  (2026-08-24). PP ice time (`powerPlayIcetime` from the `5on4` row, plus `pp_toi_share`) is
  now a pickup/cooling feature: val Spearman 0.6214 → 0.6249, spot-check top-15 mean 54.8% →
  56.2%, gate passed. Two recorded surprises: the **level** carries the signal, not the
  5-vs-20 delta (`rolling_20_powerPlayIcetime` ranks 3rd of 49 features,
  `rolling_delta_5_20_pp_toi_share` ranks 44th), and on the canonical Raddysh case it helps
  only *after* the breakout — at the one date he is a real free agent it moved him DOWN 47
  places. Split PDO (on-ice SH%/SV%/gax) **failed its gate and was reverted** (spot-check
  56.2% → 53.4%, simulated adds 60% → 56%), and **both** families were rejected for the draft
  ranker (val Spearman 0.8259 → 0.8244/0.8256); `onice_sh_luck`'s Ridge coefficient came out
  positive when a luck residual must be negative, and it promoted 38-year-old Brad Marchand 21
  places — the player class it was designed to demote. The statistics were verified correct
  first (league mean PDO 0.9995), so these are real negative results. Season-level columns
  (`ppToiShare`, `avgPPIcetime`, `oniceShootingPct`, `oniceSavePct`, `pdo`, `oniceGaxPerGame`)
  are still **computed** in `player_seasons.csv` for the board and future work — a test pins
  that they are not draft model features. Full numbers: PROJECT-PLAN Learning Log 2026-08-24.
- **The keeper board ranks on a 5-year horizon as of 2026-08-24.** `src/keeperHorizon.py` applies
  an empirical age curve and survival curve (measured off the 18 seasons already on disk) to the
  existing year-1 VORP: `Σ discount^k · S(age,k) · [A(age,k)·vorp₁ − pick_cost]`, H=5,
  discount=0.88. Four rules to keep. **Age buckets by `round()`, never `floor()`** — that is the
  convention the design's measured table was built with, confirmed by reproducing all ten of its
  published `(ratio, n)` pairs exactly, and the spec named this off-by-one as the module's most
  likely bug. **Survival multiplies the cost as well as the benefit** (not playing means not
  paying the picks) and **both sides scale with the horizon** — multiplying only the benefit is the
  same unit error as the old "keep nobody" bug. **`horizon_keeper_value` is already cost-inclusive;
  never subtract `pick_cost` from it again** — `keeper_advisor._scenario_sets` is a second
  implementation of the ranking rule and now calls `keeper.recommendation_order` rather than
  re-deriving it. Passing no `horizon_curves` degrades to the exact single-season behaviour.
  Frontend display logic lives in `frontend/src/lib/keeperHorizon.ts`, per the src/lib rule.
  Two measured results worth knowing: survival (not production) is what separates a 34-year-old
  from a 23-year-old, and the **goalie multiplier peaks at 24 and is low at 21** — the opposite
  shape from skaters, because young goalies do not stick.
- **The game-log cache filename is versioned** (`moneypuck.GAME_CACHE_VERSION`, now `v2`).
  `loadGameLogs` prefers a fresh-looking cache over the raw CSVs, so widening `GAME_COLUMNS`
  without bumping the tag would serve a stale-schema cache and fail downstream with a
  `KeyError` that looks like a code bug. A fresh clone now builds
  `data/processed/moneypuck_games_v2_{min_season}.parquet`; bump the tag whenever
  `GAME_COLUMNS` changes.
- ~~Season constants duplicated across files~~ — fixed July 2026: `src/season.py` owns `CURRENT_SEASON` and derives every split boundary, spot-check date, season label and headshot season id from it. Rollover is a one-line edit there, and `tests/test_season.py` pins the derived values so a silent shift fails loudly. `backtest.KNOWN_PICKUPS` still needs hand re-curation each season — it cannot be derived.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

`pytest.ini` (not `pyproject.toml`'s `[tool.pytest.ini_options]`) is the config
pytest actually reads — it wins when both exist.
