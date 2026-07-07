r"""Phase B1 build: aggregate MoneyPuck game logs to one row per (playerId, season)
and cache to data/processed/player_seasons.csv.

This is a LONG first run -- loadGameLogs(min_season=2008) reads the full 2.6 GB
history file (and writes its own moneypuck_games_2008.csv game-level cache along
the way). Run it once; downstream draft-feature work reads the cheap season CSV.

    .\.venv\Scripts\python.exe scripts/build_player_seasons.py

Prints the GATE B1 acceptance numbers (row count, season span, a McDavid
spot-check) so you can sanity-check the aggregation before trusting it.
"""

import os
import sys

# Make `from src import ...` work regardless of where python is invoked from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402

from src import moneypuck  # noqa: E402

OUT_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'player_seasons.csv')


def main():
    # min_season=2008 (NOT loadGameLogs' 2020 default) -- the draft model trains
    # on the full history, so we need every season we have.
    print("Loading game logs from 2008 (first run reads the full 2.6 GB file)...")
    games = moneypuck.loadGameLogs(min_season=2008)

    print("Aggregating to one row per (playerId, season)...")
    seasons = moneypuck.buildPlayerSeasons(games)
    seasons.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}")

    # ---- GATE B1 acceptance checks -------------------------------------------
    n_rows = len(seasons)
    season_span = f"{seasons['season'].min()}-{seasons['season'].max()}"
    n_seasons = seasons['season'].nunique()
    print("\n" + "=" * 60)
    print("GATE B1 acceptance")
    print("=" * 60)
    print(f"rows:              {n_rows:,}")
    print(f"seasons:           {n_seasons}  ({season_span})")
    print(f"rows / season avg: {n_rows / n_seasons:,.0f}")
    print("  expect ~= (n_seasons x ~900 skaters); 2-3x that => situation rows")
    print("  were double-counted (aggregation bypassed moneypuckGamePoints).")

    # Spot-check: McDavid 2023-24 should read 32G/100A (PROJECT-PLAN Learning Log).
    mcdavid = seasons[
        seasons['full_name'].str.contains('McDavid', case=False, na=False)
        & (seasons['season'] == 2023)
    ]
    print("\nMcDavid 2023-24 spot-check (expect 32 G / 100 A):")
    if mcdavid.empty:
        print("  NOT FOUND -- check name/season handling before trusting output.")
    else:
        r = mcdavid.iloc[0]
        assists = r['totalPrimaryAssists'] + r['totalSecondaryAssists']
        print(f"  GP {r['gamesPlayed']:.0f} | G {r['totalGoals']:.0f} | "
              f"A {assists:.0f} | PPP {r['totalPPP']:.0f} "
              f"(PPP ~= 42 expected; official 44, known 5-on-3 undercount)")


if __name__ == '__main__':
    main()
