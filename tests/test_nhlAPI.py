"""Network-failure contract for the NHL API client.

These pin the fix for the July 2026 incident where a birthdate build hung for
12+ hours: `requests` has no default timeout, so a half-open socket blocks
forever, and the 429 loop had no attempt cap. Every test here must finish in
milliseconds -- a test that hangs IS the regression.
"""

import pytest
import requests

from src import nhlAPI


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = b'{}'

    def json(self):
        return self._payload


class FakeSession:
    """Records the kwargs every request was made with."""

    def __init__(self, responses):
        # responses: a list consumed in order, or a single response repeated
        self._responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({'url': url, **kwargs})
        if isinstance(self._responses, list):
            index = min(len(self.calls) - 1, len(self._responses) - 1)
            response = self._responses[index]
        else:
            response = self._responses
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Backoff is real seconds in production; tests must not actually wait."""
    monkeypatch.setattr(nhlAPI.time, 'sleep', lambda _seconds: None)


def _install(monkeypatch, responses):
    session = FakeSession(responses)
    monkeypatch.setattr(nhlAPI, 'session', lambda: session)
    return session


def test_every_request_sets_a_timeout(monkeypatch):
    """The whole point: an un-timeouted GET can block forever."""
    session = _install(monkeypatch, FakeResponse(200, {'standings': []}))

    nhlAPI.getPlayerStats(8478402)
    nhlAPI.getRosterData('TOR')
    nhlAPI.getTeamNames()

    assert len(session.calls) == 3
    for call in session.calls:
        assert call.get('timeout') is not None, f"no timeout on {call['url']}"
        connect, read = call['timeout']
        assert connect > 0 and read > 0


def test_rate_limiting_gives_up_instead_of_looping_forever(monkeypatch):
    """A perpetual 429 used to spin indefinitely at 15s per attempt."""
    session = _install(monkeypatch, FakeResponse(429))

    with pytest.raises(nhlAPI.NHLAPIError):
        nhlAPI.getPlayerStats(8478402)

    assert len(session.calls) == nhlAPI.MAX_ATTEMPTS


def test_rate_limiting_recovers_when_the_api_relents(monkeypatch):
    _install(monkeypatch, [FakeResponse(429), FakeResponse(200, {'birthDate': '1997-01-13'})])

    assert nhlAPI.getPlayerStats(8478402) == {'birthDate': '1997-01-13'}


def test_persistent_server_error_raises_rather_than_spinning(monkeypatch):
    """getRosterData's unexpected-status branch neither slept nor counted."""
    session = _install(monkeypatch, FakeResponse(500))

    with pytest.raises(nhlAPI.NHLAPIError):
        nhlAPI.getRosterData('TOR')

    assert len(session.calls) == nhlAPI.MAX_ATTEMPTS


def test_connection_failure_is_retried_then_surfaced(monkeypatch):
    """A stalled socket raises ConnectTimeout once the timeout is in place."""
    session = _install(monkeypatch, requests.exceptions.ConnectTimeout('stalled'))

    with pytest.raises(nhlAPI.NHLAPIError):
        nhlAPI.getPlayerStats(8478402)

    assert len(session.calls) == nhlAPI.MAX_ATTEMPTS


def test_transient_connection_failure_recovers(monkeypatch):
    _install(monkeypatch, [
        requests.exceptions.ConnectionError('reset'),
        FakeResponse(200, {'birthDate': '1997-01-13'}),
    ])

    assert nhlAPI.getPlayerStats(8478402) == {'birthDate': '1997-01-13'}


def test_get_team_names_extracts_abbreviations(monkeypatch):
    _install(monkeypatch, FakeResponse(200, {'standings': [
        {'teamAbbrev': {'default': 'TOR'}},
        {'teamAbbrev': {'default': 'MTL'}},
    ]}))

    assert nhlAPI.getTeamNames() == ['TOR', 'MTL']
