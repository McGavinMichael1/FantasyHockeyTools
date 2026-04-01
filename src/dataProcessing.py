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
    players_df = players_df.copy()
    players_df['first'] = players_df['firstName'].apply(lambda x: ast.literal_eval(x)['default'])
    players_df['last'] = players_df['lastName'].apply(lambda x: ast.literal_eval(x)['default'])
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

def extractCurrentStats(data, player_id):
    season_totals = data['seasonTotals']
    current = next((s for s in season_totals if s['season'] == 20252026), None)
    if current is None:
        # return a dict of zeros if no current season data is found
        return {
            'player_id': player_id,
            'goals': 0,
            'assists': 0,
            'avgToi' : 0,
            'gameWinningGoals': 0,
            'gamesPlayed': 0,
            'shorthandedPoints': 0,
            'points': 0,
            'plusMinus': 0,
            'shootingPctg': 0,
            'powerPlayPoints': 0,
            'pim': 0,
            'shots': 0
        }
    else:
        # concatenate the player id with the current season stats into a single dict
        current_stats = {
            'player_id': player_id,
            'goals': current.get('goals', 0),
            'assists': current.get('assists', 0),
            'avgToi': current.get('avgToi', 0),
            'gameWinningGoals': current.get('gameWinningGoals', 0),
            'gamesPlayed': current.get('gamesPlayed', 0),
            'shorthandedPoints': current.get('shorthandedPoints', 0),
            'points': current.get('points', 0),
            'plusMinus': current.get('plusMinus', 0),
            'shootingPctg': current.get('shootingPctg', 0),
            'powerPlayPoints': current.get('powerPlayPoints', 0),
            'pim': current.get('pim', 0),
            'shots': current.get('shots', 0)
        }
        return current_stats
    
def parseToi(toi_string):
    toi_split = toi_string.split(":")
    minutes = int(toi_split[0])
    seconds = int(toi_split[1])
    total_minutes = minutes + seconds/60
    return total_minutes

def extractLast5Stats(data, player_id):
    last5_games = data['last5Games']
    totals = {
        'goals': 0,
        'assists': 0,
        'avgToi' : 0,
        'points': 0,
        'plusMinus': 0,
        'shorthandedGoals': 0,
        'powerPlayGoals': 0,
        'pim': 0,
        'shots': 0
    }
    for game in last5_games:
        totals['goals'] += game.get('goals', 0)
        totals['assists'] += game.get('assists', 0)
        totals['avgToi'] += parseToi(game.get('toi', '0:00'))
        totals['points'] += game.get('points', 0)
        totals['plusMinus'] += game.get('plusMinus', 0)
        totals['powerPlayGoals'] += game.get('powerPlayGoals', 0)
        totals['shorthandedGoals'] += game.get('shorthandedGoals', 0)
        totals['pim'] += game.get('pim', 0)
        totals['shots'] += game.get('shots', 0)
    totals['avgToi'] = totals['avgToi'] / len(last5_games)  # average over 5 games
    if totals['shots'] > 0:
        totals['shootingPctg'] = totals['goals'] / totals['shots']
    else:
        totals['shootingPctg'] = 0
    return {'player_id': player_id, **totals}

def makeAllStatsDataFrame(player_ids):
    return fetchAllPlayers(player_ids, extractCurrentStats)
 
def getAllStatsWithCache(player_ids):
    return getWithCache(makeAllStatsDataFrame, player_ids, os.path.join(RAW_DATA_DIR, 'stats_current.csv'))
    
def makeAllLast5DataFrame(player_ids):
    return fetchAllPlayers(player_ids, extractLast5Stats)

def getAllLast5WithCache(player_ids):
    return getWithCache(makeAllLast5DataFrame, player_ids, os.path.join(RAW_DATA_DIR, 'stats_last5.csv'))