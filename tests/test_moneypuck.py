import pandas as pd

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
