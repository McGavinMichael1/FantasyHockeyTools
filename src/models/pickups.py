# Mid-season pickup model: train, save, load, and predict short-term fantasy value.
#
# All model modules expose the same interface so the UI and any calling code
# doesn't need to know which model type is underneath:
#   train(df)    -> fits and saves the model
#   predict(df)  -> loads the model and returns predictions
#   load()       -> returns the saved model object
#   save(model)  -> persists the model to disk

import pickle

import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.metrics import make_scorer, roc_auc_score, RocCurveDisplay
import matplotlib.pyplot as plt
from sklearn.model_selection import RandomizedSearchCV, PredefinedSplit
import numpy as np


from src import season
from src.features.mlFeatures import buildFeatureMatrix
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'pickups', 'model.pkl')


def _spearman(y_true, y_pred):
    return spearmanr(y_true, y_pred).statistic


def train(df: pd.DataFrame):
    """Train the pickup regressor (predicted next-5-game FP/g) and save it."""
    train_df = df[df['season'] <= season.PICKUP_TRAIN_MAX_SEASON]
    val_df = df[df['season'] == season.PICKUP_VAL_SEASON]
    X_train, y_train = buildFeatureMatrix(train_df, label_col='next_5_avg')
    X_val, y_val = buildFeatureMatrix(val_df, label_col='next_5_avg')
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

    search = RandomizedSearchCV(
        xgb.XGBRegressor(),
        param_distributions=param_dist,
        n_iter=20,
        scoring=make_scorer(_spearman),
        cv=ps,
        random_state=42,
        verbose=1,
    )
    search.fit(X_all, y_all)
    model = search.best_estimator_
    print("Best params:", search.best_params_)
    print(f"Best val Spearman: {search.best_score_:.4f}")
    save(model)
    val_pred = model.predict(X_val)

    train_pred = model.predict(X_train)
    print(f"Train Spearman: {_spearman(y_train, train_pred):.4f}")
    print(f"Val Spearman:   {_spearman(y_val, val_pred):.4f}")
    # Ranking quality against the old binary label, comparable to the
    # classifier's recorded val AUC.
    print(f"Val AUC vs is_heating_up: {roc_auc_score(val_df['is_heating_up'], val_pred):.4f}")

    RocCurveDisplay.from_predictions(val_df['is_heating_up'], val_pred)
    plt.title('Pickup Model - ROC vs heating-up label (Validation Set)')
    plt.savefig('reports/pickup_roc_curve.png')
    plt.close()

    xgb.plot_importance(model, max_num_features=20)
    plt.title('Pickup Model - Top 20 Feature Importances')
    plt.tight_layout()
    plt.savefig('reports/pickup_feature_importance.png')
    plt.close()



def predict(df: pd.DataFrame) -> pd.Series:
    """Load the saved model and return predicted next-5-game fantasy FP/g."""
    model = load()
    X, _ = buildFeatureMatrix(df, label_col='next_5_avg')
    preds = model.predict(X)
    return pd.Series(preds, index=df.index)


def load():
    """Load and return the saved model object."""
    with open(MODEL_PATH, 'rb') as f:
        model = pickle.load(f)
    return model


def save(model):
    """Persist the model object to MODEL_PATH."""
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(model, f)

