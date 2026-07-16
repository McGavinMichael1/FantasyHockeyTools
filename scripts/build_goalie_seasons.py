r"""Build data/processed/goalie_seasons.csv: MoneyPuck goalie skill data merged
with NHL API season records (W/L/SO/GS) and scored with GOALIE_WEIGHTS.

One-time build per season. First run fetches ~500 goalies' landing pages
(threaded, minutes) into the permanent cache data/raw/goalie_nhl_seasons.csv,
and appends goalie birthDates to data/raw/player_birthdates.csv. At season
rollover, delete goalie_nhl_seasons.csv so everyone's new season is fetched.

    $env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts/build_goalie_seasons.py

PYTHONUTF8=1 is required: getPlayerStats prints response previews with
non-ASCII names (cp1252 consoles crash otherwise).
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src import dataProcessing  # noqa: E402
from src import moneypuck  # noqa: E402
from src.features import goalies  # noqa: E402

OUT_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'goalie_seasons.csv')


def main():
    mp = moneypuck.loadGoalieSeasons()
    ids = sorted(mp['playerId'].unique().tolist())
    print(f"MoneyPuck: {len(mp)} goalie-season rows, {len(ids)} goalies")

    print("Fetching NHL API season records (threaded; minutes on first run)...")
    nhl = dataProcessing.getGoalieSeasonsWithCache(ids)

    print("Appending goalie birthDates to the shared cache...")
    dataProcessing.appendMissingBirthDates(ids)

    seasons = goalies.build_goalie_seasons(mp, nhl)
    seasons.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}")

    # ---- GATE G1 acceptance checks ----------------------------------------
    hit_rate = len(seasons) / len(mp)
    print("\n" + "=" * 60)
    print("GATE G1 acceptance")
    print("=" * 60)
    print(f"rows:               {len(seasons):,} (expect ~1,400-1,700)")
    print(f"seasons:            {seasons['season'].nunique()} "
          f"({seasons['season'].min()}-{seasons['season'].max()}; expect 18)")
    print(f"merge hit rate:     {hit_rate:.1%} of MoneyPuck rows (expect >= 95%)")
    print("  a low hit rate means the playerId or season-key join is broken --")
    print("  measure before trusting (the birthdates lesson).")
    if len(seasons) > 3000:
        print("  WARNING: row count ~5x expected => situation rows leaked through.")

    hellebuyck = seasons[
        seasons['full_name'].str.contains('Hellebuyck', case=False, na=False)
        & (seasons['season'] == 2023)]
    print("\nHellebuyck 2023-24 spot-check (verify against hockey-reference.com):")
    if hellebuyck.empty:
        print("  NOT FOUND -- check name/join handling before trusting output.")
    else:
        r = hellebuyck.iloc[0]
        print(f"  GP {r['gamesPlayed']:.0f} | GS {r['gamesStarted']:.0f} | "
              f"W {r['wins']:.0f} | L {r['losses']:.0f} | SO {r['shutouts']:.0f} | "
              f"SV {r['saves']:.0f} | FP {r['fantasyPoints']:.1f} "
              f"({r['fpPerGame']:.2f}/gm)")


if __name__ == '__main__':
    main()
