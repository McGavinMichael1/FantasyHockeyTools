# Keeper analyzer - design

Approved 2026-07-15. Adds a skater-only keeper pipeline for the owner's Yahoo
team. It ranks the four best keeper candidates with deterministic draft-model
projections and replacement value, then optionally displays one cached LLM
explanation of the recommendation on a dedicated frontend page.

## Decisions settled with owner

- Keep exactly **four** players.
- In the current scenario, keepers consume the final four draft picks: rounds
  **18, 17, 16, and 15**.
- V1 is **skaters only**. Goalies are intentionally excluded until the shared
  goalie scoring/ranking work exists elsewhere in the product.
- The frontend gets a dedicated **`/keeper`** page.
- The LLM narrative is a cached, roster-level response. It is generated at
  most once per season by default; page loads never call an LLM.
- The deterministic ranking is the source of truth. The LLM cannot alter the
  recommended players or their ordering.

## Scope and non-goals

In scope: retrieve the authenticated Yahoo team's current roster, resolve its
skaters to the draft-projection universe, calculate keeper value, write a
local ranking artifact, export it to the Next frontend, and generate one
optional short explanation.

Out of scope: goalie ranking or projection, a new keeper ML model, live
frontend API calls to Yahoo or an LLM, web-search-backed advice, league-wide
keeper discovery, and changes to the existing draft-summary workflow.

## Data flow

```text
Yahoo OAuth roster --+--> main.py keeper --> keeper_rankings.csv
                    |           |                  |
draft model/features +-----------+                  |
                                                   +--> build_keeper_summary.py
                                                   |        (one cached LLM response)
                                                   v
                                      keeper_summary.json
                                                   |
api_export.py --keeper-only <---------------------+
       |
       v
frontend_data.json --> /api/players --> /keeper
```

`main.py keeper` builds an explicitly **unfiltered** current-season projection
table before matching the roster. It must not rely on a draft-day CSV after
`keepers.csv` has removed announced league keepers. The existing draft model
and its next-season FP/G predictions remain the only skater projection source.

## 1. Roster retrieval and matching

`src/yahooAPI.py` gains a narrow `getMyRoster()` wrapper:

1. Get the authenticated team key with `League.team_key()`.
2. Retrieve `League.to_team(team_key).roster(League.current_week())`.
3. Return Yahoo's name, player id, eligible positions, selected position, and
   status without transforming away fields useful for auditing.

`src/keeper.py` owns roster resolution. It fuzzy-matches Yahoo display names
to the unfiltered projection table using the established RapidFuzz cutoff of
85, but preserves an audit row for every roster player. A failed or ambiguous
match is never silently omitted.

Only projected skaters at C, L, R, or D are eligible. Yahoo goalies receive an
explicit `excluded_reason = "Goalie analysis is not available in v1"`; unmatched
skaters receive `excluded_reason = "No confident projection match"`.

## 2. Keeper value

`src/keeper.py` contains pure, testable functions for replacement levels,
round-pick opportunity costs, and ranking. The draft model stays unchanged.

### Replacement levels

The 10-team active skater roster is 2C, 2LW, 2RW, 4D, plus two utility slots.
Twenty utility spots are apportioned proportionally to the base skater slots:

| Position | League starters | Utility share | Replacement rank |
| --- | ---: | ---: | ---: |
| C | 20 | 4 | 24 |
| L | 20 | 4 | 24 |
| R | 20 | 4 | 24 |
| D | 40 | 8 | 48 |

For each position, the replacement level is the projected total of the player
at that one-based rank in the all-player projection table. Keeper surplus is:

```text
raw_keeper_value = projected_total - replacement_level[position]
```

### Draft-pick opportunity cost

The four keeper slots always consume the same rounds (18, 17, 16, 15), so the
combined cost cannot change which four skaters maximize total raw keeper
surplus. It is still shown for decision transparency.

For each round, derive the cost from the average projected total in that
10-pick round band of the unfiltered draft board. Assign the cheapest cost
(round 18) to the strongest recommended keeper, then rounds 17, 16, and 15
in order. This makes individual net values reproducible; the team total is
invariant to the assignment.

```text
net_keeper_value = raw_keeper_value - assigned_round_pick_cost
```

The artifact also reports the total opportunity cost and total net value of
the recommended four. The round list is a named configuration value so it can
be updated when trades change the owner's actual final picks.

## 3. CLI artifacts and failure behavior

`python main.py keeper` will:

1. Load the trained draft model and build current, unfiltered skater
   projections.
2. Fetch the authenticated Yahoo roster and resolve it against projections.
3. Calculate values and write `data/processed/keeper_rankings.csv`.
4. Print the top four plus clearly separated excluded/unmatched roster rows.

The CSV includes player identity and position, projection/last-season context,
confidence and model factors where available, replacement level, raw and net
keeper value, assigned cost round, rank, recommendation flag, and exclusion
reason.

Missing Yahoo credentials, a missing draft model/data prerequisite, a roster
lookup failure, or zero resolved skaters fails with a clear actionable CLI
message and does not emit a misleading recommendation. A stale or missing
keeper artifact is non-fatal to the existing frontend pages.

`api_export.py --keeper-only` updates the `keeper` section of
`frontend_data.json` without invoking the pickup/cooling export work. This
keeps the keeper refresh path independent of unrelated live-data/model
prerequisites.

## 4. Cached LLM narrative

`scripts/build_keeper_summary.py` is a separate, explicit command. It reads
the keeper CSV and makes **one** Anthropic request containing only local,
deterministic context for the recommended four: ranking, keeper value,
replacement level, assigned round cost, projected FP/G and total, last-season
FP/G, confidence, and model factors.

It writes the gitignored cache:

```json
{
  "season": "2026-27",
  "candidate_ids": [1, 2, 3, 4],
  "summary": "...",
  "generated_at": "...",
  "model": "..."
}
```

Rules:

- No web search and no frontend/server-side on-demand call.
- If a cache exists for the same target season, the default command prints the
  cache status and makes **no** LLM request.
- `--refresh` is required to deliberately replace an existing seasonal cache.
- Missing `ANTHROPIC_API_KEY`, an API error, or invalid response leaves the
  prior valid cache intact and returns a clear error.
- `api_export.py --keeper-only` merges the optional cache. Missing/corrupt
  cache exports `summary: null`; rankings remain available.

This reuses the existing Anthropic dependency and secret convention, but does
not modify the in-progress draft-summary files.

## 5. Frontend

Add a dedicated `/keeper` route using the existing `/api/players` endpoint and
the `keeper` section in `frontend_data.json`. A small navigation link from The
Rink reaches the page.

The page contains:

- A top-four Keep section, ordered by deterministic recommendation.
- Player cards/table values: projected FP/G and total, position replacement
  level, raw keeper surplus, assigned pick cost, net keeper value, confidence,
  and model factors.
- A sortable full table of matched rostered skaters, so omitted candidates are
  explainable.
- The cached roster-level narrative, or an unobtrusive "not generated yet"
  state.
- A visible note that goalies are intentionally excluded from v1, plus an
  excluded/unmatched roster audit section.

The route must safely render older `frontend_data.json` snapshots that lack a
`keeper` section.

## 6. Testing and acceptance gates

Add pure-function pytest coverage for:

- positional replacement levels and one-based cutoff selection;
- round-band opportunity-cost calculation and deterministic cost assignment;
- ranking order, exactly-four recommendation limit, and excluded-player audit;
- seasonal-cache detection (no LLM call required).

Network wrappers and Anthropic calls are not unit-tested, following the repo's
testing doctrine. Verification also includes a manually inspected output from
the owner's real roster: all four candidates must be actual rostered skaters,
the pick rounds must be 18/17/16/15, and no goalie may appear as recommended.

Before landing the feature, update `PROJECT-PLAN.md` with Phase C status and
the recorded validation result. Preserve the unrelated dirty
draft-explainability worktree changes.
