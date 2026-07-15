# Draft analysis model: train, save, load, and predict next-season fantasy FP/game.
#
# All model modules expose the same interface so the UI and any calling code
# doesn't need to know which model type is underneath:
#   train(df)    -> fits and saves the model
#   predict(df)  -> loads the model and returns predictions
#   load()       -> returns the saved model object
#   save(model)  -> persists the model to disk
#
# Phase B3 protocol (PROJECT-PLAN.md): baselines first, then Ridge as a
# coefficient-sign diagnostic, then XGBoost tuned on a season-based
# PredefinedSplit. The XGBoost model ships only if it beats BOTH baselines on
# val Spearman -- otherwise Baseline B (fp_w3) is the ranker.

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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'draft', 'model.pkl')

TARGET_COL = 'target_fpPerGame'
# Numeric draft features. Position one-hots (pos_*) are discovered at train
# time and the combined list is persisted with the model, so predict() always
# sees the exact columns training saw even if a position is missing from a
# prediction batch.
BASE_FEATURE_COLS = [
    'fpPerGame', 'fp_delta', 'fp_w3', 'PP_share', 'hitblock_share',
    'xGoalsSurplus', 'avgIcetime', 'career_games', 'age_at_season_start',
    'highDangerShare', 'avgGameScore',
]

TRAIN_MAX_SEASON = 2021
VAL_SEASONS = (2022, 2023)
# Test season 2024 is deliberately absent here: it gets ONE manual look after a
# model passes the val gate, then is never touched again.

# Rows need >=20 GP in both the feature season and the target season --
# injury-shortened seasons distort FP/game on either side of the label.
# Training-time only: predict() applies no GP filter, because at draft time we
# still want a projection for a player coming off a 15-game injury season.
MIN_GP = 20


def _spearman(y_true, y_pred):
    return spearmanr(y_true, y_pred).statistic


def _feature_matrix(df: pd.DataFrame, feature_cols: list) -> pd.DataFrame:
    """Numeric matrix in a fixed column order.

    A pos_* column absent from df means no player of that position in this
    batch -> fill 0. A missing numeric column is a pipeline bug -> raise.
    """
    missing = [c for c in feature_cols
               if c not in df.columns and not c.startswith('pos_')]
    if missing:
        raise ValueError(f"feature columns missing from input df: {missing}")
    X = df.reindex(columns=feature_cols)
    pos_cols = [c for c in feature_cols if c.startswith('pos_')]
    X[pos_cols] = X[pos_cols].fillna(0)
    # bool dummies -> 0/1, pd.NA -> NaN; XGBoost handles NaN natively.
    return X.apply(lambda s: pd.to_numeric(s, errors='coerce')).astype('float64')


def train(df: pd.DataFrame):
    """Train the draft ranker on build_draft_features output and save it.

    Prints val Spearman/MAE for both baselines, Ridge, and XGBoost, plus the
    GATE B3 verdict. Record the printed numbers in PROJECT-PLAN.md's Learning
    Log -- text, not just the reports/ plots.
    """
    eligible = df[
        (df['gamesPlayed'] >= MIN_GP)
        & (df['target_gamesPlayed'] >= MIN_GP)
        & df[TARGET_COL].notna()
    ]

    # Season-based split, never random rows: random splits put the same
    # player's adjacent seasons on both sides and the model memorizes players.
    train_df = eligible[eligible['season'] <= TRAIN_MAX_SEASON]
    val_df = eligible[eligible['season'].isin(VAL_SEASONS)]
    print(f"train rows: {len(train_df)} (seasons <= {TRAIN_MAX_SEASON}), "
          f"val rows: {len(val_df)} (seasons {VAL_SEASONS})")

    feature_cols = BASE_FEATURE_COLS + sorted(
        c for c in df.columns if c.startswith('pos_'))
    X_train = _feature_matrix(train_df, feature_cols)
    y_train = train_df[TARGET_COL]
    X_val = _feature_matrix(val_df, feature_cols)
    y_val = val_df[TARGET_COL]

    # --- Baselines first: the model only ships if it beats BOTH on Spearman ---
    baseline_rhos = {}
    for name, val_pred in [('Baseline A (last-season FP/g)', val_df['fpPerGame']),
                           ('Baseline B (fp_w3 weighted)', val_df['fp_w3'])]:
        baseline_rhos[name] = _spearman(y_val, val_pred)
        print(f"{name}: val Spearman {baseline_rhos[name]:.4f}, "
              f"MAE {mean_absolute_error(y_val, val_pred):.4f}")

    # --- Ridge: a coefficient-sign diagnostic more than a candidate ---
    ridge = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge())
    ridge.fit(X_train, y_train)
    ridge_pred = ridge.predict(X_val)
    print(f"Ridge: val Spearman {_spearman(y_val, ridge_pred):.4f}, "
          f"MAE {mean_absolute_error(y_val, ridge_pred):.4f}")
    coefs = pd.Series(ridge[-1].coef_, index=feature_cols).sort_values()
    print("Ridge coefficients (standardized). Sanity-check signs -- prior FP/g "
          "strongly positive; a wrong sign is a feature bug, not a modeling choice:")
    print(coefs.to_string())

    # --- XGBoost, tuned on the season split (same pattern as models/pickups) ---
    # PredefinedSplit encodes the split made above: -1 rows always train,
    # 0 rows are the fixed validation fold. Order must match the concat below.
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
    # refit=False: RandomizedSearchCV would otherwise refit best_estimator_ on
    # train+val, and any val metric computed from it would be flattered. We
    # evaluate honestly on a train-only fit first, then refit for the final model.
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

    # --- GATE B3 verdict ---
    if all(xgb_rho > rho for rho in baseline_rhos.values()):
        print("GATE B3: PASS -- XGBoost beats both baselines on val Spearman. "
              "Confirm on test-2024 exactly once, then stop touching test.")
    else:
        print("GATE B3: FAIL -- XGBoost does not beat both baselines. "
              "Ship Baseline B (fp_w3) as the ranker; that is a legitimate "
              "outcome, not a failure state.")

    # Final model: same hyperparameters, refit on train+val so the saved model
    # has seen everything up to the test boundary.
    model = xgb.XGBRegressor(random_state=42, **search.best_params_)
    model.fit(X_all, y_all)
    save({'model': model, 'feature_cols': feature_cols})

    os.makedirs('reports', exist_ok=True)
    xgb.plot_importance(model, max_num_features=20)
    plt.title('Draft Model - Top 20 Feature Importances')
    plt.tight_layout()
    plt.savefig('reports/draft_feature_importance.png')
    plt.close()


def predict(df: pd.DataFrame) -> pd.Series:
    """Load the saved model and return projected next-season fantasy FP/game."""
    payload = load()
    X = _feature_matrix(df, payload['feature_cols'])
    preds = payload['model'].predict(X)
    return pd.Series(preds, index=df.index, name='projected_fpPerGame')


def load():
    """Load and return the saved payload: {'model', 'feature_cols'}."""
    with open(MODEL_PATH, 'rb') as f:
        return pickle.load(f)


def save(payload):
    """Persist the model payload ({'model', 'feature_cols'}) to MODEL_PATH."""
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(payload, f)
