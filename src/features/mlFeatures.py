import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(BASE_DIR, '../..', 'data', 'raw')

def loadMoneyPuckData():
    historical = pd.read_csv(os.path.join(RAW_DATA_DIR, 'moneypuck_2020_2024.csv'))
    current = pd.read_csv(os.path.join(RAW_DATA_DIR, 'moneypuck_current.csv'))
    current = current[current['situation'] == 'all']
    moneyPuckData = pd.concat([historical, current], ignore_index=True).copy()
    moneyPuckData.sort_values(by=['playerId', 'gameDate'], inplace=True)
    moneyPuckData['game_fantasy_points'] = (moneyPuckData['I_F_goals'] * 3 +
                                            moneyPuckData['I_F_primaryAssists'] * 2 +
                                            moneyPuckData['I_F_secondaryAssists'] * 2 +
                                            moneyPuckData['I_F_shotsOnGoal'] * 0.15)
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

def buildLabel(df):
    next_5_avg = df.groupby(['playerId', 'season'])['game_fantasy_points'].transform(lambda x: x[::-1].rolling(5, min_periods=5).mean()[::-1].shift(-1))
    df['is_heating_up'] = (next_5_avg > df['season_avg_so_far'] * 1.25).astype(int)
    df['is_cooling_down'] = (next_5_avg < df['season_avg_so_far'] * 0.75).astype(int)
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