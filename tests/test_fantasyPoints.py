import pandas as pd
import pytest

from src import fantasyPoints


def test_calculate_skater_points_full_league_scoring():
    # 2G + 1A - 1 plusMinus + 1 GWG + 1 PPP + 5 SOG
    # = 6 + 2 - 0.5 + 1 + 1 + 0.75 = 10.25
    stats = {
        'goals': 2,
        'assists': 1,
        'plusMinus': -1,
        'gameWinningGoals': 1,
        'powerPlayPoints': 1,
        'shorthandedPoints': 0,
        'shots': 5,
    }
    assert fantasyPoints.calculateSkaterPoints(stats) == pytest.approx(10.25)


def _moneypuck_row(playerId, gameId, situation, goals=0, pA=0, sA=0,
                   sog=0, hits=0, blocks=0, points=0):
    return {
        'playerId': playerId,
        'gameId': gameId,
        'situation': situation,
        'I_F_goals': goals,
        'I_F_primaryAssists': pA,
        'I_F_secondaryAssists': sA,
        'I_F_shotsOnGoal': sog,
        'I_F_hits': hits,
        'shotsBlockedByPlayer': blocks,
        'I_F_points': points,
    }


def test_moneypuck_game_points_with_special_teams():
    # Player 1, game 100:
    #   all row:  1G, 1 primary A, 1 secondary A, 4 SOG, 2 hits, 1 block
    #   5on4 row: 1G + 1 primary A = 2 points  -> PPP = 2 (PP goals 1, PP assists 1)
    #   4on5 row: 1 point   -> SHP = 1
    #   5on5 row: must be ignored
    # FP = 3*1 + 2*(1+1) + 0.15*4 + 0.15*2 + 0.35*1 + 1*2 + 1*1
    #    = 3 + 4 + 0.6 + 0.3 + 0.35 + 2 + 1 = 11.25
    df = pd.DataFrame([
        _moneypuck_row(1, 100, 'all', goals=1, pA=1, sA=1, sog=4, hits=2,
                       blocks=1, points=3),
        _moneypuck_row(1, 100, '5on4', goals=1, pA=1, points=2),
        _moneypuck_row(1, 100, '4on5', points=1),
        _moneypuck_row(1, 100, '5on5', points=1),
    ])
    result = fantasyPoints.moneypuckGamePoints(df)

    assert len(result) == 1  # one row per player-game (the 'all' row)
    row = result.iloc[0]
    assert row['powerPlayPoints'] == 2
    assert row['powerPlayGoals'] == 1
    assert row['powerPlayAssists'] == 1
    assert row['shorthandedPoints'] == 1
    assert row['fantasyPoints'] == pytest.approx(11.25)


def test_moneypuck_game_points_powerplay_goals_and_assists():
    # PP goal/assist breakdown (from the 5on4 row) is carried through so draft
    # features can value PP production in fantasy units, not just the raw PPP
    # bonus. 5on4 row: 2 goals + 1 secondary assist = 3 points.
    df = pd.DataFrame([
        _moneypuck_row(1, 100, 'all', goals=2, sA=1, points=3),
        _moneypuck_row(1, 100, '5on4', goals=2, sA=1, points=3),
    ])
    row = fantasyPoints.moneypuckGamePoints(df).iloc[0]
    assert row['powerPlayGoals'] == 2
    assert row['powerPlayAssists'] == 1  # primary + secondary PP assists
    assert row['powerPlayPoints'] == 3


def test_moneypuck_game_points_no_powerplay_rows_zero_pp_breakdown():
    # A player with no 5on4 row gets PP goals = PP assists = 0, not NaN.
    df = pd.DataFrame([
        _moneypuck_row(2, 100, 'all', goals=1, points=1),
    ])
    row = fantasyPoints.moneypuckGamePoints(df).iloc[0]
    assert row['powerPlayGoals'] == 0
    assert row['powerPlayAssists'] == 0


def test_moneypuck_game_points_no_special_teams_rows():
    # A player with no 5on4/4on5 rows that game gets PPP = SHP = 0.
    # FP = 2*(0+1) + 0.15*2 + 0.15*3 + 0.35*2 = 2 + 0.3 + 0.45 + 0.7 = 3.45
    df = pd.DataFrame([
        _moneypuck_row(2, 100, 'all', sA=1, sog=2, hits=3, blocks=2, points=1),
    ])
    result = fantasyPoints.moneypuckGamePoints(df)

    row = result.iloc[0]
    assert row['powerPlayPoints'] == 0
    assert row['shorthandedPoints'] == 0
    assert row['fantasyPoints'] == pytest.approx(3.45)


def test_moneypuck_game_points_keeps_players_and_games_separate():
    # Two players in the same game plus one player across two games:
    # special-teams points must land on the right (playerId, gameId) row.
    df = pd.DataFrame([
        _moneypuck_row(1, 100, 'all', goals=1, points=1),
        _moneypuck_row(1, 100, '5on4', points=1),
        _moneypuck_row(2, 100, 'all', hits=2),
        _moneypuck_row(1, 101, 'all', sog=2),
        _moneypuck_row(1, 101, '4on5', points=1),
    ])
    result = fantasyPoints.moneypuckGamePoints(df).set_index(['playerId', 'gameId'])

    assert len(result) == 3
    assert result.loc[(1, 100), 'powerPlayPoints'] == 1
    assert result.loc[(1, 100), 'fantasyPoints'] == pytest.approx(3 + 1)  # 1G + 1 PPP
    assert result.loc[(2, 100), 'powerPlayPoints'] == 0
    assert result.loc[(2, 100), 'fantasyPoints'] == pytest.approx(0.3)  # 2 hits
    assert result.loc[(1, 101), 'shorthandedPoints'] == 1
    assert result.loc[(1, 101), 'fantasyPoints'] == pytest.approx(0.3 + 1)  # 2 SOG + 1 SHP


def test_calculate_goalie_points_matches_hand_computed_season():
    # Hellebuyck-tier season: 60 GS, 37 W, 19 L, 158 GA, 1656 SV, 5 SO
    # = 60*0.75 + 37*2.5 + 19*-1 + 158*-0.5 + 1656*0.15 + 5*3
    # = 45 + 92.5 - 19 - 79 + 248.4 + 15 = 302.9
    stats = {'gamesStarted': 60, 'wins': 37, 'losses': 19,
             'goalsAgainst': 158, 'saves': 1656, 'shutouts': 5}
    assert fantasyPoints.calculateGoaliePoints(stats) == pytest.approx(302.9)


def test_calculate_goalie_points_defaults_missing_stats_to_zero():
    assert fantasyPoints.calculateGoaliePoints({}) == 0
    assert fantasyPoints.calculateGoaliePoints({'wins': 2}) == pytest.approx(5.0)


def test_goalie_weights_are_the_six_league_categories_exactly():
    assert fantasyPoints.GOALIE_WEIGHTS == {
        'gamesStarted': 0.75, 'wins': 2.5, 'losses': -1,
        'goalsAgainst': -0.5, 'saves': 0.15, 'shutouts': 3,
    }
