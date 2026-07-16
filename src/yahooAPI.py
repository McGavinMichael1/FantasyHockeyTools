from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import objectpath
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


def _team_key_for_league(team_keys, league_key):
    """Find the authenticated team's numeric Yahoo key for one league."""
    prefix = f"{league_key}.t."
    return next((key for key in team_keys if key and key.startswith(prefix)), None)


def getMyRoster(lg=None):
    """Return the authenticated Yahoo manager's current roster."""
    league = lg or getLeague()
    league_key = league.settings().get('league_key')
    team_rows = objectpath.Tree(league.yhandler.get_teams_raw()).execute('$..(team_key)')
    team_key = _team_key_for_league(
        (row.get('team_key') for row in team_rows if isinstance(row, dict)),
        league_key,
    )
    if not team_key:
        raise RuntimeError(
            f"Yahoo did not return a team for the authenticated account in {league_key}"
        )
    return league.to_team(team_key).roster(league.current_week())

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
