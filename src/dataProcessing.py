import time
import pandas as pd
import numpy as np
from src import nhlAPI
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, '..', 'data', 'raw')

def makeTeamDataframe(jsonData):
    forwards = jsonData['forwards']
    defensemen = jsonData['defensemen']
    goalies = jsonData['goalies']
    roster_dict = forwards + defensemen + goalies
    df = pd.DataFrame(roster_dict)
    return df

def flattenPlayerNames(players_df):
    def extract_default(x):
        if isinstance(x, dict):
            return x['default']
        return ast.literal_eval(x)['default']
    players_df = players_df.copy()
    players_df['first'] = players_df['firstName'].apply(extract_default)
    players_df['last'] = players_df['lastName'].apply(extract_default)
    players_df['full_name'] = players_df['first'] + ' ' + players_df['last']
    return players_df

def makeAllPlayersDataFrame(teamNames):
    df = pd.DataFrame() 
    all_dfs = []
    for team in teamNames:
        print(f"Fetching data for team: {team}")  # See which team fails
        time.sleep(0.5)
        teamData = nhlAPI.getRosterData(team)
        teamData = makeTeamDataframe(teamData)
        all_dfs.append(teamData)
    df = pd.concat(all_dfs, ignore_index=True)
    return df

def fetchAllPlayers(player_ids, extract_fn):
    def worker(player_id):
        try:
            data = nhlAPI.getPlayerStats(player_id)
            return extract_fn(data, player_id)
        except Exception as e:
            print(f"Failed for player {player_id}: {e}")
            return None
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = [r for r in executor.map(worker, player_ids) if r is not None]
    return pd.DataFrame(results)

def getWithCache(make_fn, player_ids, cache_file):
    if os.path.exists(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 24:
            return pd.read_csv(cache_file)
    df = make_fn(player_ids)
    df.to_csv(cache_file, index=False)
    return df

def getAllPlayersWithCache():
    make_fn = lambda _: makeAllPlayersDataFrame(nhlAPI.getTeamNames())
    return getWithCache(make_fn, None, os.path.join(RAW_DATA_DIR, 'players_cache.csv'))

def extractBirthDate(data, player_id):
    return {'playerId': player_id, 'birthDate': data.get('birthDate')}

def makeAllBirthDatesDataFrame(player_ids):
    return fetchAllPlayers(player_ids, extractBirthDate)

def getAllBirthDatesWithCache(player_ids):
    # birthDates are immutable, so cache permanently -- unlike getWithCache's
    # 24h expiry, never refetch once the file exists. Covers retired players
    # that players_cache.csv (current roster only) can't.
    cache_file = os.path.join(RAW_DATA_DIR, 'player_birthdates.csv')
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file)
    df = makeAllBirthDatesDataFrame(player_ids)
    df.to_csv(cache_file, index=False)
    return df


def extractGoalieSeasons(data, player_id):
    """NHL regular-season goalie rows from a landing response.

    Filters to gameTypeId 2 (regular season) + leagueAbbrev NHL, converts the
    season key to MoneyPuck convention (20232024 -> 2023). Traded goalies get
    one row per team per season here -- aggregateGoalieSeasonRows sums them.
    """
    rows = []
    for s in data.get('seasonTotals', []):
        if s.get('gameTypeId') != 2 or s.get('leagueAbbrev') != 'NHL':
            continue
        rows.append({
            'playerId': player_id,
            'season': s['season'] // 10000,
            'gamesPlayed': s.get('gamesPlayed') or 0,
            'gamesStarted': s.get('gamesStarted') or 0,
            'wins': s.get('wins') or 0,
            'losses': s.get('losses') or 0,
            'otLosses': s.get('otLosses') or 0,
            'shutouts': s.get('shutouts') or 0,
            'goalsAgainst': s.get('goalsAgainst') or 0,
            'shotsAgainst': s.get('shotsAgainst') or 0,
        })
    return rows


def aggregateGoalieSeasonRows(rows):
    """One row per (playerId, season): sums the per-team stint rows."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.groupby(['playerId', 'season'], as_index=False).sum()


def makeGoalieSeasonsDataFrame(player_ids):
    def worker(player_id):
        try:
            return extractGoalieSeasons(nhlAPI.getPlayerStats(player_id), player_id)
        except Exception as e:
            print(f"Failed for goalie {player_id}: {e}")
            return []
    with ThreadPoolExecutor(max_workers=5) as executor:
        rows = [row for result in executor.map(worker, player_ids) for row in result]
    return aggregateGoalieSeasonRows(rows)


def getGoalieSeasonsWithCache(player_ids):
    """Permanent cache (like birthdates), plus append-missing: ids absent
    from the cache are fetched and appended. Completed seasons never change;
    at season rollover DELETE data/raw/goalie_nhl_seasons.csv so every
    goalie's newest season gets fetched fresh (a few minutes, threaded).
    """
    cache_file = os.path.join(RAW_DATA_DIR, 'goalie_nhl_seasons.csv')
    if os.path.exists(cache_file):
        cached = pd.read_csv(cache_file)
        missing = sorted(set(player_ids) - set(cached['playerId']))
        if not missing:
            return cached
        combined = pd.concat([cached, makeGoalieSeasonsDataFrame(missing)],
                             ignore_index=True)
        combined.to_csv(cache_file, index=False)
        return combined
    df = makeGoalieSeasonsDataFrame(player_ids)
    df.to_csv(cache_file, index=False)
    return df


def appendMissingBirthDates(player_ids):
    """getAllBirthDatesWithCache returns the cache as-is when it exists; this
    also fetches ids the cache lacks (goalies were never in player_seasons,
    so the draft-era birthdate build skipped them).
    """
    cache_file = os.path.join(RAW_DATA_DIR, 'player_birthdates.csv')
    if not os.path.exists(cache_file):
        return getAllBirthDatesWithCache(player_ids)
    cached = pd.read_csv(cache_file)
    missing = sorted(set(player_ids) - set(cached['playerId']))
    if not missing:
        return cached
    combined = pd.concat([cached, makeAllBirthDatesDataFrame(missing)],
                         ignore_index=True)
    combined.to_csv(cache_file, index=False)
    return combined