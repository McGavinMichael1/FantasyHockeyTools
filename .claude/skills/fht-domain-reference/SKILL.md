---
name: fht-domain-reference
description: Use when reading MoneyPuck game logs or their column subset, computing or changing fantasy-point scoring, interpreting situation rows (all/5on4/4on5/5on5/other) or PPP/SHP derivation, interpreting what NHL API or Yahoo API fields and responses mean (not how to call/cache them or fix their errors — see fht-operations / fht-debugging-playbook), or when a hockey/fantasy term (VORP, replacement level, gameScore, Corsi) is unclear.
---

# FHT domain reference

Domain facts only — not how to run commands (see fht-operations) or why the
system is shaped this way (see fht-architecture-contract). Every fact below
was verified against repo source on 2026-07-05; anchors are `path:line`.

## 1. The league and fantasy mechanics

League: Yahoo `nhl.l.33072`, hardcoded at `src/yahooAPI.py:12`. 10 teams, 4
keepers. Roster: `C, C, LW, LW, RW, RW, D, D, D, D, Util, G, G, BN×5, IR+×2`
(PROJECT-PLAN.md:316).

**Skater scoring** (PROJECT-PLAN.md:293-304, exactly matches
`SKATER_WEIGHTS` at `src/fantasyPoints.py:4-14`):

| Stat | Weight |
|---|---|
| Goals (G) | 3 |
| Assists (A) | 2 |
| Plus/Minus (+/-) | 0.5 |
| Powerplay Points (PPP) | 1 |
| Shorthanded Points (SHP) | 1 |
| Game-Winning Goals (GWG) | 1 |
| Shots on Goal (SOG) | 0.15 |
| Hits (HIT) | 0.15 |
| Blocks (BLK) | 0.35 |

**Goalie scoring** (PROJECT-PLAN.md:306-314 — reference only; no goalie
scoring code exists yet, see fht-draft-campaign Phase D):

| Stat | Weight |
|---|---|
| Games Started (GS) | 0.75 |
| Wins (W) | 2.5 |
| Losses (L) | -1 |
| Goals Against (GA) | -0.5 |
| Saves (SV) | 0.15 |
| Shutouts (SHO) | 3 |

Fantasy-mechanics glossary (a non-hockey engineer needs these):

- **Draft** — once-yearly October event where each team fills its roster from
  the full skater/goalie pool; drafted players are "owned" all season.
- **Waivers / free agents** — undrafted (or dropped) players anyone can add;
  the pickup analyzer ranks these week to week.
- **Pickup / drop** — the in-season roster move of adding a free agent and
  cutting a rostered player to make room.
- **Keeper** — a player a team is allowed to retain across draft years
  instead of re-drafting (4 per team here); see `src/keepers.py`.
- **Rank order matters more than point values** — the product decision
  behind "Spearman rank correlation as primary metric" (PROJECT-PLAN.md:73):
  a draft board only has to order players correctly, not predict their exact
  point totals, because a draft/pickup choice is inherently a ranking choice
  among the available pool.
- **Replacement value / VORP** — a player's fantasy worth isn't their raw
  total, it's the surplus over what a freely available replacement at the
  same position would produce. Planned formula (PROJECT-PLAN.md:212-228,
  not yet implemented — `src/keeper.py` doesn't exist yet, Phase C):
  `keeperValue = projected_total − replacementLevel[position]`, where
  `replacementLevel[pos]` is the projected total of the Nth-ranked player at
  that position, N derived from 10 teams × starting slots (e.g. ~25th-ranked
  C, ~45th-ranked D, given 2C/2LW/2RW/4D + Util share). Whether keepers also
  cost a draft pick is `ASSUMED — needs confirmation` (an open
  PROJECT-PLAN.md Phase C1 TODO, lines 215-219 — league keeper-cost rules
  are blocked on the owner checking Yahoo settings; this item is not
  tracked in OPEN-QUESTIONS.md).

## 2. MoneyPuck data model

The single most important domain fact in this repo: MoneyPuck's file is
**game-level, per-situation**, not one row per player-game.

| Field | Meaning |
|---|---|
| Grain | one row per `(playerId, gameId, situation)` |
| `situation` values | `all`, `5on4`, `4on5`, `5on5`, `other` |
| `all` row | **already totals** every situation for that player-game — do not sum `all` + situation rows, that double-counts (`src/moneypuck.py:96-102` docstring) |
| `season` convention | int year of season *start*: `season=2025` means the 2025-26 season (`main.py:16`) |
| `gameDate` | int `YYYYMMDD`, not a date type |
| `I_F_` prefix | "individual for" — the player's own on-ice-for stats (their goals, their shots) |
| `onIce_` prefix | team-level stat while this player was on the ice (e.g. `onIce_corsiPercentage`) |
| `xGoals` | expected goals — shot-quality model output; `goals − xGoals` is a shooting-luck / regression-to-mean signal (positive = running hot), computed as `xgoals_surplus` at `src/features/mlFeatures.py:14` |
| `gameScore` | a single-number per-game performance rating |
| Corsi / Fenwick | shot-attempt (Corsi) and unblocked-shot-attempt (Fenwick) percentages — possession proxies, columns `onIce_corsiPercentage` / `onIce_fenwickPercentage` |
| High-danger shots | shots from high-danger ice; `high_danger_rate = I_F_highDangerShots / I_F_shotsOnGoal` (`src/features/mlFeatures.py:15`) |

The repo never reads all ~150 raw columns — it reads a fixed 22-column
subset, `GAME_COLUMNS` at `src/moneypuck.py:26-33`, specifically to keep the
2.6 GB history file loadable in memory. Verified list (2026-07-05):
`playerId, name, gameId, season, gameDate, position, situation, icetime,
gameScore, onIce_corsiPercentage, onIce_fenwickPercentage, I_F_goals,
I_F_primaryAssists, I_F_secondaryAssists, I_F_points, I_F_xGoals,
I_F_shotsOnGoal, I_F_hits, shotsBlockedByPlayer, I_F_oZoneShiftStarts,
I_F_dZoneShiftStarts, I_F_highDangerShots`.

PPP/SHP derivation (`src/fantasyPoints.py:29-57`, pinned by
`tests/test_fantasyPoints.py:38-59`): PPP = `I_F_points` summed over that
player-game's `5on4` rows; SHP = summed over `4on5` rows. 5-on-3 points have
nowhere to land except the `other` situation bucket, so they are *not*
counted as PPP — a documented, accepted slight undercount. Acceptance check
recorded in PROJECT-PLAN.md:133-135: running the 2023-24 season through the
pipeline reproduces Matthews 69G/38A and McDavid 32G/100A exactly; McDavid's
PPP comes out 42 vs the official 44 (source: PROJECT-PLAN.md's recorded
check, not independently re-verified here — official NHL totals are
external and UNVERIFIED from this repo).

**Data license** (as of 2026-07-05): MoneyPuck's download page redirects
automated scrapers to a data-license notice, so there is deliberately no
auto-downloader in this repo (`src/moneypuck.py:1-6`). Refreshing
`data/raw/moneypuck_current.csv` is a manual browser download from
https://moneypuck.com/data.htm ; `checkCurrentFreshness()`
(`src/moneypuck.py:36-46`) nags once the file is more than `STALE_DAYS = 3`
days old. Verified today: it printed "moneypuck_current.csv is 93 days
old…" (data/raw file dated Apr 3, run July 5 — offseason staleness is
expected).

## 3. Scoring approximation ledger — one path

`moneypuckGamePoints` (`src/fantasyPoints.py:29-57`) is the single skater
scoring function, reading `SKATER_WEIGHTS`. It omits `plusMinus` and
`gameWinningGoals` — MoneyPuck game logs don't carry them directly — a
documented ~5% approximation, accepted (`src/fantasyPoints.py:1-3`,
PROJECT-PLAN.md:66-67, 318-319). It is used for both the canonical ML label
and player-season aggregation (all of `mlFeatures.py`, `buildPlayerSeasons`)
and the heuristic ranker input.

The old NHL-API scoring path, `calculateSkaterPoints`, was deleted July 2026
when the pickup pipeline went MoneyPuck-only — it is no longer live code.

## 4. NHL API (`api-web.nhle.com/v1`, no auth)

| Endpoint | Used for | Behavior |
|---|---|---|
| `/standings/now` | team abbreviations (`getTeamNames`, `src/nhlAPI.py:24-33`) | names arrive as `{'default': ...}` dicts, not plain strings |
| `/roster/{team}/current` | per-team roster (`getRosterData`, `src/nhlAPI.py:7-22`) | 429 → `time.sleep(5)` and retry (line 13) |
| `/player/{id}/landing` | per-player season/last-5 stats (`getPlayerStats`, `src/nhlAPI.py:35-49`) | 429 → `time.sleep(15)` and retry (line 41); does **not** indicate whether the player is currently active — must cross-reference against roster data (March 2026 lesson, PROJECT-PLAN.md:349) |

Player names throughout the NHL API responses come as `{'default': ...}`
(and `firstName`/`lastName`) dicts, flattened to `full_name` by
`dataProcessing.flattenPlayerNames` (per discovery dossier; not re-read in
full here — treat as established). Community-maintained endpoint docs (no
official NHL docs exist): https://gitlab.com/dword4/nhlapi . Headshot image
URL pattern, `api_export.py:25`: `https://assets.nhle.com/mugs/nhl/20252026/{player_id}.png`
— note the season string is hardcoded, same debt class as
`src/dataProcessing.py:71`'s hardcoded `20252026` literal (Phase E fix,
PROJECT-PLAN.md:53).

## 5. Yahoo API

`yahoo_fantasy_api` + `yahoo_oauth`; OAuth session built from
`oauth2.json` at repo root (`src/yahooAPI.py:10`) — **never quote this
file's contents in any output**; it is untracked and gitignored (verified
`git ls-files .env oauth2.json` returns empty). League handle:
`gm.to_league('nhl.l.33072')` (`src/yahooAPI.py:12`).

Yahoo rosters return **display names**, not NHL player ids, so every
Yahoo-sourced name needs fuzzy matching to the NHL id space: rapidfuzz
`process.extractOne(name, candidates, score_cutoff=85)`
(`src/yahooAPI.py:31`, reused identically in `src/keepers.py:53` for keeper
names). A cutoff of 85 is the one fuzzy-match tolerance used everywhere in
this repo; unmatched names print a "No good match found" warning and are
dropped rather than guessed.

**Keeper lists are not exposed by the Yahoo API before draft day** — this is
why `src/keepers.py` reads a hand-maintained `data/raw/keepers.csv`
(`player_name` column) instead of querying the league (module header,
`src/keepers.py:1-11`). `loadKeepers()` raises rather than silently
succeeding on an empty file ("an empty keeper list silently drafts
everyone", `src/keepers.py:36`).

## 6. ML domain semantics

- **"Heating up" / "cooling down"** — labels built in
  `src/features/mlFeatures.py::buildLabel` (lines 44-56) from `next_5_avg`,
  the player's mean fantasy points over their *next 5 games* (a
  reverse-rolling-then-shifted window). That value is converted to a
  **percentile against every other player in the same season**
  (`next_5_percentile`, line 51) — not against the player's own history.
  `is_heating_up = percentile ≥ 0.75`, `is_cooling_down = percentile ≤ 0.25`.
- **Why league-relative, not self-relative** — verbatim rationale comment at
  `src/features/mlFeatures.py:46-51`: a self-relative threshold lets
  low-output players (the example given is shot-blocking defensemen) trigger
  "heating up" on ordinary block/hit variance that never produces
  fantasy-relevant totals; percentile against the full field ties the label
  to actual absolute value.
- **Why the draft model targets PPG, not totals** — PROJECT-PLAN.md:71-72:
  season totals conflate skill with injury luck (a great player who misses
  30 games looks mediocre by total points); the draft target is next-season
  fantasy points-per-game, with projected totals only shown for readability
  as `PPG × 78`.
- **Why splits are by season, never random rows** — random row splits leak
  future information about a player's later-season performance into
  training via other rows from the *same* player-season; the house rule
  (PROJECT-PLAN.md:33, 191) is season-boundary splits only (e.g. pickups
  train ≤2022 / val 2023; draft train ≤2021 / val 2022-2023 / test 2024,
  test season touched once). `season_avg_so_far` in
  `buildRollingFeatures` is deliberately `shift(1)`-ed before its expanding
  mean (`src/features/mlFeatures.py:37-40`) — a same-day leakage guard so a
  game's own result can't leak into its own "season so far" feature.
- **Typical magnitudes** (July 3, 2026 retrain on the corrected
  full-league-weight label; canonical record of the exact AUCs:
  `fht-quality-gates` §3 golden inventory, sourced from
  PROJECT-PLAN.md:376-379 — pickup val ≈0.73, cooling val ≈0.64, small
  train/val gap). The fuller label (hits/blocks/PPP/SHP included) proved
  *more* learnable than the earlier G/A/SOG-only label because hits/blocks
  are stable, role-driven stats with less shooting-luck noise.
  `src/backtest.py:34` fixes `HOT_PERCENTILE = 0.75` to mirror this same
  training threshold; the free-agent pool's hit-rate base rate is **25% by
  construction** (the label's own cold/hot split), printed alongside the
  model's and a naive last-10-games baseline's hit rates at
  `src/backtest.py:107-112`.

## When NOT to use this skill

- How to actually run training/prediction/backtest commands, venv setup, or
  CLI flags → **fht-operations**.
- Why the codebase is shaped the way it is (module boundaries, train/predict
  split, why MoneyPuck was chosen as the single stats source) →
  **fht-architecture-contract**.
- Test coverage expectations, what must be pinned by pytest, hygiene rules →
  **fht-quality-gates**.
- The known live test failure in `loadGameLogs`, or diagnosing a new bug →
  **fht-debugging-playbook**.
- Draft/keeper roadmap status, what's built vs. stubbed for Phase B/C →
  **fht-draft-campaign**.
- Open research directions (LSTM un-parking, feature ideas, tuning order) →
  **fht-research-frontier**.

## Provenance and maintenance

Re-run these to catch drift before trusting this document:

```
# Scoring weights (must match the table in section 1)
.\.venv\Scripts\python.exe -c "from src.fantasyPoints import SKATER_WEIGHTS; print(SKATER_WEIGHTS)"

# Column subset actually read from MoneyPuck files
.\.venv\Scripts\python.exe -c "from src.moneypuck import GAME_COLUMNS; print(GAME_COLUMNS)"

# Freshness nag threshold and live staleness state
.\.venv\Scripts\python.exe -c "from src import moneypuck; moneypuck.checkCurrentFreshness()"

# Scoring/label pinning tests still pass
.\.venv\Scripts\python.exe -m pytest tests/test_fantasyPoints.py -v

# Confirm PPP/SHP and league-scoring source line ranges haven't moved
grep -n "SKATER_WEIGHTS\|moneypuckGamePoints" src/fantasyPoints.py
grep -n "GAME_COLUMNS\|STALE_DAYS" src/moneypuck.py

# Confirm the hardcoded season literals (known debt, Phase E) are still there
grep -rn "20252026" src/ main.py api_export.py
```

Cross-check PROJECT-PLAN.md's "League Scoring Rules" section and Learning
Log whenever this file is next updated — that document is the authoritative,
owner-maintained source; this skill only mirrors what the code currently
implements.
