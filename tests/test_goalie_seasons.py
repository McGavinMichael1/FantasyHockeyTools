import pandas as pd

from src import dataProcessing


LANDING_FIXTURE = {
    'birthDate': '1993-05-19',
    'seasonTotals': [
        # NHL regular season — kept
        {'season': 20232024, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 60, 'gamesStarted': 60, 'wins': 37, 'losses': 19,
         'otLosses': 4, 'shutouts': 5, 'goalsAgainst': 158, 'shotsAgainst': 1814},
        # playoffs — dropped (gameTypeId 3)
        {'season': 20232024, 'gameTypeId': 3, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 5, 'gamesStarted': 5, 'wins': 1, 'losses': 4,
         'otLosses': 0, 'shutouts': 0, 'goalsAgainst': 15, 'shotsAgainst': 130},
        # AHL — dropped
        {'season': 20152016, 'gameTypeId': 2, 'leagueAbbrev': 'AHL',
         'gamesPlayed': 30, 'gamesStarted': 30, 'wins': 20, 'losses': 8,
         'otLosses': 1, 'shutouts': 2, 'goalsAgainst': 70, 'shotsAgainst': 800},
        # traded season: one row per team, must aggregate to one
        {'season': 20222023, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 20, 'gamesStarted': 18, 'wins': 10, 'losses': 8,
         'otLosses': 1, 'shutouts': 1, 'goalsAgainst': 55, 'shotsAgainst': 600},
        {'season': 20222023, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 15, 'gamesStarted': 14, 'wins': 7, 'losses': 6,
         'otLosses': 0, 'shutouts': 0, 'goalsAgainst': 40, 'shotsAgainst': 450},
        # ancient season with a missing field — None coerces to 0
        {'season': 20082009, 'gameTypeId': 2, 'leagueAbbrev': 'NHL',
         'gamesPlayed': 40, 'gamesStarted': None, 'wins': 22, 'losses': 15,
         'otLosses': 2, 'shutouts': 3, 'goalsAgainst': 100, 'shotsAgainst': 1100},
    ],
}


def test_extract_goalie_seasons_filters_and_converts_season_keys():
    rows = dataProcessing.extractGoalieSeasons(LANDING_FIXTURE, 8478024)
    seasons = sorted(r['season'] for r in rows)
    assert seasons == [2008, 2022, 2022, 2023]  # no playoffs, no AHL
    assert all(r['playerId'] == 8478024 for r in rows)
    ancient = next(r for r in rows if r['season'] == 2008)
    assert ancient['gamesStarted'] == 0  # None -> 0


def test_aggregate_goalie_season_rows_sums_traded_stints():
    rows = dataProcessing.extractGoalieSeasons(LANDING_FIXTURE, 8478024)
    df = dataProcessing.aggregateGoalieSeasonRows(rows)
    assert len(df) == 3  # 2008, 2022 (merged), 2023
    traded = df[df['season'] == 2022].iloc[0]
    assert traded['gamesPlayed'] == 35
    assert traded['wins'] == 17
    assert traded['shotsAgainst'] == 1050


def test_append_missing_birthdates_fetches_only_missing_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(dataProcessing, 'RAW_DATA_DIR', str(tmp_path))
    pd.DataFrame({'playerId': [1], 'birthDate': ['1990-01-01']}).to_csv(
        tmp_path / 'player_birthdates.csv', index=False)

    fetched = []

    def fake_fetch(ids):
        fetched.extend(ids)
        return pd.DataFrame({'playerId': ids, 'birthDate': ['1995-05-05'] * len(ids)})

    monkeypatch.setattr(dataProcessing, 'makeAllBirthDatesDataFrame', fake_fetch)
    result = dataProcessing.appendMissingBirthDates([1, 2])

    assert fetched == [2]  # id 1 was cached, never refetched
    assert sorted(result['playerId'].tolist()) == [1, 2]
    on_disk = pd.read_csv(tmp_path / 'player_birthdates.csv')
    assert sorted(on_disk['playerId'].tolist()) == [1, 2]


def test_get_goalie_seasons_with_cache_appends_missing_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(dataProcessing, 'RAW_DATA_DIR', str(tmp_path))
    pd.DataFrame({'playerId': [1], 'season': [2023], 'gamesPlayed': [50],
                  'gamesStarted': [48], 'wins': [30], 'losses': [15],
                  'otLosses': [3], 'shutouts': [4], 'goalsAgainst': [120],
                  'shotsAgainst': [1400]}).to_csv(
        tmp_path / 'goalie_nhl_seasons.csv', index=False)

    fetched = []

    def fake_make(ids):
        fetched.extend(ids)
        return pd.DataFrame({'playerId': ids, 'season': [2023] * len(ids),
                             'gamesPlayed': [20] * len(ids), 'gamesStarted': [18] * len(ids),
                             'wins': [9] * len(ids), 'losses': [8] * len(ids),
                             'otLosses': [1] * len(ids), 'shutouts': [1] * len(ids),
                             'goalsAgainst': [50] * len(ids), 'shotsAgainst': [560] * len(ids)})

    monkeypatch.setattr(dataProcessing, 'makeGoalieSeasonsDataFrame', fake_make)
    result = dataProcessing.getGoalieSeasonsWithCache([1, 2])

    assert fetched == [2]
    assert sorted(result['playerId'].tolist()) == [1, 2]
