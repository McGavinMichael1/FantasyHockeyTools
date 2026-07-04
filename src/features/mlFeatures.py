import pandas as pd

from src import moneypuck
from src import fantasyPoints

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
    position_mapping = {'C': 0, 'L': 1, 'R': 2, 'D': 3}
    moneyPuckData['position_encoded'] = moneyPuckData['position'].map(position_mapping)
    return moneyPuckData

def buildRollingFeatures(df, windows=[5, 10, 20]):
    all_window_stats = ['I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_xGoals', 'I_F_shotsOnGoal', 'game_fantasy_points', 'gameScore', 'ozone_start_pct', 'xgoals_surplus', 'high_danger_rate'] # all windows

    possession_stats = ['onIce_corsiPercentage', 'onIce_fenwickPercentage'] #10, 20 only

    role_stats = ['icetime'] # 5, 10 only

    for window in windows:
        for stat in all_window_stats:
            df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))
        if window >= 10:
            for stat in possession_stats:
                df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))
        if window <= 10:
            for stat in role_stats:
                df[f'rolling_{window}_{stat}'] = (df.groupby('playerId')[stat].transform(lambda x: x.rolling(window, min_periods=1).mean()))
    # After the rolling windows loop
    df['season_avg_so_far'] = (
        df.groupby(['playerId', 'season'])['game_fantasy_points']
        .transform(lambda x: x.shift(1).expanding().mean())
    )

    return df

def buildLabel(df, hot_quantile=0.75, cold_quantile=0.25):
    next_5_avg = df.groupby(['playerId', 'season'])['game_fantasy_points'].transform(lambda x: x[::-1].rolling(5, min_periods=5).mean()[::-1].shift(-1))
    # Rank against the league that season rather than each player's own baseline.
    # A relative-to-self threshold lets low-output players (e.g. shot-blocking
    # defensemen) trigger "heating up" on ordinary block/hit variance without ever
    # producing fantasy-relevant totals. Percentile vs. the field ties the label
    # to actual absolute value.
    next_5_percentile = next_5_avg.groupby(df['season']).rank(pct=True)
    df['is_heating_up'] = (next_5_percentile >= hot_quantile).astype(int)
    df['is_cooling_down'] = (next_5_percentile <= cold_quantile).astype(int)
    df = df.dropna(subset=['season_avg_so_far'])
    df = df[next_5_avg.reindex(df.index).notna()]
    return df

def buildFeatureMatrix(df, label_col='is_heating_up'):
    feature_cols = [col for col in df.columns if col.startswith('rolling_')]
    feature_cols.append('season_avg_so_far')
    feature_cols.append('position_encoded')
    X = df[feature_cols]
    y = df[label_col] if label_col in df.columns else None
    return X, y