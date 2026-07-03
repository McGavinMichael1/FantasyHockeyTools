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
from sklearn.metrics import roc_auc_score, classification_report, RocCurveDisplay
import matplotlib.pyplot as plt
from sklearn.model_selection import RandomizedSearchCV, PredefinedSplit
import numpy as np


from src.features.mlFeatures import buildFeatureMatrix
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'pickups', 'model.pkl')

def train(df: pd.DataFrame):
    """Train the pickup model on rolling window data and save it."""
    train_df = df[df['season'] <= 2022] # Use data up to 2022 for training
    val_df = df[df['season'] == 2023]
    X_train, y_train = buildFeatureMatrix(train_df, label_col='is_heating_up')
    X_val, y_val = buildFeatureMatrix(val_df, label_col='is_heating_up')
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
        xgb.XGBClassifier(eval_metric='logloss'),
        param_distributions=param_dist,
        n_iter=20,
        scoring='roc_auc',
        cv=ps,
        random_state=42,
        verbose=1,
    )
    search.fit(X_all, y_all)
    model = search.best_estimator_
    print("Best params:", search.best_params_)
    print(f"Best val AUC: {search.best_score_:.4f}")
    save(model)
    proba = model.predict_proba(X_val)[:, 1]
    preds = model.predict(X_val)

    train_proba = model.predict_proba(X_train)[:, 1]
    print(f"Train AUC: {roc_auc_score(y_train, train_proba):.4f}")
    print(f"Val AUC:   {roc_auc_score(y_val, proba):.4f}")

    print(classification_report(y_val, preds))

    RocCurveDisplay.from_predictions(y_val, proba)
    plt.title('Pickup Model - ROC Curve (Validation Set)')
    plt.savefig('reports/pickup_roc_curve.png')
    plt.close()

    xgb.plot_importance(model, max_num_features=20)
    plt.title('Pickup Model - Top 20 Feature Importances')
    plt.tight_layout()
    plt.savefig('reports/pickup_feature_importance.png')
    plt.close()



def predict(df: pd.DataFrame) -> pd.Series:
    """Load the saved model and return predicted short-term fantasy points."""
    model = load()
    X, _ = buildFeatureMatrix(df, label_col='is_heating_up')
    probas = model.predict_proba(X)[:, 1]
    return pd.Series(probas, index=df.index)


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

