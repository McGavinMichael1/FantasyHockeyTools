import os
import time

import pandas as pd
import pytest

from src import moneypuck


def _game_row(playerId, season, gameId, situation='all'):
    row = {col: 0 for col in moneypuck.GAME_COLUMNS}
    row.update({
        'playerId': playerId,
        'season': season,
        'gameId': gameId,
        'situation': situation,
        'name': f'Player {playerId}',
        'gameDate': int(f'{season}1101'),
        'position': 'C',
    })
    return row


def test_load_game_logs_filters_season_and_keeps_situations(tmp_path):
    history = pd.DataFrame([
        _game_row(1, 2015, 10),            # below min_season -> dropped
        _game_row(1, 2020, 20),
        _game_row(1, 2020, 20, '5on4'),    # situation rows must survive
    ])
    current = pd.DataFrame([
        _game_row(1, 2025, 30),
        _game_row(2, 2025, 30),
    ])
    history_file = tmp_path / 'history.csv'
    current_file = tmp_path / 'current.csv'
    cache_file = tmp_path / 'cache.csv'
    history.to_csv(history_file, index=False)
    current.to_csv(current_file, index=False)

    df = moneypuck.loadGameLogs(min_season=2020, history_file=history_file,
                                current_file=current_file, cache_file=cache_file)

    assert len(df) == 4
    assert df['season'].min() == 2020
    assert set(df['situation']) == {'all', '5on4'}
    # second call hits the cache (delete sources to prove it's not re-reading)
    history_file.unlink()
    current_file.unlink()
    cache_file.touch()  # keep cache newer than (now missing) current file
    df2 = moneypuck.loadGameLogs(min_season=2020, history_file=history_file,
                                 current_file=current_file, cache_file=cache_file)
    assert len(df2) == 4


def test_cache_round_trips_through_parquet(tmp_path):
    """Parquet is the cache format; it must preserve dtypes and values."""
    df = pd.DataFrame([_game_row(1, 2020, 20), _game_row(2, 2020, 21, '5on4')])
    path = tmp_path / 'cache.parquet'

    moneypuck.writeCache(df, path)
    result = moneypuck.readCache(path)

    pd.testing.assert_frame_equal(df, result)


def test_load_game_logs_defaults_to_a_parquet_cache(tmp_path):
    history = pd.DataFrame([_game_row(1, 2020, 20)])
    current = pd.DataFrame([_game_row(1, 2025, 30)])
    history_file = tmp_path / 'history.csv'
    current_file = tmp_path / 'current.csv'
    history.to_csv(history_file, index=False)
    current.to_csv(current_file, index=False)
    cache_file = tmp_path / 'cache.parquet'

    moneypuck.loadGameLogs(min_season=2020, history_file=history_file,
                           current_file=current_file, cache_file=cache_file)

    assert cache_file.exists()
    assert len(pd.read_parquet(cache_file)) == 2


def test_corrupt_cache_rebuilds_instead_of_crashing(tmp_path):
    """Caches are disposable; a truncated one must not be fatal."""
    history = pd.DataFrame([_game_row(1, 2020, 20)])
    current = pd.DataFrame([_game_row(1, 2025, 30)])
    history_file = tmp_path / 'history.csv'
    current_file = tmp_path / 'current.csv'
    history.to_csv(history_file, index=False)
    current.to_csv(current_file, index=False)
    cache_file = tmp_path / 'cache.parquet'
    cache_file.write_bytes(b'not a parquet file')
    os.utime(cache_file, (time.time() + 60, time.time() + 60))  # look "fresh"

    df = moneypuck.loadGameLogs(min_season=2020, history_file=history_file,
                                current_file=current_file, cache_file=cache_file)

    assert len(df) == 2
    assert len(pd.read_parquet(cache_file)) == 2, "corrupt cache should be replaced"


def test_missing_sources_still_error_when_there_is_no_cache(tmp_path):
    with pytest.raises(FileNotFoundError):
        moneypuck.loadGameLogs(min_season=2020,
                               history_file=tmp_path / 'nope.csv',
                               current_file=tmp_path / 'nope2.csv',
                               cache_file=tmp_path / 'nocache.parquet')


def _pickup_row(playerId, gameId, gameDate, situation='all', season=2025,
                name='Player One', position='C', icetime=1200,
                goals=0, pA=0, sA=0, sog=0, hits=0, blocks=0, points=0):
    """Minimal full-situation game-log row for buildPickupStats tests."""
    return {
        'playerId': playerId, 'gameId': gameId, 'gameDate': gameDate,
        'season': season, 'name': name, 'position': position,
        'situation': situation, 'icetime': icetime,
        'I_F_goals': goals, 'I_F_primaryAssists': pA,
        'I_F_secondaryAssists': sA, 'I_F_shotsOnGoal': sog,
        'I_F_hits': hits, 'shotsBlockedByPlayer': blocks,
        'I_F_points': points,
    }


def test_build_pickup_stats_season_totals_no_double_count():
    # Player 1, one game with situation rows: the 5on4 row must feed PPP,
    # not be summed into the season totals (the 'all' row already totals it).
    # FP = 3*1 + 2*1 + 0.15*3 + 0.15*2 + 0.35*1 + 1*1(PPP)
    #    = 3 + 2 + 0.45 + 0.30 + 0.35 + 1 = 7.10
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015, goals=1, pA=1, sog=3, hits=2,
                    blocks=1, points=2),
        _pickup_row(1, 100, 20251015, situation='5on4', goals=1, points=1),
    ])
    result = moneypuck.buildPickupStats(df, season=2025)

    assert len(result) == 1
    row = result.iloc[0]
    assert row['gamesPlayed'] == 1
    assert row['goals'] == 1
    assert row['assists'] == 1
    assert row['points'] == 2
    assert row['shots'] == 3
    assert row['hits'] == 2
    assert row['blocks'] == 1
    assert row['powerPlayPoints'] == 1
    assert row['fantasyPoints'] == pytest.approx(7.10)
    assert row['season_ppg'] == pytest.approx(7.10)
    assert row['avgToiSeconds'] == pytest.approx(1200)


def test_build_pickup_stats_last5_window_is_last_five_by_date():
    # 7 games: season totals cover all 7, last5_* only the 5 most recent.
    # Each game: 1 goal (FP 3). Last-5 FP = 15, season FP = 21.
    rows = [_pickup_row(1, 100 + i, 20251001 + i, goals=1, points=1)
            for i in range(7)]
    result = moneypuck.buildPickupStats(pd.DataFrame(rows), season=2025)

    row = result.iloc[0]
    assert row['gamesPlayed'] == 7
    assert row['goals'] == 7
    assert row['fantasyPoints'] == pytest.approx(21)
    assert row['last5_goals'] == 5
    assert row['last5_fantasyPoints'] == pytest.approx(15)
    assert row['season_ppg'] == pytest.approx(3.0)


def test_build_pickup_stats_filters_to_requested_season():
    df = pd.DataFrame([
        _pickup_row(1, 100, 20241015, season=2024, goals=5, points=5),
        _pickup_row(1, 200, 20251015, season=2025, goals=1, points=1),
    ])
    result = moneypuck.buildPickupStats(df, season=2025)

    assert len(result) == 1
    assert result.iloc[0]['goals'] == 1
    assert result.iloc[0]['gamesPlayed'] == 1


def test_build_pickup_stats_empty_season_returns_empty_frame():
    df = pd.DataFrame([_pickup_row(1, 100, 20241015, season=2024)])
    result = moneypuck.buildPickupStats(df, season=2025)
    assert len(result) == 0


def test_build_pickup_stats_keeps_players_separate():
    df = pd.DataFrame([
        _pickup_row(1, 100, 20251015, goals=2, points=2),
        _pickup_row(2, 100, 20251015, name='Player Two', position='D',
                    hits=4, blocks=3),
    ])
    result = moneypuck.buildPickupStats(df, season=2025).set_index('playerId')

    assert result.loc[1, 'goals'] == 2
    assert result.loc[2, 'goals'] == 0
    assert result.loc[2, 'hits'] == 4
    assert result.loc[2, 'position'] == 'D'
    # FP: player 2 = 0.15*4 + 0.35*3 = 1.65
    assert result.loc[2, 'fantasyPoints'] == pytest.approx(1.65)
