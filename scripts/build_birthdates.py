r"""Fetch birthDate for every playerId in player_seasons (and goalie_seasons,
when built) via the NHL API landing endpoint, caching to
data/raw/player_birthdates.csv.

birthDates never change, so this only fetches ids the cache lacks: each
season's rookies, plus goalies if the goalie table was built after the cache.
Re-running is cheap and is the right way to refresh -- it is also **resumable**,
flushing progress every 100 players, so an interrupted run continues rather
than starting over.

    .\.venv\Scripts\python.exe scripts/build_birthdates.py
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402

from src import dataProcessing  # noqa: E402


PROCESSED_DIR = os.path.join(REPO_ROOT, 'data', 'processed')


def _player_ids():
    """Every id needing an age feature: skaters from player_seasons, plus
    goalies from goalie_seasons when that table exists (it is built later, and
    its ids were never in player_seasons)."""
    ids = set()
    for name, column in (('player_seasons.csv', 'playerId'),
                         ('goalie_seasons.csv', 'playerId')):
        path = os.path.join(PROCESSED_DIR, name)
        if os.path.exists(path):
            ids.update(pd.read_csv(path, usecols=[column])[column].dropna().astype(int))
        else:
            print(f"  (no {name} yet -- skipping those ids)")
    if not ids:
        raise FileNotFoundError(
            "Neither player_seasons.csv nor goalie_seasons.csv exists -- "
            "run scripts/build_player_seasons.py first")
    return sorted(ids)


def main():
    player_ids = _player_ids()
    print(f"{len(player_ids)} players need a birthDate; "
          f"only uncached ids are fetched (resumable, {dataProcessing.MAX_WORKERS} workers).")

    df = dataProcessing.appendMissingBirthDates(player_ids)

    got = df['birthDate'].notna().sum()
    print(f"\nDone: {len(df)} rows, {got} with a birthDate "
          f"({got / len(player_ids):.1%} of requested {len(player_ids)}).")
    if len(df) < len(player_ids):
        print(f"  {len(player_ids) - len(df)} players returned no landing data "
              f"(skipped) -- they'll get NaN age.")


if __name__ == '__main__':
    main()
