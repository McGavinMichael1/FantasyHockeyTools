# All MoneyPuck data IO lives here.
#
# MoneyPuck asks automated scrapers to obtain a data license, so there is
# deliberately NO auto-downloader: refresh data by downloading in a browser
# from https://moneypuck.com/data.htm into data/raw/. checkCurrentFreshness()
# reminds you when the current-season file is going stale.

import os
import time

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, '..', 'data', 'raw')
PROCESSED_DIR = os.path.join(BASE_DIR, '..', 'data', 'processed')

HISTORY_FILE = os.path.join(RAW_DATA_DIR, '2008_to_2024.csv')   # all situations, 2008-2024
CURRENT_FILE = os.path.join(RAW_DATA_DIR, 'moneypuck_current.csv')  # all situations, current season

STALE_DAYS = 3

# The subset of MoneyPuck's ~150 columns the pipeline uses — keeps the
# 2.6 GB history file readable in memory.
GAME_COLUMNS = [
    'playerId', 'name', 'gameId', 'season', 'gameDate', 'position', 'situation',
    'icetime', 'gameScore',
    'onIce_corsiPercentage', 'onIce_fenwickPercentage',
    'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_points',
    'I_F_xGoals', 'I_F_shotsOnGoal', 'I_F_hits', 'shotsBlockedByPlayer',
    'I_F_oZoneShiftStarts', 'I_F_dZoneShiftStarts', 'I_F_highDangerShots',
]


def checkCurrentFreshness(current_file=CURRENT_FILE):
    """Warn if the manually-downloaded current-season file is going stale."""
    if not os.path.exists(current_file):
        print(f"Missing {current_file} — download it from https://moneypuck.com/data.htm")
        return False
    age_days = (time.time() - os.path.getmtime(current_file)) / 86400
    if age_days > STALE_DAYS:
        print(f"moneypuck_current.csv is {age_days:.0f} days old — grab a fresh copy "
              f"in your browser from https://moneypuck.com/data.htm")
        return False
    return True


def loadGameLogs(min_season=2020, history_file=HISTORY_FILE,
                 current_file=CURRENT_FILE, cache_file=None):
    """Game logs with ALL situation rows, history + current season combined.

    Caches the filtered concat to data/processed/ — the cache is reused until
    the current-season file is replaced with a newer download.
    """
    # Check for required files first
    missing_files = []
    if not os.path.exists(history_file):
        missing_files.append(f"Historical data: {history_file}")
    if not os.path.exists(current_file):
        missing_files.append(f"Current season: {current_file}")

    if missing_files:
        print("\n" + "="*70)
        print("ERROR: Missing MoneyPuck data files")
        print("="*70)
        for f in missing_files:
            print(f"  ❌ {f}")
        print("\nTo download:")
        print("  1. Visit https://moneypuck.com/data.htm")
        print("  2. Download 'All Situations, 2008-2024' → save as:")
        print(f"     {history_file}")
        print("  3. Download 'All Situations, Current Season' → save as:")
        print(f"     {current_file}")
        print("="*70 + "\n")
        raise FileNotFoundError(f"Missing required MoneyPuck data files: {', '.join(missing_files)}")

    if cache_file is None:
        cache_file = os.path.join(PROCESSED_DIR, f'moneypuck_games_{min_season}.csv')
    if os.path.exists(cache_file):
        current_missing = not os.path.exists(current_file)
        if current_missing or os.path.getmtime(cache_file) > os.path.getmtime(current_file):
            return pd.read_csv(cache_file)

    print(f"Loading MoneyPuck data from {history_file} and {current_file}...")
    history = pd.read_csv(history_file, usecols=GAME_COLUMNS)
    history = history[history['season'] >= min_season]
    current = pd.read_csv(current_file, usecols=GAME_COLUMNS)
    df = pd.concat([history, current], ignore_index=True)
    df.sort_values(['playerId', 'gameDate'], inplace=True)
    df.to_csv(cache_file, index=False)
    print(f"Cached to {cache_file}")
    return df
