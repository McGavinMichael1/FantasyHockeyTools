from src import yahooAPI


def test_team_key_for_league_uses_yahoos_resolved_numeric_league_key():
    team_key = yahooAPI._team_key_for_league(
        ['465.l.33072.t.9', '465.l.12345.t.1'],
        '465.l.33072',
    )

    assert team_key == '465.l.33072.t.9'
