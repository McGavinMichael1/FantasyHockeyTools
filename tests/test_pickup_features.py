import pandas as pd

from src.features import pickups


def _stats_row(playerId, name='Skater Guy', position='C', gamesPlayed=10,
               season_ppg=2.0, last5_fantasyPoints=8.0):
    return {
        'playerId': playerId, 'name': name, 'position': position,
        'gamesPlayed': gamesPlayed, 'season_ppg': season_ppg,
        'last5_fantasyPoints': last5_fantasyPoints,
    }


def _players_df():
    return pd.DataFrame([
        {'id': 1, 'full_name': 'Roster Name One', 'positionCode': 'C'},
        {'id': 2, 'full_name': 'Goalie Person', 'positionCode': 'G'},
        {'id': 3, 'full_name': 'Rostered Star', 'positionCode': 'L'},
        {'id': 4, 'full_name': 'Small Sample', 'positionCode': 'D'},
    ])


def test_rank_free_agents_scores_and_sorts():
    stats = pd.DataFrame([
        _stats_row(1, season_ppg=2.0, last5_fantasyPoints=8.0),   # 0.6*2 + 0.4*8 = 4.4
        _stats_row(5, name='Cache Miss', position='D',
                   season_ppg=5.0, last5_fantasyPoints=20.0),      # 11.0, not in players_df
    ])
    result = pickups.rankFreeAgents(stats, _players_df(), rostered_nhle_ids=set())

    assert list(result['playerId']) == [5, 1]
    assert result.iloc[0]['weighted_score'] == 11.0
    assert result.iloc[1]['weighted_score'] == 4.4


def test_rank_free_agents_falls_back_to_moneypuck_identity():
    # Player 5 is missing from the roster cache: display fields fall back
    # to MoneyPuck's name/position instead of being dropped or NaN.
    stats = pd.DataFrame([_stats_row(5, name='Cache Miss', position='D')])
    result = pickups.rankFreeAgents(stats, _players_df(), rostered_nhle_ids=set())

    assert len(result) == 1
    assert result.iloc[0]['full_name'] == 'Cache Miss'
    assert result.iloc[0]['positionCode'] == 'D'


def test_rank_free_agents_filters_goalies_rostered_and_small_samples():
    stats = pd.DataFrame([
        _stats_row(1),                    # keep
        _stats_row(2, position='G'),      # goalie (via roster positionCode)
        _stats_row(3),                    # rostered
        _stats_row(4, gamesPlayed=4),     # GP < 5
    ])
    result = pickups.rankFreeAgents(stats, _players_df(), rostered_nhle_ids={3})

    assert list(result['playerId']) == [1]
