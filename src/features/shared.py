# Features shared across all prediction tasks.
# These are derived from the base player DataFrame and can be reused
# by both draft and pickup models.
#
# Examples of what belongs here:
#   - Position encoding
#   - Team encoding
#   - Career games played
#   - Fantasy points per game (season total)

import os

import pandas as pd
from src import keepers, moneypuck


def add_age_at_season_start(df: pd.DataFrame) -> pd.DataFrame:
    """Merge data/raw/player_birthdates.csv (built by scripts/build_birthdates.py,
    extended with goalie ids by scripts/build_goalie_seasons.py) and add
    age_at_season_start: fractional years at an Oct-1 season start.
    Missing cache or missing player -> NaN age, never a crash.
    """
    birthdates_path = os.path.join(
        os.path.dirname(__file__), '..', '..', 'data', 'raw', 'player_birthdates.csv')
    df = df.copy()
    if not os.path.exists(birthdates_path):
        print("player_birthdates.csv not found -- run scripts/build_birthdates.py; "
              "age_at_season_start set to NaN")
        df['age_at_season_start'] = pd.NA
        return df
    birthdates = (pd.read_csv(birthdates_path)[['playerId', 'birthDate']]
                  .drop_duplicates('playerId'))
    df = df.merge(birthdates, on='playerId', how='left')
    birth = pd.to_datetime(df['birthDate'], errors='coerce')
    # MoneyPuck season 2023 == the 2023-24 season, starting ~Oct 1, 2023.
    season_start = pd.to_datetime(df['season'].astype(str) + '-10-01')
    df['age_at_season_start'] = (season_start - birth).dt.days / 365.25
    return df


def build_shared_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the base player DataFrame and adds features common to all tasks.
    Returns a new DataFrame with the added columns.
    """
    # TODO: implement shared feature engineering
    raise NotImplementedError


def select_matrix(df, feature_cols, label_col=None):
    """Slice an engineered DataFrame into the (X, y) contract every model uses.

    Deliberately dumb: it only selects columns. Each task decides *which*
    columns are features (an allowlist -- a column nobody named is simply
    absent, never silently fed to a model), and any per-model preprocessing
    (imputation, scaling) stays in the model module. `y` is None when
    `label_col` is missing from `df`, which is the predict-time case where the
    rows have no label yet.
    """
    X = df[feature_cols]
    y = df[label_col] if label_col and label_col in df.columns else None
    return X, y
