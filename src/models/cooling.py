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
from sklearn.metrics import roc_auc_score, RocCurveDisplay
import matplotlib.pyplot as plt


from src.features.mlFeatures import buildFeatureMatrix
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, '..', '..', 'models', 'cooling', 'model.pkl')

def train(df: pd.DataFrame):
    """Train the cooling regressor (predicted next-5-game FP/g) and save it.

    Same continuous target as the pickup model; callers treat a LOW predicted
    next-5 FP/g as a cooling-down / drop candidate.
    """
    train_df = df[df['season'] <= 2022] # Use data up to 2022 for training
    val_df = df[df['season'] == 2023]
    X_train, y_train = buildFeatureMatrix(train_df, label_col='next_5_avg')
    X_val, y_val = buildFeatureMatrix(val_df, label_col='next_5_avg')
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        eval_metric='rmse',
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=True)
    save(model)
    val_pred = model.predict(X_val)

    print(f"Val Spearman: {spearmanr(y_val, val_pred).statistic:.4f}")
    # Low predicted FP = cooling down; negate so the AUC is comparable to the
    # old classifier's recorded val AUC.
    print(f"Val AUC vs is_cooling_down: {roc_auc_score(val_df['is_cooling_down'], -val_pred):.4f}")

    RocCurveDisplay.from_predictions(val_df['is_cooling_down'], -val_pred)
    plt.title('Cooling Model - ROC vs cooling-down label (Validation Set)')
    plt.savefig('reports/cooling_roc_curve.png')
    plt.close()

    xgb.plot_importance(model, max_num_features=20)
    plt.title('Cooling Model - Top 20 Feature Importances')
    plt.tight_layout()
    plt.savefig('reports/cooling_feature_importance.png')
    plt.close()



def predict(df: pd.DataFrame) -> pd.Series:
    """Load the saved model and return predicted next-5-game fantasy FP/g.

    LOW values mean cooling down — callers invert when building a drop-candidate
    ranking.
    """
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

