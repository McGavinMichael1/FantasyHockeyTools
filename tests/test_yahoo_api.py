import pytest

from src import yahooAPI


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

    def __init__(self, picks, details, team_keys=(MY_TEAM, OTHER_TEAM)):
        self._picks = picks
        self._details = details
        self.player_details_calls = []
        self.yhandler = FakeYHandler(team_keys)

    def settings(self):
        return {'league_key': LEAGUE_KEY}

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


def test_get_draft_results_keeps_picks_whose_name_yahoo_cannot_resolve():
    # Dropping the row would shift every later pick's position in the replay.
    league = FakeLeague(
        picks=[_pick(1, 1, MY_TEAM, 6743), _pick(2, 1, OTHER_TEAM, 999)],
        details=[_detail(6743, 'Connor McDavid')],
    )

    rows = yahooAPI.getDraftResults(2025, lg=league)

    assert len(rows) == 2
    assert rows[1]['player_name'] is None
