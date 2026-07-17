from copy import deepcopy
from datetime import datetime, timezone
import json

import pandas as pd
import pytest

from src import keeper, keeper_advisor


def _projection_board():
    rows = []
    for position, count, top_total in [
        ("C", 30, 240), ("L", 30, 230), ("R", 30, 220),
        ("D", 90, 250), ("G", 30, 270),
    ]:
        for index in range(count):
            rows.append({
                "playerId": len(rows) + 1,
                "full_name": f"{position} Player {index + 1}",
                "position": position,
                "projected_total": float(top_total - index),
                "projected_fpPerGame": 3.0,
                "projected_gp": 78 if position != "G" else 55,
                "fpPerGame": 2.7,
                "gamesPlayed": 70,
                "age": 24.0 + index / 10,
                "delta_vs_last": 0.3,
                "confidence": 88,
                "factor_1": '{"label":"Three-season form","value":0.4}',
            })
    return pd.DataFrame(rows)


def _rankings_and_histories():
    roster = [
        {"name": "D Player 1", "player_id": "y1", "eligible_positions": ["D"]},
        {"name": "C Player 1", "player_id": "y2", "eligible_positions": ["C"]},
        {"name": "L Player 1", "player_id": "y3", "eligible_positions": ["LW"]},
        {"name": "R Player 1", "player_id": "y4", "eligible_positions": ["RW"]},
        {"name": "G Player 1", "player_id": "y5", "eligible_positions": ["G"]},
        {"name": "Not Projected", "player_id": "y6", "eligible_positions": ["C"]},
    ]
    board = _projection_board()
    rankings = keeper.analyze_keepers(roster, board)
    rankings["target_season"] = "2026-27"
    skater_history = pd.DataFrame([
        {"playerId": 91, "season": 2023, "gamesPlayed": 70, "fpPerGame": 2.4,
         "totalGoals": 20, "totalPrimaryAssists": 18, "totalSecondaryAssists": 15,
         "totalShotsOnGoal": 180, "totalHits": 40, "totalShotsBlocked": 25,
         "totalPPP": 18, "avgIcetime": 1120, "xGoalsSurplus": 1.2},
        {"playerId": 91, "season": 2024, "gamesPlayed": 72, "fpPerGame": 2.7,
         "totalGoals": 24, "totalPrimaryAssists": 20, "totalSecondaryAssists": 17,
         "totalShotsOnGoal": 195, "totalHits": 43, "totalShotsBlocked": 28,
         "totalPPP": 22, "avgIcetime": 1160, "xGoalsSurplus": 0.4},
    ])
    goalie_history = pd.DataFrame([
        {"playerId": 181, "season": 2024, "gamesPlayed": 55,
         "gamesStarted": 53, "fpPerGame": 4.2, "wins": 32, "losses": 17,
         "shutouts": 4, "saves": 1500, "goalsAgainst": 135,
         "save_pct": 0.917, "gsax": 12.1},
    ])
    return board, rankings, skater_history, goalie_history


def _build(generated_at):
    board, rankings, skaters, goalies = _rankings_and_histories()
    return keeper_advisor.build_context(
        rankings,
        board,
        skater_history=skaters,
        goalie_history=goalies,
        yahoo_settings={
            "league_key": "nhl.l.33072",
            "name": "Test League",
            "num_teams": 10,
            "scoring_type": "head",
            "roster_positions": [{"position": "C", "count": 2}],
            "current_week": 99,
        },
        generated_at=generated_at,
    )


def test_context_contains_every_roster_player_and_relevant_history():
    context = _build(datetime(2026, 7, 17, tzinfo=timezone.utc))

    assert context["schema_version"] == 1
    assert context["season"] == "2026-27"
    assert len(context["roster"]) == 6
    assert len(context["official_top_four"]) == 4
    unmatched = next(row for row in context["roster"] if row["yahoo_name"] == "Not Projected")
    assert unmatched["match_status"] == "unmatched"
    assert unmatched["history"] == []
    skater = next(row for row in context["roster"] if row["player_id"] == 91)
    goalie = next(row for row in context["roster"] if row["player_id"] == 181)
    assert [season["season"] for season in skater["history"]] == [2023, 2024]
    assert goalie["history"][0]["gamesStarted"] == 53
    assert skater["factors"] == [{"label": "Three-season form", "value": 0.4}]


def test_context_hash_ignores_timestamp_but_changes_with_decision_data():
    first = _build(datetime(2026, 7, 17, tzinfo=timezone.utc))
    second = _build(datetime(2026, 7, 18, tzinfo=timezone.utc))
    assert first["context_id"] == second["context_id"]
    assert first["generated_at"] != second["generated_at"]

    changed = deepcopy(second)
    changed["roster"][0]["projected_total"] += 1
    assert keeper_advisor.context_id_for(changed) != first["context_id"]


def test_scenario_sets_use_exact_keeper_round_math():
    context = _build(datetime(2026, 7, 17, tzinfo=timezone.utc))
    scenarios = context["scenario_data"]["sets"]
    assert len(scenarios) == 5  # five matched players choose four
    official_ids = sorted(context["official_top_four"])
    official = next(row for row in scenarios if sorted(row["player_ids"]) == official_ids)
    assert [player["assigned_round"] for player in official["players"]] == [18, 17, 16, 15]
    assert official["total_net_keeper_value"] == pytest.approx(
        sum(player["raw_keeper_value"] - player["pick_cost"]
            for player in official["players"])
    )


def test_context_serializes_only_stable_yahoo_settings():
    context = _build(datetime(2026, 7, 17, tzinfo=timezone.utc))
    yahoo = context["league"]["yahoo_snapshot"]
    assert yahoo["league_key"] == "nhl.l.33072"
    assert "current_week" not in yahoo
    assert context["league"]["keeper_tenure"] == "unknown"


def test_write_context_is_json_and_creates_parent(tmp_path):
    context = _build(datetime(2026, 7, 17, tzinfo=timezone.utc))
    target = tmp_path / "nested" / "keeper_advisor_context.json"
    keeper_advisor.write_context(context, target)
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("{")


def test_context_normalizes_non_finite_optional_history_and_factor_values():
    board, rankings, skaters, goalies = _rankings_and_histories()
    skaters.loc[skaters["playerId"] == 91, "xGoalsSurplus"] = float("inf")
    rankings.loc[rankings["playerId"] == 91, "factor_1"] = (
        '{"label":"Three-season form","value":1e309}'
    )

    context = keeper_advisor.build_context(
        rankings,
        board,
        skater_history=skaters,
        goalie_history=goalies,
        generated_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    skater = next(row for row in context["roster"] if row["player_id"] == 91)
    assert skater["history"][-1]["xGoalsSurplus"] is None
    if skater["factors"]:
        assert skater["factors"] == [
            {"label": "Three-season form", "value": None},
        ]
    json.dumps(context, allow_nan=False)


def test_context_rejects_non_finite_official_keeper_decision_data():
    board, rankings, skaters, goalies = _rankings_and_histories()
    official_index = rankings.index[rankings["is_recommended"]].tolist()[0]
    rankings.loc[official_index, "raw_keeper_value"] = float("inf")

    with pytest.raises(ValueError, match="non-finite decision data"):
        keeper_advisor.build_context(
            rankings,
            board,
            skater_history=skaters,
            goalie_history=goalies,
            generated_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
        )


def test_write_context_atomically_replaces_an_existing_target(tmp_path):
    target = tmp_path / "keeper_advisor_context.json"
    target.write_text('{"context_id":"old"}', encoding="utf-8")
    context = _build(datetime(2026, 7, 17, tzinfo=timezone.utc))

    keeper_advisor.write_context(context, target)

    assert json.loads(target.read_text(encoding="utf-8")) == context
    assert not target.with_suffix(target.suffix + ".tmp").exists()
