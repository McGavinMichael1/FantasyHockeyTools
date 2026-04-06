import numpy as np
import pandas as pd
import torch
import os
from torch.utils.data import Dataset

SEQUENCE_LENGTH = 10

SEQUENCE_FEATURES = [
    'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
    'I_F_shotsOnGoal', 'I_F_xGoals', 'gameScore', 'icetime',
    'onIce_corsiPercentage', 'onIce_fenwickPercentage',
    'ozone_start_pct', 'high_danger_rate', 'position_encoded'
]
COLS_NEEDED = [
    'playerId', 'name', 'season', 'gameDate', 'situation', 'position',
    'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
    'I_F_shotsOnGoal', 'I_F_xGoals', 'gameScore', 'icetime',
    'onIce_corsiPercentage', 'onIce_fenwickPercentage',
    'I_F_oZoneShiftStarts', 'I_F_dZoneShiftStarts',
    'I_F_highDangerShots'
]

def loadLSTMData():
    RAW_DATA_DIR_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..', 'data', 'raw')
    historical = pd.read_csv(os.path.join(RAW_DATA_DIR_LOCAL, '2008_to_2024.csv'), usecols=COLS_NEEDED)
    historical = historical[historical['situation'] == 'all']
    historical = historical[historical['season'] >= 2016]
    current = pd.read_csv(os.path.join(RAW_DATA_DIR_LOCAL, 'moneypuck_current.csv'), usecols=COLS_NEEDED)
    current = current[current['situation'] == 'all']
    df = pd.concat([historical, current], ignore_index=True).copy()
    df.sort_values(by=['playerId', 'gameDate'], inplace=True)
    df['ozone_start_pct'] = df['I_F_oZoneShiftStarts'] / (df['I_F_oZoneShiftStarts'] + df['I_F_dZoneShiftStarts']).replace(0, 1)
    df['high_danger_rate'] = df['I_F_highDangerShots'] / df['I_F_shotsOnGoal'].replace(0, 1)
    position_mapping = {'C': 0, 'L': 1, 'R': 2, 'D': 3}
    df['position_encoded'] = df['position'].map(position_mapping)
    df['game_fantasy_points'] = (df['I_F_goals'] * 3 +
                              df['I_F_primaryAssists'] * 2 +
                              df['I_F_secondaryAssists'] * 2 +
                              df['I_F_shotsOnGoal'] * 0.15)

    df['season_avg_so_far'] = (df.groupby(['playerId', 'season'])['game_fantasy_points']
                                .transform(lambda x: x.shift(1).expanding().mean()))
    return df

def buildSequences(df, sequence_length=SEQUENCE_LENGTH, has_label=True):
    X, y, player_ids = [], [], []
    for player_id, player_df in df.groupby('playerId'):
        player_df = player_df.sort_values('gameDate').reset_index(drop=True)
        for i in range(len(player_df) - sequence_length):
            seq = player_df.iloc[i:i + sequence_length][SEQUENCE_FEATURES].values
            X.append(seq)
            player_ids.append(player_id)
            if has_label:
                label = player_df.iloc[i + sequence_length]['is_heating_up']
                y.append(label)

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32) if has_label else None, player_ids

    
class HockeySequenceDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X)
        self.y = torch.tensor(y)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]