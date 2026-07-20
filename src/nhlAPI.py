# NHL API client. Identity, roster and landing data only -- MoneyPuck is the
# stats source (see fht-architecture-contract).
#
# Every request goes through _get(), the single place that touches the network.
# It exists because of a July 2026 incident: a birthdate build hung for 12+
# hours on a laptop. `requests` has NO default timeout, so a half-open socket
# (different wifi, captive portal, idle connection dropped by an ISP) blocks
# forever rather than erroring -- and the 429 branch retried without an attempt
# cap. _get sets a hard timeout, bounds every retry, and backs off on 429, so a
# bad network fails in seconds instead of hanging a build overnight.
#
# Response logging is logger.debug, not print: the old per-request status +
# 200-char preview was thousands of non-ASCII console writes per build, which
# is both slow on Windows and the source of the cp1252 UnicodeEncodeError.

import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api-web.nhle.com/v1"

# (connect, read) seconds. Read is generous -- the landing endpoint is slow for
# long-career players -- but finite, which is the whole point.
TIMEOUT = (5, 30)
MAX_ATTEMPTS = 5
# Successive 429 waits. The API rate-limits hard when several workers hammer
# it; escalating beats the old flat 15s, which could never drain a sustained
# limit.
RATE_LIMIT_BACKOFF = (15, 30, 60, 120)


class NHLAPIError(RuntimeError):
    """A request exhausted MAX_ATTEMPTS.

    Subclasses RuntimeError so existing callers that catch RuntimeError
    (dataProcessing's per-player workers) still skip the player rather than
    crashing the whole build.
    """


_session = None


def session():
    """Shared connection-pooled session. Replaced wholesale in tests."""
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _get(url, timeout=TIMEOUT):
    """GET and return parsed JSON, or raise NHLAPIError. Never loops forever."""
    status = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session().get(url, timeout=timeout)
        except requests.RequestException as error:
            logger.debug("%s attempt %d failed: %s", url, attempt + 1, error)
            if attempt == MAX_ATTEMPTS - 1:
                raise NHLAPIError(
                    f"{url} failed after {MAX_ATTEMPTS} attempts: {error}") from error
            time.sleep(min(2 ** attempt, 30))
            continue

        status = response.status_code
        if status == 200:
            return response.json()

        if status == 429:
            delay = RATE_LIMIT_BACKOFF[min(attempt, len(RATE_LIMIT_BACKOFF) - 1)]
            logger.warning("Rate limited on %s; waiting %ds", url, delay)
            time.sleep(delay)
            continue

        logger.debug("%s returned %d (attempt %d)", url, status, attempt + 1)
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(min(2 ** attempt, 30))

    raise NHLAPIError(
        f"NHL API returned {status} for {url} after {MAX_ATTEMPTS} attempts")


def getRosterData(team):
    return _get(f"{BASE_URL}/roster/{team}/current")


def getTeamNames():
    """Team abbreviations, from the standings endpoint."""
    data = _get(f"{BASE_URL}/standings/now")
    return [team['teamAbbrev']['default'] for team in data['standings']]


def getPlayerStats(player_id):
    return _get(f"{BASE_URL}/player/{player_id}/landing")
