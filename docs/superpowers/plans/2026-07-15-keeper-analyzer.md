# Keeper Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build a skater-only Yahoo keeper analyzer that recommends four players deterministically, exports a dedicated /keeper page, and optionally displays one season-cached LLM rationale.

**Architecture:** A new pure keeper module resolves the authenticated Yahoo roster against all current draft-model projections before any announced-keeper or draft display filtering. It calculates positional replacement surplus and late-round opportunity costs, while main.py writes the ranking audit. A lightweight exporter merges the CSV and optional cached summary into the existing frontend JSON; the new Next route reads only that JSON.

**Tech Stack:** Python 3.14 venv, pandas, RapidFuzz, existing XGBoost draft model, existing Anthropic SDK, pytest, Next.js 16, React 18, TypeScript 5, CSS modules.

## Global Constraints

- Run Python as .\.venv\Scripts\python.exe; never use system Python.
- Do not add a keeper ML model, a dependency, a MoneyPuck downloader, or any live browser/frontend call to Yahoo or an LLM.
- Use the current draft model as the skater projection source. The keeper path must build projections before applying the 20-GP draft-display filter or the league-wide keepers.csv filter.
- Recommend exactly four resolved C/L/R/D skaters when four or more resolve. Goalies must remain visible only as excluded audit rows.
- Use KEEPER_ROUNDS = (18, 17, 16, 15), ordered from cheapest cost to most expensive cost.
- Use RapidFuzz cutoff 85 and preserve every Yahoo player as an audit row, including unmatched and ambiguous rows.
- The LLM response is display-only, has no web-search tool, is cached after a successful response, and defaults to no same-season refresh.
- Do not stage data files, JSON caches, model files, oauth2.json, environment variables, or unrelated dirty draft-explainability files.
- Add pytest only for pure functions. Do not add Yahoo or Anthropic network tests.
- Retain the existing draft behavior and leave src/models/draft.py and src/features/draft.py unchanged.

---

## File Structure

### Create

- src/keeper.py — pure Yahoo-name resolution, keeper math, audit rows, and ranking metadata.
- scripts/build_keeper_summary.py — one-call seasonal cache builder with no web search.
- tests/test_keeper.py — pure replacement, pick cost, matching, audit, and ranking tests.
- tests/test_keeper_summary.py — pure cache and prompt tests.
- tests/test_keeper_export.py — temporary-file export-contract tests.
- frontend/src/app/keeper/page.tsx — dedicated page.
- frontend/src/components/rink/KeeperBoard.tsx — cards, sortable table, narrative, and audit UI.
- frontend/src/components/rink/KeeperBoard.module.css — keeper-only hierarchy and responsive layout.

### Modify

- src/yahooAPI.py — add getMyRoster without changing all-team roster lookup.
- main.py — extract unfiltered current projections and add keeper CLI.
- api_export.py — add keeper serialization and --keeper-only mode.
- frontend/src/app/api/players/route.ts — normalize keeper to null for old snapshots.
- frontend/src/types/player.ts — add keeper API types.
- frontend/src/app/page.tsx and frontend/src/app/page.module.css — link to /keeper.
- PROJECT-PLAN.md — record an accurate Phase C implementation/validation status after real-roster verification.

## Task 1: Add the pure keeper-value engine

**Files:**

- Create: src/keeper.py
- Create: tests/test_keeper.py

**Interfaces:**

- Consumes a projections DataFrame with playerId, full_name, position, projected_total, projected_fpPerGame, fpPerGame, gamesPlayed, age, delta_vs_last, confidence, and factor_1 through factor_6.
- Consumes Yahoo roster dictionaries containing name, player_id, eligible_positions, selected_position, status, and position_type.
- Produces KeeperAnalysis(players, replacement_levels, round_pick_costs, total_raw_keeper_value, total_opportunity_cost, total_net_keeper_value).
- Exposes KEEPER_COUNT = 4, KEEPER_ROUNDS = (18, 17, 16, 15), REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48}, and resolve_roster plus rank_keepers.

- [ ] **Step 1: Write the failing math and audit tests**

~~~python
# tests/test_keeper.py
import pandas as pd

from src import keeper


def _board():
    rows = []
    for position, count, top_total in [
        ("C", 30, 200), ("L", 30, 180), ("R", 30, 160), ("D", 90, 220),
    ]:
        for index in range(count):
            rows.append({
                "playerId": len(rows) + 1,
                "full_name": f"{position} Player {index + 1}",
                "position": position,
                "projected_total": float(top_total - index),
                "projected_fpPerGame": 3.0,
                "fpPerGame": 2.7,
                "gamesPlayed": 70,
                "age": 25.0,
                "delta_vs_last": 0.3,
                "confidence": 90,
            })
    return pd.DataFrame(rows)


def test_replacement_levels_use_one_based_league_cutoffs():
    assert keeper.replacement_levels(_board()) == {
        "C": 177.0, "L": 157.0, "R": 137.0, "D": 173.0,
    }


def test_round_pick_costs_average_exact_ten_pick_bands():
    board = pd.DataFrame({
        "playerId": range(1, 181),
        "full_name": [f"Player {number}" for number in range(1, 181)],
        "position": ["C"] * 180,
        "projected_total": [float(200 - index) for index in range(180)],
    })
    costs = keeper.round_pick_costs(board)
    assert costs[18] == 25.5
    assert costs[15] == 55.5


def test_rank_keepers_preserves_goalie_and_unmatched_audit_rows():
    roster = [
        {"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"], "selected_position": "C", "status": "", "position_type": "P"},
        {"name": "L Player 1", "player_id": "y2", "eligible_positions": ["LW"], "selected_position": "LW", "status": "", "position_type": "P"},
        {"name": "R Player 1", "player_id": "y3", "eligible_positions": ["RW"], "selected_position": "RW", "status": "", "position_type": "P"},
        {"name": "D Player 1", "player_id": "y4", "eligible_positions": ["D"], "selected_position": "D", "status": "", "position_type": "P"},
        {"name": "Goalie Name", "player_id": "y5", "eligible_positions": ["G"], "selected_position": "G", "status": "", "position_type": "G"},
        {"name": "Missing Name", "player_id": "y6", "eligible_positions": ["C"], "selected_position": "C", "status": "", "position_type": "P"},
    ]

    analysis = keeper.analyze_keepers(roster, _board())
    recommended = analysis.players[analysis.players["is_recommended"]].sort_values("keeper_rank")

    assert len(recommended) == 4
    assert recommended["assigned_round"].tolist() == [18, 17, 16, 15]
    assert recommended["full_name"].tolist() == ["D Player 1", "C Player 1", "L Player 1", "R Player 1"]
    goalie = analysis.players.loc[analysis.players["yahoo_name"] == "Goalie Name"].iloc[0]
    unmatched = analysis.players.loc[analysis.players["yahoo_name"] == "Missing Name"].iloc[0]
    assert goalie["excluded_reason"] == "Goalie analysis is not available in v1"
    assert unmatched["excluded_reason"] == "No confident projection match"
~~~

- [ ] **Step 2: Run the test before implementation**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper.py -v
~~~

Expected: collection fails because src.keeper does not exist.

- [ ] **Step 3: Implement the complete deterministic engine**

~~~python
# src/keeper.py
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import process

KEEPER_COUNT = 4
KEEPER_ROUNDS = (18, 17, 16, 15)
REPLACEMENT_RANKS = {"C": 24, "L": 24, "R": 24, "D": 48}
SKATER_POSITIONS = frozenset(REPLACEMENT_RANKS)
MATCH_SCORE_CUTOFF = 85
MATCH_AMBIGUITY_MARGIN = 2.0


@dataclass
class KeeperAnalysis:
    players: pd.DataFrame
    replacement_levels: dict[str, float]
    round_pick_costs: dict[int, float]
    total_raw_keeper_value: float
    total_opportunity_cost: float
    total_net_keeper_value: float


def target_season_label(feature_season: int) -> str:
    start = feature_season + 1
    return f"{start}-{str(start + 1)[-2:]}"


def replacement_levels(projections: pd.DataFrame) -> dict[str, float]:
    levels = {}
    for position, rank in REPLACEMENT_RANKS.items():
        board = (projections[projections["position"] == position]
                 .sort_values("projected_total", ascending=False)
                 .reset_index(drop=True))
        if len(board) < rank:
            raise ValueError(f"need {rank} projected {position}s for replacement level")
        levels[position] = float(board.iloc[rank - 1]["projected_total"])
    return levels


def round_pick_costs(projections: pd.DataFrame, rounds=KEEPER_ROUNDS, teams=10) -> dict[int, float]:
    board = projections.sort_values("projected_total", ascending=False).reset_index(drop=True)
    costs = {}
    for round_number in rounds:
        start = (round_number - 1) * teams
        band = board.iloc[start:start + teams]
        if len(band) != teams:
            raise ValueError(f"need {round_number * teams} projections to price round {round_number}")
        costs[round_number] = float(band["projected_total"].mean())
    return costs


def _is_goalie(player: dict) -> bool:
    return (
        "G" in set(player.get("eligible_positions") or [])
        or player.get("selected_position") == "G"
        or player.get("position_type") == "G"
    )


def resolve_roster(roster: list[dict], projections: pd.DataFrame) -> pd.DataFrame:
    names = projections["full_name"].tolist()
    rows = []
    for player in roster:
        base = {
            "yahoo_player_id": str(player.get("player_id", "")),
            "yahoo_name": player["name"],
            "eligible_positions": player.get("eligible_positions") or [],
            "selected_position": player.get("selected_position"),
            "yahoo_status": player.get("status") or "",
            "match_score": pd.NA,
            "match_status": "unmatched",
            "excluded_reason": None,
        }
        if _is_goalie(player):
            rows.append({**base, "match_status": "goalie",
                         "excluded_reason": "Goalie analysis is not available in v1"})
            continue
        matches = process.extract(player["name"], names, score_cutoff=MATCH_SCORE_CUTOFF, limit=2)
        if not matches:
            rows.append({**base, "excluded_reason": "No confident projection match"})
            continue
        best_name, best_score, best_index = matches[0]
        if len(matches) == 2 and best_score - matches[1][1] < MATCH_AMBIGUITY_MARGIN:
            rows.append({**base, "match_score": float(best_score), "match_status": "ambiguous",
                         "excluded_reason": "Ambiguous projection match"})
            continue
        projection = projections.iloc[best_index].to_dict()
        rows.append({**base, **projection, "match_score": float(best_score), "match_status": "matched"})
    resolved = pd.DataFrame(rows)
    # Goalies/unmatched rows still need every projection column so ranking and
    # export can represent them as null rather than raising a KeyError.
    for column in projections.columns:
        if column not in resolved.columns:
            resolved[column] = pd.NA
    return resolved


def rank_keepers(resolved: pd.DataFrame, projections: pd.DataFrame,
                 keeper_count=KEEPER_COUNT, keeper_rounds=KEEPER_ROUNDS) -> KeeperAnalysis:
    players = resolved.copy()
    matched = ((players["match_status"] == "matched")
               & players["position"].isin(SKATER_POSITIONS))
    levels = replacement_levels(projections)
    costs = round_pick_costs(projections, keeper_rounds)
    players["replacement_level"] = pd.NA
    players["raw_keeper_value"] = pd.NA
    players["keeper_rank"] = pd.NA
    players["is_recommended"] = False
    players["assigned_round"] = pd.NA
    players["pick_cost"] = pd.NA
    players["net_keeper_value"] = pd.NA
    players.loc[matched, "replacement_level"] = players.loc[matched, "position"].map(levels)
    players.loc[matched, "raw_keeper_value"] = (
        players.loc[matched, "projected_total"] - players.loc[matched, "replacement_level"]
    )
    choice_indexes = (players[matched]
                      .sort_values(["raw_keeper_value", "projected_total", "playerId"],
                                   ascending=[False, False, True])
                      .head(keeper_count).index.tolist())
    for rank, (row_index, round_number) in enumerate(zip(choice_indexes, keeper_rounds), start=1):
        players.loc[row_index, ["keeper_rank", "is_recommended", "assigned_round", "pick_cost"]] = [
            rank, True, round_number, costs[round_number],
        ]
        players.loc[row_index, "net_keeper_value"] = (
            players.loc[row_index, "raw_keeper_value"] - costs[round_number]
        )
    recommended = players[players["is_recommended"]]
    return KeeperAnalysis(
        players=players,
        replacement_levels=levels,
        round_pick_costs=costs,
        total_raw_keeper_value=float(recommended["raw_keeper_value"].sum()),
        total_opportunity_cost=float(recommended["pick_cost"].sum()),
        total_net_keeper_value=float(recommended["net_keeper_value"].sum()),
    )


def analyze_keepers(roster: list[dict], projections: pd.DataFrame,
                    keeper_count=KEEPER_COUNT, keeper_rounds=KEEPER_ROUNDS) -> KeeperAnalysis:
    return rank_keepers(resolve_roster(roster, projections), projections, keeper_count, keeper_rounds)
~~~

Keep fewer-than-four resolved skaters as a visible shortfall in the analysis. Main should fail only when zero skaters resolve, not erase partial audit evidence.

- [ ] **Step 4: Run the focused tests and import smoke**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper.py -v
.\.venv\Scripts\python.exe -c "from src import keeper; print(keeper.KEEPER_ROUNDS)"
~~~

Expected: all keeper tests pass and the import prints (18, 17, 16, 15).

- [ ] **Step 5: Commit Task 1**

~~~powershell
git add src/keeper.py tests/test_keeper.py
git commit -m "feat: add keeper value engine"
~~~

## Task 2: Add authenticated Yahoo roster retrieval and CLI output

**Files:**

- Modify: src/yahooAPI.py
- Modify: main.py

**Interfaces:**

- Consumes getMyRoster and keeper.analyze_keepers from Task 1.
- Produces buildCurrentDraftProjections() and runKeeper(), plus data/processed/keeper_rankings.csv.

- [ ] **Step 1: Add the owned-team Yahoo wrapper without changing pickup lookup**

~~~python
# src/yahooAPI.py
def getMyRoster(lg=None) -> list[dict]:
    """Roster for the Yahoo team authenticated by oauth2.json."""
    league = lg or getLeague()
    team_key = league.team_key()
    if not team_key:
        raise RuntimeError("Could not find authenticated Yahoo team in nhl.l.33072")
    return league.to_team(team_key).roster(league.current_week())
~~~

Leave getRosteredIds unchanged because pickup filtering still needs every league roster. Do not add a Yahoo API unit test.

- [ ] **Step 2: Extract all current draft model projections before either draft filter**

Move main.py lines 156-204 into the following helper. Preserve all existing age, projected total, delta, confidence, and SHAP-factor calculations exactly.

~~~python
# main.py
def buildCurrentDraftProjections() -> pd.DataFrame:
    """All current-season draft-model projections before draft-only filters."""
    df = loadPlayerSeasonFeatures()
    current = df[df["season"] == CURRENT_SEASON].copy()
    current["projected_fpPerGame"] = draftModel.predict(current)

    rankings = current[[
        "playerId", "full_name", "position", "gamesPlayed",
        "fpPerGame", "projected_fpPerGame",
    ]].copy()
    rankings["age"] = current["age_at_season_start"] + 1
    rankings["projected_total"] = rankings["projected_fpPerGame"] * 78
    rankings["delta_vs_last"] = rankings["projected_fpPerGame"] - rankings["fpPerGame"]

    seasons_of_history = (
        df[df["season"] <= CURRENT_SEASON].groupby("playerId")["season"].nunique()
    )
    rankings["confidence"] = [
        draft_explain.compute_confidence(
            seasons_of_history=int(seasons_of_history.get(pid, 1)),
            feature_gp=int(games_played),
            age=age,
            projection=float(projection),
            fp_w3=fp_w3,
        )
        for pid, games_played, age, projection, fp_w3 in zip(
            current["playerId"], current["gamesPlayed"], rankings["age"],
            current["projected_fpPerGame"], current["fp_w3"],
        )
    ]
    contributions = draftModel.shap_contributions(current)
    factor_columns = [f"factor_{number}" for number in range(1, 7)]
    factor_rows = []
    for index in current.index:
        factors = draft_explain.top_factors(contributions.loc[index].to_dict(), top_n=3)
        cells = [
            json.dumps({"label": factor["label"], "value": round(factor["value"], 4)})
            for factor in factors
        ]
        factor_rows.append((cells + [""] * len(factor_columns))[:len(factor_columns)])
    for column, values in zip(factor_columns, zip(*factor_rows)):
        rankings[column] = list(values)
    return rankings.sort_values("projected_fpPerGame", ascending=False).reset_index(drop=True)
~~~

Update runDraft to call this helper, then apply its existing gamesPlayed >= 20 display filter and existing keepers.filterOutKeepers logic. That preserves the draft board while keeper analysis deliberately includes injury-shortened skaters.

- [ ] **Step 3: Add runKeeper and parser dispatch**

~~~python
# main.py imports
from src import keeper

KEEPER_RANKINGS_PATH = os.path.join("data", "processed", "keeper_rankings.csv")


def runKeeper():
    """Analyze the authenticated Yahoo roster as four skater keepers."""
    projections = buildCurrentDraftProjections()
    try:
        roster = yahooAPI.getMyRoster()
    except Exception as exc:
        raise RuntimeError(
            "Unable to retrieve your Yahoo roster. Check oauth2.json and the authenticated league team."
        ) from exc

    analysis = keeper.analyze_keepers(roster, projections)
    resolved_count = int((analysis.players["match_status"] == "matched").sum())
    if resolved_count == 0:
        raise ValueError("No Yahoo roster skaters matched draft projections; no keeper ranking was written.")

    rankings = analysis.players.copy()
    rankings["target_season"] = keeper.target_season_label(CURRENT_SEASON)
    os.makedirs(os.path.dirname(KEEPER_RANKINGS_PATH), exist_ok=True)
    rankings.to_csv(KEEPER_RANKINGS_PATH, index=False)

    recommended = rankings[rankings["is_recommended"]].sort_values("keeper_rank")
    print("\n=== Keeper recommendations ===")
    print(recommended[[
        "keeper_rank", "full_name", "position", "projected_total",
        "raw_keeper_value", "assigned_round", "pick_cost", "net_keeper_value",
    ]].to_string(index=False))
    if len(recommended) < keeper.KEEPER_COUNT:
        print(f"WARNING: only {len(recommended)} resolved skaters; cannot fill all {keeper.KEEPER_COUNT} keeper slots.")
    excluded = rankings[rankings["excluded_reason"].notna()]
    if not excluded.empty:
        print("\n=== Excluded roster rows ===")
        print(excluded[["yahoo_name", "excluded_reason"]].to_string(index=False))
~~~

Add sub.add_parser("keeper", help="rank my Yahoo roster skaters as four keeper choices") and the matching runKeeper branch. Retain the plural keepers import only for draft-pool filtering.

- [ ] **Step 4: Run non-network checks**

~~~powershell
.\.venv\Scripts\python.exe -c "import main; print(hasattr(main, 'runKeeper'))"
.\.venv\Scripts\python.exe main.py --help
~~~

Expected: import prints True and help lists keeper. Do not call main.py keeper until the local draft model, player-season cache, and Yahoo auth are present.

- [ ] **Step 5: Commit Task 2**

~~~powershell
git add src/yahooAPI.py main.py
git commit -m "feat: add Yahoo keeper ranking command"
~~~

## Task 3: Add the no-search, season-cached LLM narrative

**Files:**

- Create: scripts/build_keeper_summary.py
- Create: tests/test_keeper_summary.py

**Interfaces:**

- Consumes data/processed/keeper_rankings.csv.
- Produces data/processed/keeper_summary.json with season, candidate_ids, summary, generated_at, and model.
- Exposes cache_is_current(cache, target_season) and build_prompt(recommended, target_season).

- [ ] **Step 1: Write failing cache/prompt tests**

~~~python
# tests/test_keeper_summary.py
from scripts import build_keeper_summary as summaries


def test_same_season_cache_reuses_without_key_or_request():
    cache = {
        "season": "2026-27",
        "candidate_ids": [1, 2, 3, 4],
        "summary": "Keep these four.",
        "generated_at": "2026-07-15T00:00:00+00:00",
        "model": "test",
    }
    assert summaries.cache_is_current(cache, "2026-27") is True
    assert summaries.cache_is_current(cache, "2027-28") is False
    assert summaries.should_generate(cache, "2026-27", force=False) is False
    assert summaries.should_generate(cache, "2026-27", force=True) is True


def test_prompt_is_local_data_only_and_cannot_reorder_candidates():
    rows = [{
        "keeper_rank": 1, "full_name": "Player One", "position": "C",
        "projected_fpPerGame": 3.1, "projected_total": 241.8,
        "fpPerGame": 2.9, "gamesPlayed": 72, "age": 25.0, "delta_vs_last": 0.2,
        "raw_keeper_value": 60.0,
        "assigned_round": 18, "pick_cost": 20.0,
        "net_keeper_value": 40.0, "confidence": 92,
        "factor_1": '{"label": "Last-season FP/game", "value": 0.42}',
    }]
    prompt = summaries.build_prompt(rows, "2026-27")
    assert "Player One" in prompt
    assert "Last-season FP/game" in prompt
    assert "web search" not in prompt.lower()
    assert "do not change the recommendation order" in prompt.lower()
~~~

- [ ] **Step 2: Run the test before implementation**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper_summary.py -v
~~~

Expected: import fails because scripts.build_keeper_summary does not exist.

- [ ] **Step 3: Implement cache-first generation**

Import argparse, json, os, sys, datetime/timezone, pathlib.Path, and pandas at module scope; defer importing anthropic until after the cache/key checks so a cached invocation never requires the SDK or API key.

~~~python
# scripts/build_keeper_summary.py
MODEL = "claude-opus-4-8"
RANKINGS_PATH = os.path.join(REPO_ROOT, "data", "processed", "keeper_rankings.csv")
SUMMARY_PATH = os.path.join(REPO_ROOT, "data", "processed", "keeper_summary.json")


def cache_is_current(cache: dict | None, target_season: str) -> bool:
    return bool(cache and cache.get("season") == target_season and cache.get("summary"))


def should_generate(cache: dict | None, target_season: str, force: bool = False) -> bool:
    return force or not cache_is_current(cache, target_season)


def build_prompt(recommended: list[dict], target_season: str) -> str:
    def factors(row):
        labels = []
        for number in range(1, 7):
            cell = row.get(f"factor_{number}", "")
            if not cell:
                continue
            try:
                factor = json.loads(cell)
            except (TypeError, ValueError):
                continue
            labels.append(f"{factor['label']} ({float(factor['value']):+.2f})")
        return "; ".join(labels) or "none recorded"

    rows = []
    for row in recommended:
        rows.append(
            f"#{int(row['keeper_rank'])} {row['full_name']} ({row['position']}): "
            f"last season {float(row['fpPerGame']):.2f} FP/G in {int(row['gamesPlayed'])} GP; "
            f"age {float(row['age']):.1f}; {float(row['projected_fpPerGame']):.2f} projected FP/G, "
            f"{float(row['projected_total']):.1f} projected FP, "
            f"change {float(row['delta_vs_last']):+.2f} FP/G, "
            f"{float(row['raw_keeper_value']):.1f} replacement surplus, "
            f"round {int(row['assigned_round'])} cost {float(row['pick_cost']):.1f}, "
            f"{float(row['net_keeper_value']):.1f} net keeper value, "
            f"{int(row['confidence'])}/100 confidence, model factors: {factors(row)}."
        )
    return (
        f"You are explaining a fantasy-hockey keeper recommendation for {target_season}.\n"
        "Use only the deterministic information below. Do not browse, infer current news, "
        "or change the recommendation order. Write one concise 3-4 sentence blurb explaining "
        "why these four skaters should be kept. Respond only with the blurb.\n\n"
        + "\n".join(rows)
    )
~~~

In main(), load the ranking CSV, select is_recommended rows in keeper_rank order, and obtain the single target_season. Load JSON safely before checking ANTHROPIC_API_KEY. A valid same-season cache must print a reuse message and return successfully even when the environment variable is absent or candidate IDs have changed. Only an absent/invalid/new-season cache or --refresh can import anthropic and call:

~~~python
response = client.messages.create(
    model=MODEL,
    max_tokens=300,
    messages=[{"role": "user", "content": prompt}],
)
~~~

Do not pass tools. Validate non-empty text before writing. Write JSON atomically through a sibling temporary path and os.replace so an API/key/response failure leaves an earlier valid cache intact.

- [ ] **Step 4: Run cache checks**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper_summary.py -v
.\.venv\Scripts\python.exe scripts/build_keeper_summary.py --help
~~~

Expected: tests pass and help documents --refresh. With an existing same-season cache, the script exits successfully before checking credentials.

- [ ] **Step 5: Commit Task 3**

~~~powershell
git add scripts/build_keeper_summary.py tests/test_keeper_summary.py
git commit -m "feat: add cached keeper summary generator"
~~~

## Task 4: Export keeper data independently of pickup/cooling work

**Files:**

- Modify: api_export.py
- Modify: frontend/src/app/api/players/route.ts
- Create: tests/test_keeper_export.py

**Interfaces:**

- Consumes keeper_rankings.csv and optional keeper_summary.json.
- Produces top-level keeper: null or a section with season, generated_at, summary, summary_generated_at, summary_model, summary_matches_recommendation, totals, and a full audit players array.
- Produces export_keeper_only(), invoked by python api_export.py --keeper-only.

- [ ] **Step 1: Write the failing temporary-artifact export test**

~~~python
# tests/test_keeper_export.py
import json

import pandas as pd

import api_export


def test_keeper_export_keeps_recommendation_and_goalie_audit(tmp_path, monkeypatch):
    rankings = tmp_path / "keeper_rankings.csv"
    summary = tmp_path / "keeper_summary.json"
    pd.DataFrame([
        {
            "target_season": "2026-27", "yahoo_player_id": "y1", "yahoo_name": "Skater",
            "playerId": 7, "full_name": "Skater", "position": "C", "match_status": "matched",
            "excluded_reason": None, "gamesPlayed": 70, "fpPerGame": 2.1,
            "projected_fpPerGame": 2.5, "projected_total": 195.0, "age": 25.0,
            "delta_vs_last": 0.4, "confidence": 90, "replacement_level": 150.0,
            "raw_keeper_value": 45.0, "keeper_rank": 1, "is_recommended": True,
            "assigned_round": 18, "pick_cost": 20.0, "net_keeper_value": 25.0,
        },
        {
            "target_season": "2026-27", "yahoo_player_id": "g1", "yahoo_name": "Goalie",
            "match_status": "goalie", "excluded_reason": "Goalie analysis is not available in v1",
            "is_recommended": False,
        },
    ]).to_csv(rankings, index=False)
    summary.write_text(json.dumps({
        "season": "2026-27", "candidate_ids": [7], "summary": "Keep Skater.",
        "generated_at": "now", "model": "test",
    }), encoding="utf-8")
    monkeypatch.setattr(api_export, "KEEPER_RANKINGS_PATH", str(rankings))
    monkeypatch.setattr(api_export, "KEEPER_SUMMARY_PATH", str(summary))

    section = api_export.build_keeper_section()
    assert section["players"][0]["is_recommended"] is True
    assert section["players"][1]["excluded_reason"] == "Goalie analysis is not available in v1"
    assert section["summary"] == "Keep Skater."
~~~

- [ ] **Step 2: Run the test before serializer implementation**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper_export.py -v
~~~

Expected: failure because KEEPER_RANKINGS_PATH and build_keeper_section are absent.

- [ ] **Step 3: Add the complete export boundary**

Add KEEPER_RANKINGS_PATH and KEEPER_SUMMARY_PATH near the draft constants. Import ast, add a safe JSON loader, a nullable-number helper, and build_keeper_section beside build_draft_list. Each CSV row becomes one JSON player record; matched rows carry NHL headshots and draft fields, while goalie/unmatched rows use null projection fields and an empty headshot.

~~~python
def build_keeper_section():
    if not os.path.exists(KEEPER_RANKINGS_PATH):
        return None
    frame = pd.read_csv(KEEPER_RANKINGS_PATH)
    season = str(frame["target_season"].dropna().iloc[0])
    recommended_mask = frame["is_recommended"].fillna(False).astype(str).str.lower().eq("true")
    recommended = frame[recommended_mask].sort_values("keeper_rank")
    cache = _load_optional_json(KEEPER_SUMMARY_PATH)
    summary_is_current = bool(cache and cache.get("season") == season and cache.get("summary"))
    return {
        "season": season,
        "generated_at": pd.Timestamp.now().isoformat(),
        "summary": cache.get("summary") if summary_is_current else None,
        "summary_generated_at": cache.get("generated_at") if summary_is_current else None,
        "summary_model": cache.get("model") if summary_is_current else None,
        "summary_matches_recommendation": (
            cache.get("candidate_ids") == [int(value) for value in recommended["playerId"]]
            if summary_is_current else None
        ),
        "total_raw_keeper_value": _number(recommended["raw_keeper_value"].sum()),
        "total_opportunity_cost": _number(recommended["pick_cost"].sum()),
        "total_net_keeper_value": _number(recommended["net_keeper_value"].sum()),
        "players": [_keeper_player_record(row) for _, row in frame.iterrows()],
    }
~~~

Use this exact row mapper so the Python field names and Task 5 TypeScript
contract stay aligned:

~~~python
def _number(value):
    return None if pd.isna(value) else round(float(value), 3)


def _positions(value):
    if isinstance(value, list):
        return [str(position) for position in value]
    if pd.isna(value):
        return []
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return []
    return [str(position) for position in parsed] if isinstance(parsed, list) else []


def _boolean(value):
    return str(value).strip().lower() == "true"


def _keeper_player_record(row):
    player_id = None if pd.isna(row.get("playerId")) else int(row["playerId"])
    position = None if pd.isna(row.get("position")) else row["position"]
    return {
        "yahoo_player_id": str(row.get("yahoo_player_id", "")),
        "yahoo_name": row["yahoo_name"],
        "eligible_positions": _positions(row.get("eligible_positions")),
        "selected_position": None if pd.isna(row.get("selected_position")) else row["selected_position"],
        "yahoo_status": None if pd.isna(row.get("yahoo_status")) else row["yahoo_status"],
        "id": player_id,
        "full_name": None if pd.isna(row.get("full_name")) else row["full_name"],
        "positionCode": position,
        "headshot": get_headshot_url(player_id) if player_id is not None else "",
        "match_score": _number(row.get("match_score")),
        "match_status": row["match_status"],
        "excluded_reason": None if pd.isna(row.get("excluded_reason")) else row["excluded_reason"],
        "gamesPlayed": None if pd.isna(row.get("gamesPlayed")) else int(row["gamesPlayed"]),
        "last_fpPerGame": _number(row.get("fpPerGame")),
        "projected_fpPerGame": _number(row.get("projected_fpPerGame")),
        "projected_total": _number(row.get("projected_total")),
        "age": _number(row.get("age")),
        "delta_vs_last": _number(row.get("delta_vs_last")),
        "confidence": None if pd.isna(row.get("confidence")) else int(row["confidence"]),
        "factors": _parse_factors(row),
        "replacement_level": _number(row.get("replacement_level")),
        "raw_keeper_value": _number(row.get("raw_keeper_value")),
        "keeper_rank": None if pd.isna(row.get("keeper_rank")) else int(row["keeper_rank"]),
        "is_recommended": _boolean(row.get("is_recommended", False)),
        "assigned_round": None if pd.isna(row.get("assigned_round")) else int(row["assigned_round"]),
        "pick_cost": _number(row.get("pick_cost")),
        "net_keeper_value": _number(row.get("net_keeper_value")),
    }
~~~

Normal export_data adds the keeper section but remains otherwise unchanged. Implement export_keeper_only to load an existing frontend_data.json safely, preserve its top-level generated_at value so pickup/draft freshness is not falsely reset, replace only keeper, and write the result. Add argparse with --keeper-only. In the Next API route, explicitly return keeper: data.keeper ?? null and include keeper: null in both error fallbacks. Change dataAge calculation to prefer a valid top-level generated_at timestamp and fall back to file mtime; keeper-only export must not refresh the general data age.

- [ ] **Step 4: Run serializer and CLI checks**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper_export.py -v
.\.venv\Scripts\python.exe api_export.py --help
~~~

Expected: the test passes and --keeper-only appears in help. Once a keeper CSV exists, --keeper-only must not run MoneyPuck, NHL, pickup, cooling, or Yahoo operations.

- [ ] **Step 5: Commit Task 4**

~~~powershell
git add api_export.py frontend/src/app/api/players/route.ts tests/test_keeper_export.py
git commit -m "feat: export keeper analysis for frontend"
~~~

## Task 5: Build the dedicated Keeper Analysis route

**Files:**

- Modify: frontend/src/types/player.ts
- Modify: frontend/src/app/page.tsx
- Modify: frontend/src/app/page.module.css
- Create: frontend/src/app/keeper/page.tsx
- Create: frontend/src/components/rink/KeeperBoard.tsx
- Create: frontend/src/components/rink/KeeperBoard.module.css

**Interfaces:**

- Consumes keeper from the existing /api/players JSON response.
- Produces a page that renders data, a cache-missing state, and an audit without any live LLM/Yahoo request.

- [ ] **Step 1: Add exact TypeScript API contracts**

~~~ts
export interface KeeperPlayer {
  yahoo_player_id: string;
  yahoo_name: string;
  eligible_positions: string[];
  selected_position: string | null;
  yahoo_status: string | null;
  id: number | null;
  full_name: string | null;
  positionCode: Position | "G" | null;
  headshot: string;
  match_score: number | null;
  match_status: "matched" | "unmatched" | "ambiguous" | "goalie";
  excluded_reason: string | null;
  gamesPlayed: number | null;
  last_fpPerGame: number | null;
  projected_fpPerGame: number | null;
  projected_total: number | null;
  age: number | null;
  delta_vs_last: number | null;
  confidence: number | null;
  factors: DraftFactor[];
  replacement_level: number | null;
  raw_keeper_value: number | null;
  keeper_rank: number | null;
  is_recommended: boolean;
  assigned_round: number | null;
  pick_cost: number | null;
  net_keeper_value: number | null;
}

export interface KeeperAnalysis {
  season: string;
  generated_at: string;
  summary: string | null;
  summary_generated_at: string | null;
  summary_model: string | null;
  summary_matches_recommendation: boolean | null;
  total_raw_keeper_value: number | null;
  total_opportunity_cost: number | null;
  total_net_keeper_value: number | null;
  players: KeeperPlayer[];
}
~~~

- [ ] **Step 2: Add navigation and the cache-safe page**

Import Link from next/link in the root page and add a Keeper analysis anchor with href="/keeper" using a new tabLink CSS class. The new page uses the same Rink header classes and a Link back to "/". Its only fetch is /api/players.

~~~tsx
// frontend/src/app/keeper/page.tsx
interface KeeperApiResponse {
  keeper?: KeeperAnalysis | null;
  dataAge?: string;
  error?: string;
}

const [keeper, setKeeper] = useState<KeeperAnalysis | null>(null);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

useEffect(() => {
  fetch("/api/players")
    .then(async (response) => {
      const payload: KeeperApiResponse = await response.json();
      if (!response.ok && !payload.keeper) throw new Error(payload.error || "Could not load keeper data.");
      setKeeper(payload.keeper ?? null);
    })
    .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load keeper data."))
    .finally(() => setLoading(false));
}, []);
~~~

The missing keeper state must show these two commands:

~~~text
.\.venv\Scripts\python.exe main.py keeper
.\.venv\Scripts\python.exe api_export.py --keeper-only
~~~

- [ ] **Step 3: Implement KeeperBoard behavior and styles**

Filter data exactly as follows:

~~~tsx
const recommended = keeper.players
  .filter((player) => player.is_recommended)
  .sort((left, right) => (left.keeper_rank ?? Infinity) - (right.keeper_rank ?? Infinity));

const skaters = keeper.players.filter(
  (player) => player.match_status === "matched" && player.excluded_reason === null,
);

const audit = keeper.players.filter(
  (player) => player.match_status !== "matched" || player.excluded_reason !== null,
);
~~~

Render four Keep cards for recommended with Headshot, PositionChip only when positionCode is C/L/R/D, ScoreMeter when confidence is non-null, and projected total, replacement, raw surplus, round, cost, and net value. Render a sortable skater table using RinkTable.module.css controls/table classes. Render narrative text when summary is non-null; otherwise show Narrative not generated yet. If summary_matches_recommendation is false, show the existing cached text plus: Cached narrative was generated for an earlier ordering; refresh only if you deliberately want a new LLM request. Render audit names, positions, status, and exclusion reason below the table.

~~~css
/* frontend/src/components/rink/KeeperBoard.module.css */
.hero { max-width: 1160px; margin: 0 auto; padding: 28px 32px 12px; }
.keepGrid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.keepCard { padding: 16px; border: 1px solid var(--line); border-top: 4px solid var(--hot); border-radius: 10px; background: var(--boards); }
.narrative { margin-top: 18px; padding: 16px; border-left: 4px solid var(--cold); background: var(--ice); }
.audit { margin-top: 22px; color: var(--ink-2); }
@media (max-width: 900px) { .hero { padding: 20px 16px; } .keepGrid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 560px) { .keepGrid { grid-template-columns: 1fr; } }
~~~

Do not modify DraftBoard or add a JavaScript test framework.

- [ ] **Step 4: Type-check and build**

Run from frontend:

~~~powershell
npx tsc --noEmit
npm run build
~~~

Expected: TypeScript and Next production build succeed. If node_modules is absent, install existing pinned dependencies before these commands; do not add a package.

- [ ] **Step 5: Commit Task 5**

~~~powershell
git add frontend/src/types/player.ts frontend/src/app/page.tsx frontend/src/app/page.module.css frontend/src/app/keeper/page.tsx frontend/src/components/rink/KeeperBoard.tsx frontend/src/components/rink/KeeperBoard.module.css
git commit -m "feat: add keeper analysis page"
~~~

## Task 6: Verify the pipeline and record Phase C status

**Files:**

- Modify: PROJECT-PLAN.md

**Interfaces:**

- Consumes completed source, optional local cache, and frontend build.
- Produces validation evidence without committing generated artifacts.

- [ ] **Step 1: Run focused Python gates**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_keeper.py tests/test_keeper_summary.py tests/test_keeper_export.py -v
.\.venv\Scripts\python.exe -c "import main; from src import keeper; print(keeper.KEEPER_COUNT)"
.\.venv\Scripts\python.exe main.py --help
~~~

Expected: focused tests pass, import prints 4, and help lists keeper.

- [ ] **Step 2: Run the real roster and export flow when prerequisites exist**

~~~powershell
.\.venv\Scripts\python.exe main.py keeper
.\.venv\Scripts\python.exe api_export.py --keeper-only
~~~

Inspect the local CSV and JSON. Require exactly four recommended rows when at least four skaters resolve; require rounds 18, 17, 16, 15; require no goalie recommendation; and require a non-null keeper JSON section. If OAuth, the draft model, or prerequisite cache is absent, report that exact missing prerequisite instead of claiming a result.

- [ ] **Step 3: Validate season-sticky summary behavior without wasted calls**

When ANTHROPIC_API_KEY is intentionally available, run:

~~~powershell
.\.venv\Scripts\python.exe scripts/build_keeper_summary.py
.\.venv\Scripts\python.exe scripts/build_keeper_summary.py
.\.venv\Scripts\python.exe api_export.py --keeper-only
~~~

Expected: the first run writes one response after one request; the second run reports cache reuse with no request. Do not use --refresh during ordinary validation. Without a key, validate the deterministic page's Narrative not generated yet state.

- [ ] **Step 4: Build and visually inspect the frontend**

Run from frontend:

~~~powershell
npm run build
~~~

Manually inspect /keeper with a populated export and with an older JSON snapshot that lacks keeper. Verify four cards, sortable matched-skater table, audit rows, cached/narrative-missing states, keyboard table controls, and narrow-screen horizontal table behavior.

- [ ] **Step 5: Run full pytest and separate unrelated failures**

~~~powershell
.\.venv\Scripts\python.exe -m pytest -v
~~~

All keeper tests must pass. Preserve and report existing unrelated failures rather than folding them into this feature: the known tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations guard-order failure and any draft-summary assertion caused by the user's dirty draft-explainability worktree. Investigate any new keeper failure before proceeding.

- [ ] **Step 6: Record the truthful project state and commit docs only**

Update PROJECT-PLAN.md Phase C and the Learning Log with the focused test result, real-roster result only if Step 2 succeeded, the four late-round configuration, and the explicit skater-only goalie exclusion. Do not mark the real-roster milestone complete unless it was actually observed.

~~~powershell
git add PROJECT-PLAN.md
git commit -m "docs: record keeper analyzer validation"
~~~
