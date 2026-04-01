from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import os
from src import dataProcessing
from rapidfuzz import process

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def getLeague():
    oauth = OAuth2(None, None, from_file=os.path.join(BASE_DIR, '..', 'oauth2.json'))
    gm = yfa.Game(oauth, 'nhl')
    lg = gm.to_league('nhl.l.33072')
    return lg

def getRosteredIds(lg):
    rostered_names = set()
    teams = lg.teams()
    for team in teams:
        roster = lg.to_team(team)
        roster = roster.roster(lg.current_week())
        for player in roster:
            rostered_names.add(player['name'])
    return rostered_names

def getRosteredNHLIds(rostered_names, players_df):
    players_df = dataProcessing.flattenPlayerNames(players_df)
    candidate_names = players_df['full_name'].tolist()

    rostered_ids = set()
    for name in rostered_names:
        match = process.extractOne(name, candidate_names, score_cutoff=85)
        if match:
            matched_name = match[0]
            player_id = players_df.loc[players_df['full_name'] == matched_name, 'id'].values[0]
            rostered_ids.add(player_id)
        else:
            print(f"No good match found for {name}")
    return rostered_ids



# def getMyRoster():