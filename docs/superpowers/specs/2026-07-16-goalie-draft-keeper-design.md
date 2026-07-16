# Goalie draft + keeper ranking - design

Drafted 2026-07-16; open decisions settled with the owner the same day. Adds
goalies to the draft analyzer and keeper analyzer with a trained goalie
ranker. This **supersedes** the old "Goalies v1 = NO ML" decision in
PROJECT-PLAN.md Phase D — the owner requested a trained model on 2026-07-16
and supplied the MoneyPuck goalie data to power it. Pickups stay skaters-only;
goalie streaming is an explicitly separate future feature (starters are rarely
on waivers).

## Decisions settled with owner (2026-07-16)

- **Losses are regulation-only.** The league does not record OT/SO losses as
  losses, and OTL earns/costs nothing. Use the NHL API `losses` field as-is.
- **The six goalie categories are the complete scoring picture** — no SV%,
  GAA, or OTL categories exist in the league.
- **Goalie replacement rank is 20.** Teams roster two goalies each; no
  third-goalie benching habit in this league.
- **The draft board's default cross-position order is VORP.** Every row in
  `draft_rankings.csv` (skaters and goalies) gains a `vorp` column.
- **Goalies are full keeper candidates.** They compete for the four keeper
  slots purely on net keeper value; the math decides.

## Scope and non-goals

In scope: goalie fantasy scoring, a `goalie_seasons` table (MoneyPuck + NHL
API), goalie draft features, a goalie ranker model with the Phase B baseline
protocol, goalie rows in `draft_rankings.csv`, goalie eligibility in the
keeper analyzer, and the frontend/UI touches those imply.

Out of scope: goalie streaming/pickups, in-season goalie models, rookie
goalies (no prior NHL season — same scope cut as skaters), backup/starter
depth-chart inference, and any change to the skater draft model.

## The uniform-scoring problem, settled

Goalies and skaters already share a currency: **league fantasy points**. The
league's goalie categories (PROJECT-PLAN.md, verified) get their own weights
table beside `SKATER_WEIGHTS` in `src/fantasyPoints.py`:

```python
GOALIE_WEIGHTS = {
    'gamesStarted': 0.75,
    'wins': 2.5,
    'losses': -1,
    'goalsAgainst': -0.5,
    'saves': 0.15,
    'shutouts': 3,
}
```

plus `calculateGoaliePoints(stats)` mirroring `calculateSkaterPoints` (NHL API
field names; `saves = shotsAgainst - goalsAgainst`). Single source of truth,
same file, same discipline.

Raw FP is the shared **unit** but not the shared **ranking axis** — a workhorse
starter piles up FP the way no skater does, and positional scarcity differs.
The cross-position axis is **VORP (value over replacement)**, which the keeper
analyzer already implements for skaters: extend `src/keeper.py`'s
`REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48}` with `"G": 20`
(10 teams × 2 starting G slots; no Util eligibility for goalies). Keeper value
and any cross-position draft comparison use
`projected_total - replacement_level[position]` uniformly. Within-position
ordering is unchanged by this.

**Confirmed by owner 2026-07-16:** `losses` means NHL-definition regulation
losses (the NHL API `losses` field, excluding `otLosses`). OT/SO losses are
not recorded as losses in this league and earn/cost nothing.

## Data

### Raw files (labeled 2026-07-16, see data/raw/goalies/README.md)

| File | Grain | Coverage |
| --- | --- | --- |
| `goalies_current_seasons.csv` | goalie-season-situation | 2025 (2025-26) |
| `goalies_current_gamedata.csv` | goalie-game-situation | 2025 (2025-26) |
| `goalies_2008_to_2024_seasons.csv` | goalie-season-situation | 2008–2024 |
| `goalies_2008_to_2024_gamedata.csv` | goalie-game-situation | 2008–2024 |

Same situation-row structure as skater MoneyPuck data: use `situation == 'all'`
rows only; summing situations double-counts. The game-grain files are **not
used** by this design — they are staged for the future streaming feature.

### What MoneyPuck lacks, and the merge that fixes it

MoneyPuck goalie data is shot/xGoals data: no wins, losses, shutouts, or games
started — so **fantasy points cannot be computed from MoneyPuck alone**. The
NHL API landing endpoint (`/player/{id}/landing`, already the repo's
identity/birthDate source) provides per-season `seasonTotals` with
`gamesPlayed`, `gamesStarted`, `wins`, `losses`, `otLosses`, `shutouts`,
`goalsAgainst`, `shotsAgainst` for NHL regular seasons.

`scripts/build_goalie_seasons.py` (one-time build per season, mirroring
`build_player_seasons.py` + `build_birthdates.py`):

1. Load both season-grain MoneyPuck files, keep `situation == 'all'`, concat
   2008–2024 + current → one row per goalie-season with icetime, xGoals,
   goals (= goals against), ongoal (= shots on goal against), danger-band
   columns, `games_played`.
2. Fetch `seasonTotals` for every unique goalie playerId (~500 ids, threaded
   like `dataProcessing.getAllBirthDatesWithCache`, cached permanently to
   `data/raw/goalie_nhl_seasons.csv` — refresh appends only the current
   season). Filter to `gameTypeId == 2` and `leagueAbbrev == 'NHL'`; convert
   NHL season keys (`20232024`) to MoneyPuck years (`2023`).
3. Merge on `playerId + season` (MoneyPuck playerId IS the NHL playerId),
   compute `fantasyPoints` via `calculateGoaliePoints`, `fpPerGame`
   (per NHL-API `gamesPlayed`), and skill columns:
   `gsax = xGoals - goals` (goals saved above expected),
   `save_pct = 1 - goals / ongoal`, and
   `xsave_delta = save_pct - (1 - xGoals / ongoal)`.
4. Write `data/processed/goalie_seasons.csv` (gitignored, like
   `player_seasons.csv`) and print GATE G1 acceptance checks.

**GATE G1:** ~17–18 seasons × ~90 goalies ≈ 1,400–1,700 rows; merge hit rate
between MoneyPuck and NHL API reported and ≥95% (measure it — the birthdates
lesson: never trust a join without its hit rate); spot-check one goalie-season
by hand against hockey-reference (e.g. Hellebuyck 2023-24: 60 GP, 37 W,
5 SO). If rows ≈ 5× expected, situation rows leaked through.

Also extend the birthdate cache to goalie ids: `build_birthdates.py` reads
`player_seasons.csv` only, so the goalie build reuses
`getAllBirthDatesWithCache` for its ids and appends to
`data/raw/player_birthdates.csv` (same cache, union of ids).

## Features — `src/features/goalies.py::build_goalie_features`

Takes the `goalie_seasons` table, same discipline as
`src/features/draft.py::build_draft_features` (own-season columns as features,
only the target shifts, `groupby('playerId')`-scoped lags):

- `fpPerGame`, `fp_delta`, `fp_w3` (50/30/20, same scheme as skaters)
- `gsax_per60` (gsax / icetime × 3600) — the goalie analog of
  `xGoalsSurplus`, sign flipped: positive = stopping more than expected
- `save_pct`, `xsave_delta`
- `gs_share` = gamesStarted / 82 — workload is the dominant goalie fantasy
  signal; this is the starter-vs-backup feature
- `career_games` (cumsum of gamesPlayed)
- `age_at_season_start` (birthdate cache, Oct-1 season start, same code path)
- `target_fpPerGame` = next season's `fpPerGame`, masked to consecutive
  seasons; `target_gamesPlayed` alongside, exactly as in draft.py

No position one-hots (all rows are G). **GATE G2 (leakage):** no feature may
use same-season-or-later information relative to the target season.

## Model — `src/models/goalieDraft.py`

Same four-function interface (`train`/`predict`/`load`/`save`), same protocol
as `src/models/draft.py`, saved to `models/goalieDraft/model.pkl` (gitignored,
retrain locally):

- Target: next-season goalie **FP per game played** (PPG discipline — totals
  conflate skill with injury/workload luck, same settled rationale).
- Splits: train ≤ 2021, val 2022+2023, test 2024 (one look, then stop).
- `MIN_GP = 15` both sides (goalie seasons max ~65 games; 20 would discard
  legitimate backup seasons; 15 keeps them while excluding cameos).
- Baseline A: last-season FP/GP. Baseline B: `fp_w3`. Record val Spearman +
  MAE for both, in text, before any model.
- Ridge as coefficient-sign diagnostic (gs_share and fp_w3 strongly positive
  expected), then XGBoost via the proven
  `RandomizedSearchCV + PredefinedSplit + refit=False` pattern.

**GATE G3:** the model ships only if it beats **both** baselines on val
Spearman; otherwise ship Baseline B as the goalie ranker — a legitimate
outcome, and *more likely here than for skaters*: expect only ~600–900
eligible training rows (vs ~11k skater rows), so a baseline win is the honest
default expectation. Small-sample caveat goes in the Learning Log either way.

## Rankings integration

`main.py`:

- New `train-goalies` subcommand → builds features from `goalie_seasons.csv`,
  runs the G3 protocol.
- `draft` gains goalie rows: build current-season goalie features, predict,
  and append to `data/processed/draft_rankings.csv` with `position = 'G'` and
  the same columns. Projected total for goalies is
  `projected FP/GP × projected GP` where **projected GP = 50/30/20 weighted
  gamesPlayed, capped at 65** (deterministic heuristic; `× 78` is a skater
  assumption). A `projected_gp` column is added for transparency (78 for
  skaters).
- `draft` computes a `vorp` column for **every** row (skaters and goalies):
  `projected_total - replacement_level[position]`, from the same
  `replacement_levels()` function the keeper analyzer uses, run on the
  combined skater+goalie projection table before any keeper filtering. VORP
  is the board's default cross-position order.
- If the goalie model/data prerequisites are missing, `draft` warns loudly
  and emits skaters only — never silently, never fatally (`vorp` still
  computed for the skater rows).

`src/keeper.py`:

- Add `"G": 20` to `REPLACEMENT_RANKS`; delete the goalie-exclusion branch
  (`excluded_reason = "Goalies are excluded..."`) so rostered goalies resolve
  against the goalie rows in the projection table and compete for the four
  keeper slots on `net_keeper_value` like everyone else.
- Replacement level for G comes from the same `replacement_levels()` function
  operating on the now-goalie-inclusive projection table.

Frontend/UI: draft board gets `G` in the position filter, renders the goalie
rows it now receives, and **default-sorts the all-positions view by `vorp`**
(per-position views may keep projected FP/G ordering); keeper page drops the
"goalies are intentionally excluded" note and renders goalie candidates like
skaters. The keeper LLM
summary prompt (`scripts/build_keeper_summary.py`) drops its "do not mention
goalies" instruction. No new routes, no new sections in `frontend_data.json`.

**GATE G4 (eyeball):** top of the goalie rankings must be
Hellebuyck/Shesterkin-tier workhorse starters; no backup with a hot 20-game
season may outrank a healthy starter on projected **total** (per-game rank may
legitimately differ). If it looks wrong, it is wrong — debug features first.

## Testing (per fht-quality-gates)

Pure-function pytest coverage:

- `calculateGoaliePoints` against a hand-computed season (weights table math).
- goalie_seasons aggregation rejects situation double-counting (feed a fixture
  with all 5 situation rows, assert only `'all'` survives).
- NHL-season-key conversion and the merge (fixture ids, assert hit rate math).
- Feature leakage: `target_fpPerGame` masked across gap seasons; lags scoped
  by playerId.
- `REPLACEMENT_RANKS["G"]` flows through `replacement_levels()`; keeper
  eligibility now includes G rows and excludes nothing by position.
- Projected-GP heuristic (weights, cap, single-season goalies).

Network fetches are not unit-tested (repo doctrine). Gates G1–G4 numbers get
recorded in PROJECT-PLAN.md's Learning Log, and Current Phase is updated.

## Work breakdown (implementation-plan order)

1. **Data labeling** (done 2026-07-16 in the design session): renamed the
   four raw files by grain + README.
2. **Scoring**: `GOALIE_WEIGHTS` + `calculateGoaliePoints` + tests.
3. **goalie_seasons build**: `scripts/build_goalie_seasons.py`, NHL API
   season cache, birthdate-cache extension, GATE G1 checks.
4. **Features**: `src/features/goalies.py` + leakage tests (GATE G2).
5. **Model**: `src/models/goalieDraft.py`, baselines → Ridge → XGBoost,
   GATE G3 verdict, `main.py train-goalies`.
6. **Draft integration**: goalie rows + `projected_gp` in
   `draft_rankings.csv`, `vorp` for all rows, graceful degradation,
   GATE G4 eyeball.
7. **Keeper integration**: replacement rank G, exclusion removal,
   keeper-summary prompt update, tests.
8. **Frontend/UI**: position filter, keeper page copy, verify old
   `frontend_data.json` snapshots still render.
9. **Bookkeeping**: PROJECT-PLAN.md phase/decision updates (supersede
   "Goalies v1 = NO ML"), Learning Log entries, `fht-draft-campaign` +
   `fht-architecture-contract` skill updates ("Goalies have no scoring path"
   weak-point row comes out).

All open questions were answered by the owner on 2026-07-16 — see "Decisions
settled with owner" at the top.
