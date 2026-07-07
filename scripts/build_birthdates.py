r"""Fetch birthDate for every playerId in player_seasons via the NHL API landing
endpoint and cache to data/raw/player_birthdates.csv.

One-time build (birthDates never change). Covers retired players that
players_cache.csv -- current roster only -- misses; the age-at-season-start
draft feature needs full historical coverage.

    .\.venv\Scripts\python.exe scripts/build_birthdates.py

Run with PYTHONUTF8=1 on Windows: getPlayerStats prints response previews
containing non-ASCII player names (cp1252 consoles crash otherwise).
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402

from src import dataProcessing  # noqa: E402


def main():
    seasons = pd.read_csv(
        os.path.join(REPO_ROOT, 'data', 'processed', 'player_seasons.csv'))
    player_ids = sorted(seasons['playerId'].unique().tolist())
    print(f"Fetching birthDate for {len(player_ids)} players "
          f"(threaded, 5 workers; ~minutes)...")

    df = dataProcessing.getAllBirthDatesWithCache(player_ids)

    got = df['birthDate'].notna().sum()
    print(f"\nDone: {len(df)} rows, {got} with a birthDate "
          f"({got / len(player_ids):.1%} of requested {len(player_ids)}).")
    if len(df) < len(player_ids):
        print(f"  {len(player_ids) - len(df)} players returned no landing data "
              f"(skipped) -- they'll get NaN age.")


if __name__ == '__main__':
    main()
