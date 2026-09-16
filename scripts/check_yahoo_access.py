r"""Staged Yahoo Fantasy API access check.

Run this after Yahoo approves a Fantasy Sports API access application, or any
time Yahoo calls start failing, to learn WHICH layer is broken:

    .\.venv\Scripts\python.exe scripts\check_yahoo_access.py

Stages get strictly more demanding, so the first failure names the cause:

  1-2 fail  -> the app itself is not approved (or oauth2.json holds the wrong
               app's consumer key). Re-authenticating will NOT help.
  3+ fail   -> the app is approved but this league/season/team lookup is wrong.

A 403 saying "you are not in this league" is the OPPOSITE of a 403 saying "this
application is not authorized": the first means the app is fine and the league
key is wrong (almost always a bare `nhl.l.<id>` key, which silently follows
Yahoo's game rollover into someone else's league).

Stage 2 must assert on the HTTP status: Yahoo returns a well-formed JSON body
with a 403, so reading the body without checking the code reports a refusal as
a success.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa

from src import yahooAPI
from src.season import CURRENT_SEASON

OAUTH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'oauth2.json')

results = []


def stage(name, fn, verbose=False):
    print(f"\n=== {name} ===", flush=True)
    try:
        out = fn()
        print(f"PASS: {out}", flush=True)
        results.append((name, True))
        return out
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {str(error)[:400]}", flush=True)
        if verbose:
            traceback.print_exc()
        results.append((name, False))
        return None


def main(verbose=False):
    oauth = OAuth2(None, None, from_file=OAUTH_PATH)

    def token():
        if not oauth.token_is_valid():
            oauth.refresh_access_token()
            return "refreshed"
        return "valid"

    stage("1. OAuth token", token, verbose)

    def gated():
        response = oauth.session.get(
            'https://fantasysports.yahooapis.com/fantasy/v2/game/nhl',
            params={'format': 'json'})
        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP {response.status_code} -- {response.text[:200]}")
        return "HTTP 200 -- the app is approved for Fantasy Sports"

    approved = stage("2. /game/nhl (app-level approval)", gated, verbose)
    if not approved:
        print(
            "\nStopping: every later stage needs an approved app.\n"
            "  * Apply/check status at https://sports.yahoo.com/developer/access/\n"
            "  * Confirm oauth2.json's consumer_key is the SAME app Yahoo approved\n"
            f"    (current key starts {_key_prefix()})\n"
            "  * Re-running the OAuth flow does NOT fix a 403 here.")
        return summary()

    gm = yfa.Game(oauth, 'nhl')
    live_season = stage("3. live season (Yahoo's current NHL game)",
                        lambda: yahooAPI.currentLeagueSeason(gm), verbose)
    stage("4. league_ids for both seasons",
          lambda: {yr: gm.league_ids(seasons=[str(yr)], game_codes=['nhl'])
                   for yr in (live_season - 1, live_season)}, verbose)

    # Two leagues, deliberately. The live one is where we draft and play; the
    # previous one is the only place our current roster still exists.
    live = stage("5. live league", yahooAPI.getLeague, verbose)
    if live:
        stage("5b. live league settings",
              lambda: {k: live.settings().get(k)
                       for k in ('name', 'num_teams', 'season', 'league_key',
                                 'draft_status')}, verbose)
        stage("5c. my team key (live)", lambda: yahooAPI.getMyTeamKey(live), verbose)

    source = stage("6. roster-source league (previous season)",
                   yahooAPI.getRosterLeague, verbose)
    if source:
        stage("6b. its settings",
              lambda: {k: source.settings().get(k)
                       for k in ('name', 'season', 'league_key')}, verbose)
        stage("7. my roster",
              lambda: [p['name'] for p in yahooAPI.getMyRoster(source)], verbose)
        stage("8. all rostered players",
              lambda: f"{len(yahooAPI.getRosteredIds(source))} names", verbose)

    stage("9. previous season's draft results (live fetch)",
          lambda: f"{len(yahooAPI.getDraftResults(CURRENT_SEASON - 1))} picks",
          verbose)
    return summary()


def _key_prefix():
    import json
    try:
        with open(OAUTH_PATH) as handle:
            return json.load(handle)['consumer_key'][:14] + '...'
    except Exception:
        return '<unreadable>'


def summary():
    print("\n=== SUMMARY ===")
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == '__main__':
    sys.exit(main(verbose='-v' in sys.argv))
