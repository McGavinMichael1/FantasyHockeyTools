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
    if cache_file is None:
        cache_file = os.path.join(PROCESSED_DIR, f'moneypuck_games_{min_season}.csv')
    if os.path.exists(cache_file):
        current_missing = not os.path.exists(current_file)
        if current_missing or os.path.getmtime(cache_file) > os.path.getmtime(current_file):
            return pd.read_csv(cache_file)

    history = pd.read_csv(history_file, usecols=GAME_COLUMNS)
    history = history[history['season'] >= min_season]
    current = pd.read_csv(current_file, usecols=GAME_COLUMNS)
    df = pd.concat([history, current], ignore_index=True)
    df.sort_values(['playerId', 'gameDate'], inplace=True)
    df.to_csv(cache_file, index=False)
    return df
