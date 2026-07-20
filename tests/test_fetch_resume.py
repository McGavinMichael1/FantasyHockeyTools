"""Resumability of the NHL API bulk fetches.

The July 2026 incident lost ~2400 fetched players because nothing was written
until the whole build finished. These pin the checkpoint/resume contract.
"""

import pandas as pd
import pytest

from src import dataProcessing


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dataProcessing, 'RAW_DATA_DIR', str(tmp_path))
    return tmp_path


def test_fetch_flushes_progress_to_a_partial_file(raw_dir, monkeypatch):
    """A run that dies after N players must leave those N on disk."""
    monkeypatch.setattr(dataProcessing, 'CHECKPOINT_EVERY', 2)
    monkeypatch.setattr(dataProcessing.nhlAPI, 'getPlayerStats',
                        lambda pid: {'birthDate': f'199{pid}-01-01'})
    cache_file = str(raw_dir / 'player_birthdates.csv')

    dataProcessing.fetchAllPlayers([1, 2, 3, 4], dataProcessing.extractBirthDate,
                                   cache_file=cache_file)

    partial = pd.read_csv(cache_file + '.partial')
    assert sorted(partial['playerId'].tolist()) == [1, 2, 3, 4]


def test_interrupted_birthdate_build_resumes_from_the_partial(raw_dir, monkeypatch):
    """The whole point: re-running fetches only what the partial lacks."""
    cache_file = raw_dir / 'player_birthdates.csv'
    pd.DataFrame({'playerId': [1], 'birthDate': ['1990-01-01']}).to_csv(
        cache_file, index=False)
    # An interrupted run got player 2 before dying.
    pd.DataFrame({'playerId': [2], 'birthDate': ['1991-01-01']}).to_csv(
        str(cache_file) + '.partial', index=False)

    fetched = []

    def fake_fetch(ids):
        fetched.extend(ids)
        return pd.DataFrame({'playerId': ids, 'birthDate': ['1995-05-05'] * len(ids)})

    monkeypatch.setattr(dataProcessing, 'makeAllBirthDatesDataFrame', fake_fetch)
    result = dataProcessing.appendMissingBirthDates([1, 2, 3])

    assert fetched == [3], "player 2 was recovered from the partial, not refetched"
    assert sorted(result['playerId'].tolist()) == [1, 2, 3]
    assert not (raw_dir / 'player_birthdates.csv.partial').exists(), \
        "partial must be cleared once folded into the cache"
    on_disk = pd.read_csv(cache_file)
    assert sorted(on_disk['playerId'].tolist()) == [1, 2, 3]


def test_goalie_resume_keeps_every_season_row(raw_dir, monkeypatch):
    """Goalie rows are one per player-season -- dedupe must not collapse them."""
    cache_file = raw_dir / 'goalie_nhl_seasons.csv'
    pd.DataFrame({'playerId': [1, 1, 1], 'season': [2021, 2022, 2023],
                  'wins': [20, 25, 30]}).to_csv(cache_file, index=False)
    pd.DataFrame({'playerId': [2, 2], 'season': [2022, 2023],
                  'wins': [10, 12]}).to_csv(str(cache_file) + '.partial', index=False)

    monkeypatch.setattr(dataProcessing, 'makeGoalieSeasonsDataFrame',
                        lambda ids: pytest.fail(f"should not refetch {ids}"))
    result = dataProcessing.getGoalieSeasonsWithCache([1, 2])

    assert len(result) == 5, "all five player-season rows must survive"
    assert sorted(result[result['playerId'] == 1]['season'].tolist()) == [2021, 2022, 2023]


def test_extract_returning_a_list_is_flattened(raw_dir, monkeypatch):
    """extractGoalieSeasons returns many rows per player; map-based code used
    to flatten it separately."""
    monkeypatch.setattr(dataProcessing.nhlAPI, 'getPlayerStats', lambda pid: {
        'seasonTotals': [
            {'gameTypeId': 2, 'leagueAbbrev': 'NHL', 'season': 20222023, 'wins': 5},
            {'gameTypeId': 2, 'leagueAbbrev': 'NHL', 'season': 20232024, 'wins': 7},
        ]})

    rows = dataProcessing.fetchAllPlayers([1], dataProcessing.extractGoalieSeasons)

    assert len(rows) == 2
    assert sorted(rows['season'].tolist()) == [2022, 2023]


def test_failed_players_are_skipped_not_fatal(raw_dir, monkeypatch):
    """One dead player id must not sink the build."""
    def flaky(player_id):
        if player_id == 2:
            raise dataProcessing.nhlAPI.NHLAPIError('gone')
        return {'birthDate': '1990-01-01'}

    monkeypatch.setattr(dataProcessing.nhlAPI, 'getPlayerStats', flaky)

    rows = dataProcessing.fetchAllPlayers([1, 2, 3], dataProcessing.extractBirthDate)

    assert sorted(rows['playerId'].tolist()) == [1, 3]
