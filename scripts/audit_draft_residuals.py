"""Residual audit for the draft ranker -- precursor to the keeper-horizon work.

Purpose (spec: docs/superpowers/specs/2026-08-24-keeper-horizon-design.md):
the horizon design multiplies the ranker's year-1 VORP by an age curve out to
five years. If the ranker systematically under-predicts 22-year-olds at year 1,
that design compounds the bias five years deep instead of exposing it. This
script measures the bias before we build on top of it.

Why it refits instead of just calling draftModel.predict(): the shipped
models/draft/model.pkl is refit on train+val (src/models/draft.py, "Final
model: ... refit on train+val"), so residuals on DRAFT_VAL_SEASONS scored from
the pickle are IN-SAMPLE and would understate exactly the bias we are hunting.
We read the searched hyperparameters off the fitted estimator, refit on the
train seasons only, and score val out-of-sample -- reproducing the honest
`eval_model` that train() computes but never persists.

Read-only: never calls draftModel.save(), never touches DRAFT_TEST_SEASON.
"""

import os
import sys

import pandas as pd
import xgboost as xgb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import main  # noqa: E402  (import-safe: argparse only runs under __main__)
from src import season  # noqa: E402
from src.models import draft as draftModel  # noqa: E402

# Bands are wide enough that every cell holds a usable n; the young bands are
# split finely because they are the ones the horizon multiplier amplifies most.
AGE_BANDS = [(0, 22), (22, 24), (24, 27), (27, 30), (30, 33), (33, 99)]
CAREER_GAMES_BANDS = [(0, 100), (100, 300), (300, 600), (600, 10_000)]


def _band_label(bands, value):
    for low, high in bands:
        if low <= value < high:
            return f"{low}-{high}" if high < 99 or bands is CAREER_GAMES_BANDS else f"{low}+"
    return "n/a"


def _honest_val_predictions(df):
    """Refit train-only with the shipped model's hyperparameters, score val."""
    payload = draftModel.load()
    feature_cols = payload['feature_cols']
    # get_params() on the fitted estimator returns the RandomizedSearchCV
    # winners that train() applied -- they are not persisted separately.
    params = payload['model'].get_params()

    eligible = df[
        (df['gamesPlayed'] >= draftModel.MIN_GP)
        & (df['target_gamesPlayed'] >= draftModel.MIN_GP)
        & df[draftModel.TARGET_COL].notna()
    ]
    train_df = eligible[eligible['season'] <= draftModel.TRAIN_MAX_SEASON]
    val_df = eligible[eligible['season'].isin(draftModel.VAL_SEASONS)]
    print(f"train rows: {len(train_df)} (seasons <= {draftModel.TRAIN_MAX_SEASON}), "
          f"val rows: {len(val_df)} (seasons {draftModel.VAL_SEASONS})")
    print(f"test season {season.DRAFT_TEST_SEASON} deliberately untouched\n")

    X_train = draftModel._feature_matrix(train_df, feature_cols)
    X_val = draftModel._feature_matrix(val_df, feature_cols)

    model = xgb.XGBRegressor(**params)
    model.fit(X_train, train_df[draftModel.TARGET_COL])
    return val_df, pd.Series(model.predict(X_val), index=val_df.index)


def main_():
    df = main.loadPlayerSeasonFeatures()
    val_df, pred = _honest_val_predictions(df)

    audit = pd.DataFrame({
        'age': val_df['age_at_season_start'],
        'career_games': val_df['career_games'],
        'actual': val_df[draftModel.TARGET_COL],
        'pred': pred,
    })
    # Signed residual: positive = the model UNDER-predicted this player.
    audit['residual'] = audit['actual'] - audit['pred']
    audit['age_band'] = [_band_label(AGE_BANDS, a) for a in audit['age']]
    audit['cg_band'] = [_band_label(CAREER_GAMES_BANDS, c) for c in audit['career_games']]

    print("=== Mean signed residual (actual - predicted FP/g) by age band ===")
    print("positive = model UNDER-predicts this group\n")
    by_age = audit.groupby('age_band')['residual'].agg(['count', 'mean', 'median', 'std'])
    print(by_age.to_string(float_format=lambda v: f"{v:+.4f}"))

    print("\n=== Mean signed residual by age band x career_games band ===")
    pivot = audit.pivot_table(index='age_band', columns='cg_band',
                              values='residual', aggfunc='mean')
    counts = audit.pivot_table(index='age_band', columns='cg_band',
                               values='residual', aggfunc='count')
    print("\nmean residual:")
    print(pivot.to_string(float_format=lambda v: f"{v:+.4f}"))
    print("\nn:")
    print(counts.fillna(0).astype(int).to_string())

    print("\n=== Decision rule (spec precursor) ===")
    young = audit[audit['age_band'].isin(['22-24', '0-22'])]['residual']
    print(f"under-24 mean residual: {young.mean():+.4f} FP/g over n={len(young)}")
    print(f"overall mean residual:  {audit['residual'].mean():+.4f} FP/g "
          f"over n={len(audit)}")
    print(f"overall residual std:   {audit['residual'].std():.4f} FP/g")
    print("\nIf the under-24 skew is materially positive, the age curve must be")
    print("applied to a bias-corrected year-1 value, not the raw one.")


if __name__ == '__main__':
    main_()
