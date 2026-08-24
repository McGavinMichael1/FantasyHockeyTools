import pandas as pd

from src import moneypuck
from src import fantasyPoints
from src.features.shared import select_matrix

def loadMoneyPuckData():
    games = moneypuck.loadGameLogs(min_season=2020)
    # collapses to one row per player-game and scores with full league rules
    # (incl. hits, blocks, PPP/SHP from situation rows)
    moneyPuckData = fantasyPoints.moneypuckGamePoints(games)
    moneyPuckData = moneyPuckData.rename(columns={'fantasyPoints': 'game_fantasy_points'})
    moneyPuckData.sort_values(by=['playerId', 'gameDate'], inplace=True)
    moneyPuckData['ozone_start_pct'] = moneyPuckData['I_F_oZoneShiftStarts'] / ((moneyPuckData['I_F_oZoneShiftStarts'] + moneyPuckData['I_F_dZoneShiftStarts']).replace(0, 1))
    moneyPuckData['xgoals_surplus'] = moneyPuckData['I_F_goals'] - moneyPuckData['I_F_xGoals']
    moneyPuckData['high_danger_rate'] = moneyPuckData['I_F_highDangerShots'] / moneyPuckData['I_F_shotsOnGoal'].replace(0, 1)
    # Share of total ice time spent on the power play. A rate, not a level: a
    # 4th-liner with 1:30 of PP time is a different signal from a 1st-liner
    # with the same 1:30. Both are kept as features; the model picks.
    moneyPuckData['pp_toi_share'] = (
        moneyPuckData['powerPlayIcetime'] / moneyPuckData['icetime'].replace(0, 1))
    position_mapping = {'C': 0, 'L': 1, 'R': 2, 'D': 3}
    moneyPuckData['position_encoded'] = moneyPuckData['position'].map(position_mapping)
    return moneyPuckData

# Stats whose 5-vs-20-game gap is itself a signal. A rolling level cannot tell
# "has always been a PP1 guy" apart from "was promoted three games ago", and
# only the second is a breakout signal -- the Raddysh case in
# backtest.KNOWN_PICKUPS is exactly this.
TREND_DELTA_STATS = ['game_fantasy_points', 'icetime',
                     'powerPlayIcetime', 'pp_toi_share']


def buildRollingFeatures(df, windows=[5, 10, 20]):
    # icetime moved here from role_stats so its 20-game window exists for the
    # trend delta; the 5- and 10-game columns are unchanged.
    all_window_stats = ['I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
                        'I_F_xGoals', 'I_F_shotsOnGoal', 'game_fantasy_points',
                        'gameScore', 'ozone_start_pct', 'xgoals_surplus',
                        'high_danger_rate', 'icetime',
                        'powerPlayIcetime', 'pp_toi_share'] # all windows

    possession_stats = ['onIce_corsiPercentage', 'onIce_fenwickPercentage'] #10, 20 only

    for window in windows:
        for stat in all_window_stats:
            df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))
        if window >= 10:
            for stat in possession_stats:
                df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))

    # Trend deltas: recent form minus the longer baseline. Only computed when
    # both windows were actually built -- a silent per-stat skip would hide a
    # missing feature, so this guards once, explicitly.
    if {5, 20} <= set(windows):
        for stat in TREND_DELTA_STATS:
            df[f'rolling_delta_5_20_{stat}'] = (
                df[f'rolling_5_{stat}'] - df[f'rolling_20_{stat}'])

    # After the rolling windows loop
    df['season_avg_so_far'] = (
        df.groupby(['playerId', 'season'])['game_fantasy_points']
        .transform(lambda x: x.shift(1).expanding().mean())
    )

    return df

def buildLabel(df, hot_quantile=0.75, cold_quantile=0.25):
    # Continuous regression target: mean fantasy points over the next 5 games
    # (strictly future window — never includes the current game).
    df['next_5_avg'] = df.groupby(['playerId', 'season'])['game_fantasy_points'].transform(lambda x: x[::-1].rolling(5, min_periods=5).mean()[::-1].shift(-1))
    # Rank against the league that season rather than each player's own baseline.
    # A relative-to-self threshold lets low-output players (e.g. shot-blocking
    # defensemen) trigger "heating up" on ordinary block/hit variance without ever
    # producing fantasy-relevant totals. Percentile vs. the field ties the label
    # to actual absolute value. (Binary labels kept for diagnostics and the
    # parked LSTM; the pickup/cooling models now regress on next_5_avg.)
    next_5_percentile = df['next_5_avg'].groupby(df['season']).rank(pct=True)
    df['is_heating_up'] = (next_5_percentile >= hot_quantile).astype(int)
    df['is_cooling_down'] = (next_5_percentile <= cold_quantile).astype(int)
    df = df.dropna(subset=['season_avg_so_far'])
    df = df.dropna(subset=['next_5_avg'])
    return df

def pickupFeatureCols(df):
    """The pickup/cooling model's feature allowlist: all rolling-window stats
    plus the season-to-date average and encoded position."""
    feature_cols = [col for col in df.columns if col.startswith('rolling_')]
    feature_cols.append('season_avg_so_far')
    feature_cols.append('position_encoded')
    return feature_cols


def buildFeatureMatrix(df, label_col='is_heating_up'):
    return select_matrix(df, pickupFeatureCols(df), label_col)