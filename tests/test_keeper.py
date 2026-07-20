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


def _two_position_board(c_totals, d_totals):
    """A hand-computable board: two positions, explicit projected totals."""
    return pd.DataFrame(
        [{"playerId": index, "full_name": f"C Player {index}", "position": "C",
          "projected_total": float(total)}
         for index, total in enumerate(c_totals, start=1)]
        + [{"playerId": 100 + index, "full_name": f"D Player {index}", "position": "D",
            "projected_total": float(total)}
           for index, total in enumerate(d_totals, start=1)]
    )


def test_round_pick_costs_reads_team_count_instead_of_a_local_ten(monkeypatch):
    monkeypatch.setattr(keeper, "REPLACEMENT_RANKS", {"C": 4, "D": 4})
    monkeypatch.setattr(keeper, "TEAM_COUNT", 2)
    monkeypatch.setattr(keeper, "KEEPER_ROUNDS", (3,))
    board = _two_position_board([100, 90, 80, 70], [60, 50, 40, 30])

    costs = keeper.round_pick_costs(board)

    # Round 3 starts at pick 5 in a two-team league. Ordered by VORP those are
    # C80 (+10) and D40 (+10), so the round is worth 10.
    assert costs[3] == pytest.approx(10.0)


def test_pick_cost_is_a_vorp_not_an_absolute_projected_total(monkeypatch):
    # THE BUG: net_keeper_value subtracted pick_cost from raw_keeper_value, but
    # raw_keeper_value is value OVER REPLACEMENT while pick_cost was an absolute
    # season total. On the 2026 board that was 60-85 FP of keeper value minus
    # 161-173 FP of "cost", so every keeper scored deeply negative and the tool
    # said keep nobody -- a unit error wearing the costume of a conclusion.
    monkeypatch.setattr(keeper, "REPLACEMENT_RANKS", {"C": 4, "D": 4})
    monkeypatch.setattr(keeper, "TEAM_COUNT", 2)
    monkeypatch.setattr(keeper, "KEEPER_ROUNDS", (2,))
    board = _two_position_board([100, 90, 80, 70], [60, 50, 40, 30])

    costs = keeper.round_pick_costs(board)

    # Replacement is the 4th at each position: C 70, D 30. Both positions then
    # run +30/+20/+10/+0. Ordered by VORP the board is C100, D60, C90, D50, ...
    # so round 2 (picks 3 and 4) is C90 and D50, both +20.
    #
    # The old behaviour sorted by projected_total, which put C80 and C70 in that
    # slot and returned their mean TOTAL, 75.0 -- a number in the wrong units
    # AND off the wrong players.
    assert costs[2] == pytest.approx(20.0)


def test_the_round_slice_follows_vorp_because_that_is_the_board_order(monkeypatch):
    # VORP is the board's default cross-position sort (owner, 2026-07-16), so
    # the players who actually go in a round are the ones ranked there BY VORP.
    # Slicing by projected_total prices a round off players who would not have
    # been picked in it.
    monkeypatch.setattr(keeper, "REPLACEMENT_RANKS", {"C": 4, "D": 4})
    monkeypatch.setattr(keeper, "TEAM_COUNT", 2)
    monkeypatch.setattr(keeper, "KEEPER_ROUNDS", (1,))
    board = _two_position_board([100, 90, 80, 70], [60, 50, 40, 30])

    # By projected_total the top two are C100 and C90 (+30, +20 -> 25).
    # By VORP they are C100 and D60, both +30. D60 is a worse player in absolute
    # terms and still the better pick, which is the whole point of VORP.
    assert keeper.round_pick_costs(board)[1] == pytest.approx(30.0)


def test_a_pick_below_replacement_costs_nothing_rather_than_negative_value(monkeypatch):
    # Giving up a pick can never be a GAIN. A below-replacement draftee is a
    # bench player, interchangeable with a free waiver add -- that is what
    # replacement level means -- so he contributes 0 to a starting lineup, not a
    # negative. Without the clip, keeping a player would score HIGHER the more
    # worthless the pick it costs, and the last rounds of this league are all
    # below replacement.
    monkeypatch.setattr(keeper, "REPLACEMENT_RANKS", {"C": 2, "D": 2})
    monkeypatch.setattr(keeper, "TEAM_COUNT", 2)
    monkeypatch.setattr(keeper, "KEEPER_ROUNDS", (4,))
    board = _two_position_board([100, 90, 80, 70], [60, 50, 40, 30])

    # Replacement is the 2nd at each position: C 90, D 50. Round 4 is picks 7-8,
    # which by VORP are C70 (-20) and D30 (-20): a raw mean of -20.
    assert keeper.round_pick_costs(board)[4] == pytest.approx(0.0)


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


def test_net_keeper_value_subtracts_like_from_like():
    # Both terms must be value-over-replacement. The fixture has exactly 140
    # players at or above replacement (24 C + 24 L + 24 R + 48 D + 20 G) and
    # rounds 15-18 start at pick 141, so every keeper round here is below
    # replacement and costs nothing -- keeping is free when the picks it costs
    # are dead. That is a real conclusion about late picks, not a missing term:
    # test_a_pick_below_replacement_costs_nothing_rather_than_negative_value
    # pins the clip, and the round-70/71/78/90 case in the KEEPER_ROUNDS comment
    # is where the cost is genuinely positive.
    roster = [
        {"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"]},
        {"name": "L Player 1", "player_id": "y2", "eligible_positions": ["LW"]},
        {"name": "R Player 1", "player_id": "y3", "eligible_positions": ["RW"]},
        {"name": "D Player 1", "player_id": "y4", "eligible_positions": ["D"]},
    ]

    rankings = keeper.analyze_keepers(roster, _projection_board())
    recommended = rankings[rankings["is_recommended"]]

    assert (recommended["pick_cost"] == 0).all()
    assert (recommended["net_keeper_value"] == recommended["raw_keeper_value"]).all()
    # And the magnitudes are now comparable rather than an order apart.
    assert recommended["net_keeper_value"].min() > 0


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


def test_replacement_ranks_shrink_by_the_keepers_already_filling_those_slots():
    # Replacement level is the marginal DRAFTED starter. Every kept player at a
    # position is one fewer starter the league has to draft there, so the rank
    # has to come down with them.
    ranks = keeper.replacement_ranks({"C": 15, "D": 5})

    assert ranks["C"] == 24 - 15
    assert ranks["D"] == 48 - 5
    assert ranks["L"] == 24  # untouched positions keep the base rank


def test_replacement_ranks_never_go_below_one():
    ranks = keeper.replacement_ranks({"G": 999})
    assert ranks["G"] == 1


def test_replacement_ranks_without_keepers_are_the_base_constant():
    # The degraded path (no keepers.csv yet) must behave exactly as before.
    assert keeper.replacement_ranks() == keeper.REPLACEMENT_RANKS
    assert keeper.replacement_ranks({}) == keeper.REPLACEMENT_RANKS


def test_keeper_position_counts_resolves_names_fuzzily():
    board = _projection_board()
    counts = keeper.keeper_position_counts(
        ["C Player 1", "C  Player 2", "D Player 3"], board)

    assert counts == {"C": 2, "D": 1}


def test_keeper_position_counts_warns_about_a_name_it_cannot_place(capsys):
    counts = keeper.keeper_position_counts(["Nobody At All"], _projection_board())

    assert counts == {}
    assert "Nobody At All" in capsys.readouterr().out


def test_vorp_column_ranks_one_frame_against_another_frames_pool():
    board = _projection_board()
    # A pool missing the top 5 centers has a lower C replacement level, so
    # every center's VORP rises by exactly that difference.
    pool = board.drop(board[board["position"] == "C"].index[:5])

    against_self = keeper.vorp_column(board)
    against_pool = keeper.vorp_column(board, pool=pool)

    centers = board["position"] == "C"
    assert (against_pool[centers] - against_self[centers]).round(6).nunique() == 1
    assert (against_pool[centers] > against_self[centers]).all()
    # Positions the pool did not change are untouched.
    goalies = board["position"] == "G"
    assert against_pool[goalies].equals(against_self[goalies])


def test_vorp_column_with_no_pool_or_keepers_is_unchanged():
    board = _projection_board()
    assert keeper.vorp_column(board).equals(
        keeper.vorp_column(board, pool=None, kept_counts=None))


def test_round_pick_costs_price_the_pool_not_the_ranked_frame(monkeypatch):
    monkeypatch.setattr(keeper, "REPLACEMENT_RANKS", {"C": 4, "D": 4})
    monkeypatch.setattr(keeper, "TEAM_COUNT", 2)
    monkeypatch.setattr(keeper, "KEEPER_ROUNDS", (2,))
    board = _two_position_board([100, 90, 80, 70, 60], [65, 64, 63, 40, 20])
    # Removing D63 lifts D's replacement (4th D) from 40 to 20, which reprices
    # every D -- so this pool genuinely disagrees with the full board.
    pool = board[board["projected_total"] != 63]

    # Board: repl C 70 / D 40 -> by VORP C100(30) D65(25) D64(24) D63(23) ...
    #        round 2 is picks 3-4 = D64 and D63 = 23.5
    # Pool:  repl C 70 / D 20 -> by VORP D65(45) D64(44) C100(30) D40(20) ...
    #        round 2 is picks 3-4 = C100 and D40 = 25.0
    assert keeper.round_pick_costs(board)[2] == pytest.approx(23.5)
    assert keeper.round_pick_costs(pool)[2] == pytest.approx(25.0)
    assert keeper.round_pick_costs(board, pool=pool) == keeper.round_pick_costs(pool)


def test_analyze_keepers_still_rates_a_roster_player_absent_from_the_pool():
    # Your own keepers are off the draft pool but are exactly the players the
    # keeper board exists to rate -- they must not fall out as "No projection
    # match" just because the pool no longer contains them.
    board = _projection_board()
    pool = board[board["full_name"] != "C Player 1"]
    roster = [
        {"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"]},
        {"name": "L Player 1", "player_id": "y2", "eligible_positions": ["LW"]},
        {"name": "R Player 1", "player_id": "y3", "eligible_positions": ["RW"]},
        {"name": "D Player 1", "player_id": "y4", "eligible_positions": ["D"]},
    ]

    rankings = keeper.analyze_keepers(roster, board, pool=pool)

    kept = rankings[rankings["yahoo_name"] == "C Player 1"].iloc[0]
    assert kept["match_status"] == "matched"
    assert pd.notna(kept["raw_keeper_value"])


def test_analyze_keepers_prices_against_demand_aware_replacement():
    board = _projection_board()
    # Ten centers kept -> C replacement is the 14th center, not the 24th.
    rankings = keeper.analyze_keepers(
        [{"name": "C Player 1", "player_id": "y1", "eligible_positions": ["C"]}],
        board,
        kept_counts={"C": 10},
    )

    row = rankings.iloc[0]
    # C totals run 200, 199, ... so the 14th is 187.
    assert row["replacement_level"] == pytest.approx(187.0)
    assert row["raw_keeper_value"] == pytest.approx(200.0 - 187.0)


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
