import pandas as pd
import pytest

from src import keeper


def test_league_rules_are_the_canonical_keeper_assumptions():
    assert keeper.league_rules() == {
        "team_count": 10,
        "keeper_count": 4,
        "keeper_rounds": [18, 17, 16, 15],
        "keeper_tenure": "unknown",
        "roster_slots": {
            "C": 2, "L": 2, "R": 2, "D": 4,
            "UTIL": 2, "G": 2, "BN": 5, "IR+": 2,
        },
        "replacement_ranks": {"C": 24, "L": 24, "R": 24, "D": 48, "G": 20},
    }


def test_round_pick_costs_reads_team_count_instead_of_a_local_ten(monkeypatch):
    monkeypatch.setattr(keeper, "TEAM_COUNT", 2)
    board = pd.DataFrame({
        "projected_total": [float(value) for value in range(36, 0, -1)],
    })

    costs = keeper.round_pick_costs(board)

    # Round 18 starts at pick 35 in a two-team league: values 2 and 1.
    assert costs[18] == pytest.approx(1.5)


def _projection_board():
    rows = []
    for position, count, top_total in [
        ("C", 30, 200),
        ("L", 30, 180),
        ("R", 30, 160),
        ("D", 90, 220),
        ("G", 30, 240),
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


def test_keeper_analysis_treats_goalies_as_full_candidates():
    roster = [
        {"name": "G Player 1", "player_id": "g1", "eligible_positions": ["G"]},
        {"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"]},
        {"name": "L Player 1", "player_id": "y2", "eligible_positions": ["LW"]},
        {"name": "R Player 1", "player_id": "y3", "eligible_positions": ["RW"]},
        {"name": "Not On Board", "player_id": "u1", "eligible_positions": ["C"]},
    ]

    rankings = keeper.analyze_keepers(roster, _projection_board())
    recommended = rankings[rankings["is_recommended"]].sort_values("keeper_rank")

    # Raw surpluses on this fixture: C/L/R = 23 each (rank-24 replacement),
    # G = 240 - 221 = 19 (rank-20 replacement). Four matched candidates fill
    # the four slots, goalie last -- the point is the goalie COMPETES on value
    # instead of being excluded.
    assert recommended["full_name"].tolist() == [
        "C Player 1", "L Player 1", "R Player 1", "G Player 1",
    ]
    goalie_row = recommended[recommended["full_name"] == "G Player 1"].iloc[0]
    assert goalie_row["raw_keeper_value"] == pytest.approx(19.0)
    unmatched = rankings[rankings["yahoo_name"] == "Not On Board"].iloc[0]
    assert unmatched["excluded_reason"] == "No projection match"


def test_vorp_column_is_nan_for_positions_without_replacement_level():
    board = _projection_board()
    skaters_only = board[board["position"] != "G"].copy()
    vorp = keeper.vorp_column(skaters_only)
    assert vorp.notna().all()

    with_goalies = keeper.vorp_column(board)
    g_rows = board["position"] == "G"
    # G replacement = 20th goalie = 240-19 = 221
    top_goalie = board[g_rows].sort_values("projected_total", ascending=False).index[0]
    assert with_goalies.loc[top_goalie] == pytest.approx(240.0 - 221.0)
