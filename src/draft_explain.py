"""Deterministic draft-ranking explanation: human-readable SHAP factor names
and a transparent data-driven confidence score.

Both public functions are pure (no model, no IO) so they carry pytest coverage
per the repo testing doctrine (fht-quality-gates). The XGBoost booster wrapper
that produces raw SHAP contributions lives in src/models/draft.py; this module
only names and ranks them and computes confidence.

Confidence (0-100) is a documented weighted average of four sub-scores, each in
[0, 1]:
  - history   (0.25): seasons of prior history (saturates at 4 seasons)
  - games     (0.30): games played in the feature season (saturates at 70)
  - age       (0.20): peak-age band 23-28 is most reliable; decays outside
  - stability (0.25): small |projection - fp_w3| = model in line with history
Missing age or fp_w3 contribute a neutral 0.5 rather than penalizing.
"""

import math
from collections.abc import Mapping

# Raw draft-feature column -> human-readable label. Keys mirror
# src/models/draft.BASE_FEATURE_COLS. pos_* one-hots are handled by feature_label.
FEATURE_LABELS = {
    'fpPerGame': 'Last-season FP/game',
    'fp_delta': 'FP/game trend (season-over-season)',
    'fp_w3': '3-season weighted FP/game',
    'PP_share': 'Power-play share of value',
    'hitblock_share': 'Hits + blocks share of value',
    'xGoalsSurplus': 'Shooting luck (goals vs expected)',
    'avgIcetime': 'Average ice time',
    'career_games': 'Career games played',
    'age_at_season_start': 'Age',
    'highDangerShare': 'High-danger shot share',
    'avgGameScore': 'Average game score',
}

# Confidence sub-score weights (documented; sum to 1.0).
_W_HISTORY = 0.25
_W_GAMES = 0.30
_W_AGE = 0.20
_W_STABILITY = 0.25

_HISTORY_FULL_SEASONS = 4.0   # >= 4 prior seasons -> full history score
_GAMES_FULL = 70.0            # >= 70 GP -> full games score
_AGE_PEAK_LO, _AGE_PEAK_HI = 23.0, 28.0
_AGE_DECAY_PER_YEAR = 0.06    # confidence lost per year outside the peak band
_AGE_FLOOR = 0.4
_STABILITY_SCALE = 2.0        # FP/game deviation that drives stability to 0


def feature_label(col: str) -> str:
    """Human-readable name for a draft feature column."""
    if col in FEATURE_LABELS:
        return FEATURE_LABELS[col]
    if col.startswith('pos_'):
        return f"Position: {col[len('pos_'):]}"
    return col


def top_factors(contribs: Mapping[str, float], top_n: int = 3) -> list[dict]:
    """Top `top_n` positive then top `top_n` negative SHAP contributions.

    Positives sorted descending (biggest push up first); negatives sorted
    ascending (biggest push down first). Zero contributions are dropped.
    Returns a flat list of {"label", "value"}; the sign of value encodes
    direction, so consumers colour by sign.
    """
    items = [(feature_label(k), float(v)) for k, v in contribs.items()]
    positives = sorted((it for it in items if it[1] > 0),
                       key=lambda it: it[1], reverse=True)[:top_n]
    negatives = sorted((it for it in items if it[1] < 0),
                       key=lambda it: it[1])[:top_n]
    return [{'label': label, 'value': value} for label, value in positives + negatives]


def _is_missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _age_score(age) -> float:
    if _is_missing(age):
        return 0.5
    if _AGE_PEAK_LO <= age <= _AGE_PEAK_HI:
        return 1.0
    gap = (_AGE_PEAK_LO - age) if age < _AGE_PEAK_LO else (age - _AGE_PEAK_HI)
    return max(_AGE_FLOOR, 1.0 - _AGE_DECAY_PER_YEAR * gap)


def _stability_score(projection, fp_w3) -> float:
    if _is_missing(fp_w3):
        return 0.5
    deviation = abs(float(projection) - float(fp_w3))
    return max(0.0, 1.0 - deviation / _STABILITY_SCALE)


def compute_confidence(seasons_of_history: int, feature_gp: int, age,
                       projection: float, fp_w3) -> int:
    """Transparent 0-100 confidence from data depth + projection stability."""
    history_score = min(max(seasons_of_history, 0) / _HISTORY_FULL_SEASONS, 1.0)
    games_score = min(max(feature_gp, 0) / _GAMES_FULL, 1.0)
    age_score = _age_score(age)
    stability_score = _stability_score(projection, fp_w3)
    score = (_W_HISTORY * history_score
             + _W_GAMES * games_score
             + _W_AGE * age_score
             + _W_STABILITY * stability_score)
    return int(round(100 * score))
