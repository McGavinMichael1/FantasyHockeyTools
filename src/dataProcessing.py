import time
import pandas as pd
import numpy as np
from src import nhlAPI
import json

def makeTeamDataframe(jsonData):
    forwards = jsonData['forwards']
    defensemen = jsonData['defensemen']
    goalies = jsonData['goalies']
    roster_dict = forwards + defensemen + goalies
    df = pd.DataFrame(roster_dict)
    return df

def makeAllPlayersDataFrame(teamNames):
    df = pd.DataFrame() 
    all_dfs = []
    for team in teamNames:
        print(f"Fetching data for team: {team}")  # See which team fails
        time.sleep(0.2)
        teamData = nhlAPI.getRosterData(team)
        teamData = makeTeamDataframe(teamData)
        all_dfs.append(teamData)
    df = pd.concat(all_dfs, ignore_index=True)
    return df

def getAllPlayersWithCache(cache_file='data/players_cache.csv'):
    cache_file = '/Users/mike/Documents/fantasy hockey/data'
    # Check if cache exists
    if os.path.exists(cache_file):
        # Check if cache is fresh (< 24 hours old)
        # If fresh: return pd.read_csv(cache_file)
    # If not: fetch new data, save it, return it
        
