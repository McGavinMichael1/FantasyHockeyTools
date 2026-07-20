import pytest

from src import keeper, yahooAPI


class FakeGame:
    """Stands in for yfa.Game to test league resolution without OAuth."""

    def __init__(self, ids_by_call, leagues=None):
        self.ids_by_call = ids_by_call
        self.leagues = leagues or {}
        self.league_ids_kwargs = []

    def league_ids(self, **kwargs):
        self.league_ids_kwargs.append(kwargs)
        return self.ids_by_call

    def to_league(self, league_id):
        return self.leagues.get(league_id, league_id)


def test_team_key_for_league_uses_yahoos_resolved_numeric_league_key():
    team_key = yahooAPI._team_key_for_league(
        ['465.l.33072.t.9', '465.l.12345.t.1'],
        '465.l.33072',
    )

    assert team_key == '465.l.33072.t.9'


LEAGUE_KEY = '465.l.33072'
MY_TEAM = f'{LEAGUE_KEY}.t.4'
OTHER_TEAM = f'{LEAGUE_KEY}.t.9'


class FakeYHandler:
    def __init__(self, team_keys):
        self._team_keys = team_keys

    def get_teams_raw(self):
        return {'teams': [{'team_key': key} for key in self._team_keys]}


class FakeLeague:
    """Stands in for yfa.League so draft parsing is tested without OAuth."""

    def __init__(self, picks, details, team_keys=(MY_TEAM, OTHER_TEAM),
                 name=None, num_teams=None):
        self._picks = picks
        self._details = details
        self._name = yahooAPI.LEAGUE_NAME if name is None else name
        self._num_teams = keeper.TEAM_COUNT if num_teams is None else num_teams
        self.player_details_calls = []
        self.yhandler = FakeYHandler(team_keys)

    def settings(self):
        return {'league_key': LEAGUE_KEY, 'name': self._name,
                'num_teams': self._num_teams}

    def draft_results(self):
        return self._picks

    def player_details(self, player_ids):
        self.player_details_calls.append(player_ids)
        return [d for d in self._details if int(d['player_id']) in set(player_ids)]


def _pick(pick, rnd, team, player_id):
    return {'pick': pick, 'round': rnd, 'team_key': team, 'player_id': player_id}


def _detail(player_id, full_name):
    return {'player_id': str(player_id), 'name': {'full': full_name}}


def test_get_draft_results_joins_names_onto_picks_and_flags_the_owners():
    league = FakeLeague(
        picks=[_pick(1, 1, MY_TEAM, 6743), _pick(2, 1, OTHER_TEAM, 5980)],
        details=[_detail(6743, 'Connor McDavid'), _detail(5980, 'Nathan MacKinnon')],
    )

    rows = yahooAPI.getDraftResults(2025, lg=league)

    assert rows == [
        {'pick': 1, 'round': 1, 'team_key': MY_TEAM,
         'yahoo_player_id': 6743, 'player_name': 'Connor McDavid', 'is_mine': True},
        {'pick': 2, 'round': 1, 'team_key': OTHER_TEAM,
         'yahoo_player_id': 5980, 'player_name': 'Nathan MacKinnon', 'is_mine': False},
    ]


def test_get_draft_results_resolves_names_in_one_batched_call():
    # One request per pick would be ~200 calls against a rate-limited API.
    league = FakeLeague(
        picks=[_pick(i, 1, MY_TEAM if i == 1 else OTHER_TEAM, 1000 + i)
               for i in range(1, 31)],
        details=[_detail(1000 + i, f'Player {i}') for i in range(1, 31)],
    )

    yahooAPI.getDraftResults(2025, lg=league)

    assert len(league.player_details_calls) == 1
    assert len(league.player_details_calls[0]) == 30


def test_get_draft_results_raises_when_no_pick_belongs_to_the_owner():
    # Otherwise the mock draft grades the board against an empty roster and
    # "wins" meaninglessly.
    league = FakeLeague(
        picks=[_pick(1, 1, OTHER_TEAM, 6743)],
        details=[_detail(6743, 'Connor McDavid')],
    )

    with pytest.raises(RuntimeError, match='belong to team'):
        yahooAPI.getDraftResults(2025, lg=league)


def test_get_draft_results_raises_when_the_draft_has_not_happened():
    # An empty list is what Yahoo returns for a not-yet-drafted league. Grading a
    # mock draft against zero picks would silently "win" against an empty roster.
    league = FakeLeague(picks=[], details=[])

    with pytest.raises(RuntimeError, match='no draft results'):
        yahooAPI.getDraftResults(2026, lg=league)


class NamedLeague:
    def __init__(self, name, num_teams=None):
        self._name = name
        self._num_teams = keeper.TEAM_COUNT if num_teams is None else num_teams

    def settings(self):
        return {'name': self._name, 'num_teams': self._num_teams}


def test_league_lookup_filters_to_hockey():
    # Regression: yfa.Game(oauth, 'nhl') does NOT scope league_ids(). Without an
    # explicit game_codes filter, season 2025 returned five leagues across
    # several sports and the first was fantasy BASEBALL -- Shohei Ohtani in a
    # hockey draft board's backtest.
    gm = FakeGame(['465.l.33072'])

    yahooAPI._nhl_league_ids(gm, 2025)

    assert gm.league_ids_kwargs[0]['game_codes'] == ['nhl']


def test_several_nhl_leagues_resolve_by_league_name():
    # The numeric id changes every season (2024: 453.l.27273, 2025:
    # 465.l.33072), so the name is the only stable identifier across years.
    right, wrong = '465.l.33072', '465.l.19487'
    gm = FakeGame([wrong, right], leagues={
        wrong: NamedLeague("Michael's Genius League", num_teams=2),
        right: NamedLeague(yahooAPI.LEAGUE_NAME),
    })

    assert yahooAPI._resolve_league(gm, 2025) is gm.leagues[right]


def test_ambiguous_leagues_raise_instead_of_guessing():
    # Taking [0] is what produced the baseball draft. A wrong league does not
    # fail loudly on its own -- it returns a well-formed, meaningless draft.
    gm = FakeGame(['a', 'b'], leagues={
        'a': NamedLeague('Some Other League'),
        'b': NamedLeague('Yet Another League'),
    })

    with pytest.raises(RuntimeError, match='Could not identify'):
        yahooAPI._resolve_league(gm, 2025)


def test_draft_fetch_refuses_a_league_with_the_wrong_name():
    league = FakeLeague(
        picks=[_pick(1, 1, MY_TEAM, 6743)],
        details=[_detail(6743, 'Connor McDavid')],
        name='Some Baseball League',
    )

    with pytest.raises(RuntimeError, match='Refusing to grade'):
        yahooAPI.getDraftResults(2025, lg=league)


def test_draft_fetch_refuses_a_league_with_the_wrong_team_count():
    # The keeper math hardcodes 10 teams; a 12-team league would be graded with
    # the wrong replacement levels and pick costs.
    league = FakeLeague(
        picks=[_pick(1, 1, MY_TEAM, 6743)],
        details=[_detail(6743, 'Connor McDavid')],
        num_teams=12,
    )

    with pytest.raises(RuntimeError, match='teams'):
        yahooAPI.getDraftResults(2025, lg=league)


def test_get_draft_results_keeps_picks_whose_name_yahoo_cannot_resolve():
    # Dropping the row would shift every later pick's position in the replay.
    league = FakeLeague(
        picks=[_pick(1, 1, MY_TEAM, 6743), _pick(2, 1, OTHER_TEAM, 999)],
        details=[_detail(6743, 'Connor McDavid')],
    )

    rows = yahooAPI.getDraftResults(2025, lg=league)

    assert len(rows) == 2
    assert rows[1]['player_name'] is None
