import pandas as pd

from src import keeper


def _projection_board():
    rows = []
    for position, count, top_total in [
        ("C", 30, 200),
        ("L", 30, 180),
        ("R", 30, 160),
        ("D", 90, 220),
    ]:
        for index in range(count):
            rows.append(
                {
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
                }
            )
    return pd.DataFrame(rows)


def test_keeper_analysis_recommends_four_skaters_with_late_round_costs():
    roster = [
        {"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"]},
        {"name": "L Player 1", "player_id": "y2", "eligible_positions": ["LW"]},
        {"name": "R Player 1", "player_id": "y3", "eligible_positions": ["RW"]},
        {"name": "D Player 1", "player_id": "y4", "eligible_positions": ["D"]},
    ]

    rankings = keeper.analyze_keepers(roster, _projection_board())
    recommended = rankings[rankings["is_recommended"]].sort_values("keeper_rank")

    assert recommended["full_name"].tolist() == [
        "D Player 1",
        "C Player 1",
        "L Player 1",
        "R Player 1",
    ]
    assert recommended["assigned_round"].tolist() == [18, 17, 16, 15]
    assert (recommended["net_keeper_value"] == (
        recommended["raw_keeper_value"] - recommended["pick_cost"]
    )).all()


def test_keeper_analysis_keeps_goalies_and_unmatched_players_in_the_audit():
    roster = [
        {"name": "Goalie Name", "player_id": "g1", "eligible_positions": ["G"]},
        {"name": "Not On Board", "player_id": "u1", "eligible_positions": ["C"]},
    ]

    rankings = keeper.analyze_keepers(roster, _projection_board())

    assert rankings["yahoo_name"].tolist() == ["Goalie Name", "Not On Board"]
    assert rankings.iloc[0]["excluded_reason"] == "Goalies are excluded from keeper analysis"
    assert rankings.iloc[1]["excluded_reason"] == "No projection match"
