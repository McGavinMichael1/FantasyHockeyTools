# Goalie draft ranker: train, save, load, and predict next-season FP/game.
#
# Same interface as every model module (train/predict/load/save) and the same
# Phase B3 protocol as src/models/draft.py: baselines first, Ridge as a
# coefficient-sign diagnostic, XGBoost on a season-based PredefinedSplit.
# GATE G3: XGBoost ships only if it beats BOTH baselines on val Spearman --
# otherwise the saved payload IS Baseline B (fp_w3) and predict() returns it.
# With only ~600-900 eligible goalie rows a baseline win is the expected
# outcome, not a failure state.

import os
import pickle

import matplotlib.pyplot as plt
import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import make_scorer, mean_absolute_error
from sklearn.model_selection import PredefinedSplit, RandomizedSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src import season

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'goalieDraft', 'model.pkl')

TARGET_COL = 'target_fpPerGame'
FEATURE_COLS = [
    'fpPerGame', 'fp_delta', 'fp_w3', 'gsax_per60', 'save_pct', 'xsave_delta',
    'gs_share', 'career_games', 'age_at_season_start',
]

TRAIN_MAX_SEASON = season.DRAFT_TRAIN_MAX_SEASON
VAL_SEASONS = season.DRAFT_VAL_SEASONS
# season.DRAFT_TEST_SEASON gets ONE manual look after the gate, then is never
# touched.

# Goalie seasons max ~65 games; 20 (the skater floor) would discard legitimate
# backup seasons. 15 keeps backups while excluding cameos.
MIN_GP = 15


def _spearman(y_true, y_pred):
    return spearmanr(y_true, y_pred).statistic


def _feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"feature columns missing from input df: {missing}")
    X = df.reindex(columns=FEATURE_COLS)
    return X.apply(lambda s: pd.to_numeric(s, errors='coerce')).astype('float64')


def train(df: pd.DataFrame):
    """Run the GATE G3 protocol and save whichever ranker ships.

    Record the printed numbers in PROJECT-PLAN.md's Learning Log -- text,
    not just the reports/ plot.
    """
    eligible = df[
        (df['gamesPlayed'] >= MIN_GP)
        & (df['target_gamesPlayed'] >= MIN_GP)
        & df[TARGET_COL].notna()
    ]
    train_df = eligible[eligible['season'] <= TRAIN_MAX_SEASON]
    val_df = eligible[eligible['season'].isin(VAL_SEASONS)]
    print(f"train rows: {len(train_df)} (seasons <= {TRAIN_MAX_SEASON}), "
          f"val rows: {len(val_df)} (seasons {VAL_SEASONS})")

    X_train = _feature_matrix(train_df)
    y_train = train_df[TARGET_COL]
    X_val = _feature_matrix(val_df)
    y_val = val_df[TARGET_COL]

    baseline_rhos = {}
    for name, val_pred in [('Baseline A (last-season FP/g)', val_df['fpPerGame']),
                           ('Baseline B (fp_w3 weighted)', val_df['fp_w3'])]:
        baseline_rhos[name] = _spearman(y_val, val_pred)
        print(f"{name}: val Spearman {baseline_rhos[name]:.4f}, "
              f"MAE {mean_absolute_error(y_val, val_pred):.4f}")

    ridge = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge())
    ridge.fit(X_train, y_train)
    ridge_pred = ridge.predict(X_val)
    print(f"Ridge: val Spearman {_spearman(y_val, ridge_pred):.4f}, "
          f"MAE {mean_absolute_error(y_val, ridge_pred):.4f}")
    coefs = pd.Series(ridge[-1].coef_, index=FEATURE_COLS).sort_values()
    print("Ridge coefficients (standardized). Sanity-check signs -- fp_w3 and "
          "gs_share should be strongly positive; a wrong sign is a feature bug:")
    print(coefs.to_string())

    split_indicator = [-1] * len(X_train) + [0] * len(X_val)
    ps = PredefinedSplit(split_indicator)
    X_all = pd.concat([X_train, X_val])
    y_all = pd.concat([y_train, y_val])
    param_dist = {
        'n_estimators': [100, 200, 300],
        'max_depth': [3, 4, 5],
        'learning_rate': [0.01, 0.05, 0.1],
        'subsample': [0.7, 0.8, 0.9],
        'colsample_bytree': [0.7, 0.8, 1.0],
    }
    # refit=False: evaluate honestly on a train-only fit first (see models/draft.py)
    search = RandomizedSearchCV(
        xgb.XGBRegressor(random_state=42),
        param_distributions=param_dist,
        n_iter=20,
        scoring=make_scorer(_spearman),
        cv=ps,
        random_state=42,
        refit=False,
        verbose=1,
    )
    search.fit(X_all, y_all)
    print("Best params:", search.best_params_)

    eval_model = xgb.XGBRegressor(random_state=42, **search.best_params_)
    eval_model.fit(X_train, y_train)
    xgb_pred = eval_model.predict(X_val)
    xgb_rho = _spearman(y_val, xgb_pred)
    print(f"XGBoost: val Spearman {xgb_rho:.4f}, "
          f"MAE {mean_absolute_error(y_val, xgb_pred):.4f}")

    if all(xgb_rho > rho for rho in baseline_rhos.values()):
        print("GATE G3: PASS -- XGBoost beats both baselines on val Spearman. "
              f"Confirm on test-{season.DRAFT_TEST_SEASON} exactly once, "
              "then stop touching test.")
        model = xgb.XGBRegressor(random_state=42, **search.best_params_)
        model.fit(X_all, y_all)
        save({'kind': 'xgb', 'model': model, 'feature_cols': FEATURE_COLS})
        os.makedirs('reports', exist_ok=True)
        xgb.plot_importance(model, max_num_features=len(FEATURE_COLS))
        plt.title('Goalie Draft Model - Feature Importances')
        plt.tight_layout()
        plt.savefig('reports/goalie_feature_importance.png')
        plt.close()
    else:
        print("GATE G3: FAIL -- XGBoost does not beat both baselines. Shipping "
              "Baseline B (fp_w3) as the goalie ranker; predict() will return "
              "fp_w3. A legitimate outcome at this sample size, not a failure.")
        save({'kind': 'baseline_b', 'model': None, 'feature_cols': FEATURE_COLS})


def predict(df: pd.DataFrame) -> pd.Series:
    """Projected next-season goalie FP/game from whichever ranker shipped."""
    payload = load()
    if payload['kind'] == 'baseline_b':
        return pd.Series(pd.to_numeric(df['fp_w3'], errors='coerce').to_numpy(),
                         index=df.index, name='projected_fpPerGame')
    X = _feature_matrix(df)
    preds = payload['model'].predict(X)
    return pd.Series(preds, index=df.index, name='projected_fpPerGame')


def load():
    """Load the saved payload: {'kind', 'model', 'feature_cols'}."""
    with open(MODEL_PATH, 'rb') as f:
        return pickle.load(f)


def save(payload):
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(payload, f)
