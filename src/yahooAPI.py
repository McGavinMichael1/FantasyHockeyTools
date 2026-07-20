from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import objectpath
import os
import pandas as pd
from src import dataProcessing
from src import keeper
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


def getMyTeamKey(league):
    """The authenticated account's team key within one league."""
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
    return team_key

def getMyRoster(lg=None):
    """Return the authenticated Yahoo manager's current roster."""
    league = lg or getLeague()
    return league.to_team(getMyTeamKey(league)).roster(league.current_week())

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


LEAGUE_NAME = 'Greasy Slappy'


def _nhl_league_ids(gm, year):
    """League keys for one season, filtered to hockey.

    game_codes is NOT optional. Constructing yfa.Game(oauth, 'nhl') does not
    scope league_ids(): asking for season 2025 without it returns every sport
    the account played, and taking the first would grade an NHL draft board
    against a fantasy BASEBALL draft -- which is exactly what happened once.
    """
    try:
        return gm.league_ids(seasons=[str(year)], game_codes=['nhl'])
    except Exception as error:
        print(f"seasons lookup failed ({error}); falling back to the year endpoint")
        # The deprecated year endpoint is already game-scoped by yfa.Game.
        return gm.league_ids(year=year)


def _resolve_league(gm, year):
    """Pick this owner's NHL league out of everything the account played.

    The numeric league id changes every season (2024 was 453.l.27273, 2025 is
    465.l.33072), so the league NAME is the only stable identifier across years.
    Where several NHL leagues exist for one season, the one named LEAGUE_NAME
    wins; anything still ambiguous raises rather than guesses.
    """
    league_ids = _nhl_league_ids(gm, year)
    if not league_ids:
        raise RuntimeError(
            f"No Yahoo NHL league found for {year}. The authenticated account may "
            f"not have played that season, or the OAuth token lacks history access."
        )
    if len(league_ids) == 1:
        return gm.to_league(league_ids[0])

    named = []
    for candidate in league_ids:
        try:
            settings = gm.to_league(candidate).settings()
        except Exception as error:
            print(f"⚠️  Could not read settings for {candidate} ({error}); skipping")
            continue
        if settings.get('name') == LEAGUE_NAME:
            named.append(candidate)

    if len(named) == 1:
        return gm.to_league(named[0])
    raise RuntimeError(
        f"Could not identify the {year} league. NHL leagues found: {league_ids}; "
        f"{len(named)} named '{LEAGUE_NAME}'. Re-run with an explicit league_id "
        f"rather than guessing -- grading the wrong league produces a confident, "
        f"meaningless result."
    )


def getLeagueForYear(year, league_id=None):
    """The authenticated user's NHL league for one season, by draft year.

    Yahoo's season numbering follows the draft: the league drafted in Oct 2025
    is season 2025, matching the MoneyPuck convention used everywhere else.
    Pass `league_id` to bypass resolution entirely.
    """
    oauth = OAuth2(None, None, from_file=os.path.join(BASE_DIR, '..', 'oauth2.json'))
    gm = yfa.Game(oauth, 'nhl')
    if league_id:
        return gm.to_league(league_id)
    return _resolve_league(gm, year)


def _assert_expected_league(league, year):
    """Refuse to grade a league that is not this one.

    Belt-and-braces behind getLeagueForYear's name matching. A wrong league does
    not fail loudly on its own -- it returns a perfectly well-formed draft that
    produces a confident, meaningless verdict. Checking the name and team count
    costs one request and makes that failure impossible to miss.
    """
    try:
        settings = league.settings()
    except Exception as error:
        print(f"⚠️  Could not verify the {year} league identity ({error})")
        return

    name = settings.get('name')
    if name != LEAGUE_NAME:
        raise RuntimeError(
            f"The {year} league resolved to '{name}', not '{LEAGUE_NAME}'. "
            f"Refusing to grade a draft from a different league."
        )

    teams = settings.get('num_teams')
    if teams is not None and int(teams) != keeper.TEAM_COUNT:
        raise RuntimeError(
            f"The {year} league '{name}' has {teams} teams, but the keeper math "
            f"assumes {keeper.TEAM_COUNT} (src/keeper.py). Refusing to grade it."
        )


def getDraftResults(year, lg=None):
    """Every pick of one season's draft, newest-first order preserved.

    Returns a list of dicts: pick, round, team_key, yahoo_player_id, player_name,
    is_mine. Yahoo returns player IDs only, so names are resolved in one batched
    player_details() call rather than one request per pick.

    `is_mine` is resolved here rather than at grading time so the cached CSV
    carries everything the replay needs -- otherwise every mock-draft run would
    have to re-authenticate just to learn which team was the owner's.
    """
    league = lg or getLeagueForYear(year)
    _assert_expected_league(league, year)
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

    my_team_key = getMyTeamKey(league)

    rows = []
    for pick in picks:
        player_id = int(pick['player_id'])
        rows.append({
            'pick': int(pick['pick']),
            'round': int(pick['round']),
            'team_key': pick['team_key'],
            'yahoo_player_id': player_id,
            'player_name': names.get(player_id),
            'is_mine': pick['team_key'] == my_team_key,
        })

    if not any(row['is_mine'] for row in rows):
        raise RuntimeError(
            f"No {year} picks belong to team {my_team_key}. Grading would compare "
            f"the board against an empty roster and 'win' meaninglessly."
        )

    missing = [row['pick'] for row in rows if not row['player_name']]
    if missing:
        print(f"⚠️  {len(missing)} picks had no name from Yahoo (picks {missing[:5]}...)")
    return rows


def loadDraftResults(year, refresh=False, league_id=None):
    """Cached draft results as a DataFrame.

    Cached to data/raw so the mock draft never needs live OAuth -- Yahoo's OAuth
    can block on stdin when it is not run interactively, which would hang a test
    or a batch run. Fetch once per season by hand; grade as often as you like.
    """
    path = DRAFT_RESULTS_PATH.format(year=year)
    if not refresh and os.path.exists(path):
        return pd.read_csv(path)

    rows = getDraftResults(year, lg=getLeagueForYear(year, league_id=league_id))
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Wrote {len(df)} picks to {path}")
    return df
