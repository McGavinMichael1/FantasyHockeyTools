# All MoneyPuck data IO lives here.
#
# MoneyPuck asks automated scrapers to obtain a data license, so there is
# deliberately NO auto-downloader: refresh data by downloading in a browser
# from https://moneypuck.com/data.htm into data/raw/. checkCurrentFreshness()
# reminds you when the current-season file is going stale.

import os
import time

import pandas as pd

from src import fantasyPoints

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, '..', 'data', 'raw')
PROCESSED_DIR = os.path.join(BASE_DIR, '..', 'data', 'processed')

HISTORY_FILE = os.path.join(RAW_DATA_DIR, '2008_to_2024.csv')   # all situations, 2008-2024
CURRENT_FILE = os.path.join(RAW_DATA_DIR, 'moneypuck_current.csv')  # all situations, current season

GOALIE_DIR = os.path.join(RAW_DATA_DIR, 'goalies')
GOALIE_HISTORY_SEASONS_FILE = os.path.join(GOALIE_DIR, 'goalies_2008_to_2024_seasons.csv')
GOALIE_CURRENT_SEASONS_FILE = os.path.join(GOALIE_DIR, 'goalies_current_seasons.csv')
GOALIE_SEASON_COLUMNS = ['playerId', 'season', 'name', 'situation',
                         'games_played', 'icetime', 'xGoals', 'goals', 'ongoal']

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

def buildPlayerSeasons(game_df):
    """One row per (playerId, season), aggregated from full-situation game logs.

    game_df must contain ALL situation rows (as returned by loadGameLogs) --
    fantasyPoints.moneypuckGamePoints collapses them to one row per player-game
    (situation == 'all', plus derived PPP/SHP/fantasyPoints) before aggregating.
    Summing the raw situation rows directly would double-count every stat, since
    the 'all' row already totals the situation-specific rows.
    """
    games = fantasyPoints.moneypuckGamePoints(game_df)

    summary = games.groupby(['playerId', 'season']).agg(
        gamesPlayed=('gameId', 'nunique'),
        full_name=('name', lambda s: s.mode().iloc[0]),  # MoneyPuck's name has rare spelling
                                                           # variants across rows -- take the
                                                           # most common one per player-season
        position=('position', lambda s: s.mode().iloc[0]),  # most common position that season
        avgIcetime=('icetime', 'mean'),
        avgGameScore=('gameScore', 'mean'),
        avgCorsiPercentage=('onIce_corsiPercentage', 'mean'),
        avgFenwickPercentage=('onIce_fenwickPercentage', 'mean'),
        totalGoals=('I_F_goals', 'sum'),
        totalPrimaryAssists=('I_F_primaryAssists', 'sum'),
        totalSecondaryAssists=('I_F_secondaryAssists', 'sum'),
        totalPoints=('I_F_points', 'sum'),
        totalShotsOnGoal=('I_F_shotsOnGoal', 'sum'),
        totalHits=('I_F_hits', 'sum'),
        totalShotsBlocked=('shotsBlockedByPlayer', 'sum'),
        totalXGoals=('I_F_xGoals', 'sum'),
        totalHighDangerShots=('I_F_highDangerShots', 'sum'),
        totalPPP=('powerPlayPoints', 'sum'),
        totalPPGoals=('powerPlayGoals', 'sum'),
        totalPPAssists=('powerPlayAssists', 'sum'),
        totalSHP=('shorthandedPoints', 'sum'),
        totalFP=('fantasyPoints', 'sum'),
    ).reset_index()

    summary['fpPerGame'] = summary['totalFP'] / summary['gamesPlayed']
    summary['xGoalsSurplus'] = summary['totalGoals'] - summary['totalXGoals']
    summary['highDangerShare'] = (
        summary['totalHighDangerShots'] / summary['totalShotsOnGoal'].replace(0, 1)
    )

    return summary


def buildPickupStats(game_df, season):
    """One row per player for the pickup heuristic: season totals plus
    last-5-game totals for the given season, scored with full league weights
    (incl. hits/blocks; no plusMinus/GWG -- the accepted MoneyPuck
    approximation).

    game_df must contain ALL situation rows (loadGameLogs output) --
    moneypuckGamePoints collapses them; summing raw rows double-counts.
    The season id is a parameter so this module doesn't grow its own copy
    of the CURRENT_SEASON constant.
    """
    season_games = game_df[game_df['season'] == season]
    if season_games.empty:
        return pd.DataFrame(columns=[
            'playerId', 'name', 'position', 'gamesPlayed', 'goals',
            'assists', 'points', 'shots', 'hits', 'blocks',
            'powerPlayPoints', 'shorthandedPoints', 'fantasyPoints',
            'season_ppg', 'avgToiSeconds', 'last5_goals', 'last5_assists',
            'last5_points', 'last5_fantasyPoints'])
    games = fantasyPoints.moneypuckGamePoints(season_games)
    games = games.sort_values(['playerId', 'gameDate'])
    games['assists'] = games['I_F_primaryAssists'] + games['I_F_secondaryAssists']

    totals = games.groupby('playerId').agg(
        name=('name', lambda s: s.mode().iloc[0]),
        position=('position', lambda s: s.mode().iloc[0]),
        gamesPlayed=('gameId', 'nunique'),
        goals=('I_F_goals', 'sum'),
        assists=('assists', 'sum'),
        points=('I_F_points', 'sum'),
        shots=('I_F_shotsOnGoal', 'sum'),
        hits=('I_F_hits', 'sum'),
        blocks=('shotsBlockedByPlayer', 'sum'),
        powerPlayPoints=('powerPlayPoints', 'sum'),
        shorthandedPoints=('shorthandedPoints', 'sum'),
        fantasyPoints=('fantasyPoints', 'sum'),
        avgToiSeconds=('icetime', 'mean'),
    ).reset_index()
    totals['season_ppg'] = totals['fantasyPoints'] / totals['gamesPlayed'].replace(0, 1)

    last5 = (games.groupby('playerId').tail(5)
             .groupby('playerId').agg(
                 last5_goals=('I_F_goals', 'sum'),
                 last5_assists=('assists', 'sum'),
                 last5_points=('I_F_points', 'sum'),
                 last5_fantasyPoints=('fantasyPoints', 'sum'),
             ).reset_index())
    return totals.merge(last5, on='playerId', how='left')


def loadGoalieSeasons(history_file=GOALIE_HISTORY_SEASONS_FILE,
                      current_file=GOALIE_CURRENT_SEASONS_FILE):
    """Season-level MoneyPuck goalie rows, 'all'-situation only.

    The raw files carry one row per situation per goalie-season (and one row
    per team stint for traded goalies); the 'all' row already totals the
    situation rows, so only 'all' survives and stints are summed. `goals`
    here means goals AGAINST; `ongoal` is shots on goal against.
    """
    for path in (history_file, current_file):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{path} missing -- download the goalie season CSVs from "
                "moneypuck.com/data.htm into data/raw/goalies/ "
                "(see that folder's README.md for which file is which)")
    frames = [pd.read_csv(f, usecols=GOALIE_SEASON_COLUMNS)
              for f in (history_file, current_file)]
    df = pd.concat(frames, ignore_index=True)
    df = df[df['situation'] == 'all'].drop(columns=['situation'])
    return (df.groupby(['playerId', 'season'], as_index=False)
              .agg(name=('name', 'first'),
                   games_played=('games_played', 'sum'),
                   icetime=('icetime', 'sum'),
                   xGoals=('xGoals', 'sum'),
                   goals=('goals', 'sum'),
                   ongoal=('ongoal', 'sum')))