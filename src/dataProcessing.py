import time
import pandas as pd
import numpy as np
from src import nhlAPI
import json
import os

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
        time.sleep(0.5)
        teamData = nhlAPI.getRosterData(team)
        teamData = makeTeamDataframe(teamData)
        all_dfs.append(teamData)
    df = pd.concat(all_dfs, ignore_index=True)
    return df

def getAllPlayersWithCache(cache_file='data/raw/players_cache.csv'):
    # Check if cache exists
    if os.path.exists(cache_file):
        age = os.path.getmtime(cache_file)
        current_time = time.time()
        age_hours = (current_time-age)/3600
        if age_hours < 24:
            return pd.read_csv(cache_file)
        else:
            team_names = nhlAPI.getTeamNames()
            team_df = makeAllPlayersDataFrame(team_names)
            team_df.to_csv(cache_file, index=False)
            return team_df
    else:
        team_names = nhlAPI.getTeamNames()
        team_df = makeAllPlayersDataFrame(team_names)
        team_df.to_csv(cache_file, index=False)
        return team_df
        # Check if cache is fresh (< 24 hours old)
        # If fresh: return pd.read_csv(cache_file)
    # If not: fetch new data, save it, return it
        