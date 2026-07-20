from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import objectpath
import os
import pandas as pd
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


# --- Historical draft results (for the mock-draft backtest) -----------------
#
# getLeague() hardcodes this season's league key. Past seasons are DIFFERENT
# Yahoo leagues with different keys, so anything historical has to resolve the
# key by year first -- reusing getLeague() would silently grade the wrong draft.

DRAFT_RESULTS_PATH = os.path.join(BASE_DIR, '..', 'data', 'raw', 'draft_results_{year}.csv')


def getLeagueForYear(year):
    """The authenticated user's NHL league for one season, by draft year.

    Yahoo's season numbering follows the draft: the league drafted in Oct 2025
    is season 2025, matching the MoneyPuck convention used everywhere else.
    """
    oauth = OAuth2(None, None, from_file=os.path.join(BASE_DIR, '..', 'oauth2.json'))
    gm = yfa.Game(oauth, 'nhl')

    # `seasons` is the current API; `year` routes to a deprecated endpoint that
    # still works. Try the modern one, fall back rather than fail.
    try:
        league_ids = gm.league_ids(seasons=[str(year)])
    except Exception as error:
        print(f"seasons lookup failed ({error}); falling back to the year endpoint")
        league_ids = gm.league_ids(year=year)

    if not league_ids:
        raise RuntimeError(
            f"No Yahoo NHL league found for {year}. The authenticated account may "
            f"not have played that season, or the OAuth token lacks history access."
        )
    if len(league_ids) > 1:
        print(f"⚠️  {len(league_ids)} leagues found for {year}: {league_ids}")
        print(f"   Using the first one. Check this is the right league before trusting results.")
    return gm.to_league(league_ids[0])


def getDraftResults(year, lg=None):
    """Every pick of one season's draft, newest-first order preserved.

    Returns a list of dicts: pick, round, team_key, yahoo_player_id, player_name.
    Yahoo returns player IDs only, so names are resolved in one batched
    player_details() call rather than one request per pick.
    """
    league = lg or getLeagueForYear(year)
    picks = league.draft_results()
    if not picks:
        raise RuntimeError(
            f"Yahoo returned no draft results for {year} -- either the draft never "
            f"happened or the league key is wrong."
        )

    player_ids = [int(pick['player_id']) for pick in picks]
    details = league.player_details(player_ids)
    names = {}
    for detail in details:
        name = detail.get('name') or {}
        names[int(detail['player_id'])] = name.get('full')

    rows = []
    for pick in picks:
        player_id = int(pick['player_id'])
        rows.append({
            'pick': int(pick['pick']),
            'round': int(pick['round']),
            'team_key': pick['team_key'],
            'yahoo_player_id': player_id,
            'player_name': names.get(player_id),
        })

    missing = [row['pick'] for row in rows if not row['player_name']]
    if missing:
        print(f"⚠️  {len(missing)} picks had no name from Yahoo (picks {missing[:5]}...)")
    return rows


def loadDraftResults(year, refresh=False):
    """Cached draft results as a DataFrame.

    Cached to data/raw so the mock draft never needs live OAuth -- Yahoo's OAuth
    can block on stdin when it is not run interactively, which would hang a test
    or a batch run. Fetch once per season by hand; grade as often as you like.
    """
    path = DRAFT_RESULTS_PATH.format(year=year)
    if not refresh and os.path.exists(path):
        return pd.read_csv(path)

    rows = getDraftResults(year)
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Wrote {len(df)} picks to {path}")
    return df
