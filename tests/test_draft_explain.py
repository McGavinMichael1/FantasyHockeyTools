import math

from src import draft_explain


def test_feature_label_known_position_and_unknown():
    assert draft_explain.feature_label('fpPerGame') == 'Last-season FP/game'
    # pos_* one-hots become a readable position line
    assert draft_explain.feature_label('pos_C') == 'Position: C'
    # an unmapped column falls back to itself, never raises
    assert draft_explain.feature_label('mystery_col') == 'mystery_col'


def test_top_factors_keeps_top_positive_then_negative():
    contribs = {
        'fpPerGame': 0.5,
        'fp_w3': 0.2,
        'PP_share': 0.05,
        'age_at_season_start': -0.3,
        'xGoalsSurplus': -0.1,
        'career_games': -0.4,
        'pos_C': 0.0,  # zero contribution is dropped entirely
    }
    # top 2 positives desc: fpPerGame 0.5, fp_w3 0.2
    # top 2 negatives asc (most negative first): career_games -0.4, age -0.3
    result = draft_explain.top_factors(contribs, top_n=2)
    assert result == [
        {'label': 'Last-season FP/game', 'value': 0.5},
        {'label': '3-season weighted FP/game', 'value': 0.2},
        {'label': 'Career games played', 'value': -0.4},
        {'label': 'Age', 'value': -0.3},
    ]


def test_compute_confidence_full_data_full_score():
    # deep history (>=4 seasons -> 1.0), full season GP (>=70 -> 1.0),
    # peak age 25 -> 1.0, projection == fp_w3 -> stability 1.0
    # 0.25*1 + 0.30*1 + 0.20*1 + 0.25*1 = 1.0 -> 100
    assert draft_explain.compute_confidence(
        seasons_of_history=5, feature_gp=82, age=25.0,
        projection=3.0, fp_w3=3.0) == 100


def test_compute_confidence_thin_data_and_deviation():
    # seasons 2 -> 2/4 = 0.5; gp 35 -> 35/70 = 0.5;
    # age 20 -> max(0.4, 1 - 0.06*3) = 0.82;
    # |2.0 - 3.5| = 1.5 -> stability = 1 - 1.5/2 = 0.25
    # 0.25*0.5 + 0.30*0.5 + 0.20*0.82 + 0.25*0.25
    # = 0.125 + 0.15 + 0.164 + 0.0625 = 0.5015 -> round -> 50
    assert draft_explain.compute_confidence(
        seasons_of_history=2, feature_gp=35, age=20.0,
        projection=2.0, fp_w3=3.5) == 50


def test_compute_confidence_missing_age_and_fp_w3_are_neutral():
    # seasons 4 -> 1.0; gp 70 -> 1.0; age NaN -> 0.5; fp_w3 NaN -> stability 0.5
    # 0.25*1 + 0.30*1 + 0.20*0.5 + 0.25*0.5 = 0.25 + 0.30 + 0.10 + 0.125 = 0.775 -> 78
    assert draft_explain.compute_confidence(
        seasons_of_history=4, feature_gp=70, age=math.nan,
        projection=3.0, fp_w3=math.nan) == 78
