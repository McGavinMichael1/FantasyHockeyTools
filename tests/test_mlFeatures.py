import pandas as pd
import pytest

from src.features import mlFeatures
from src.features.mlFeatures import buildLabel, buildRollingFeatures


def test_build_label_keeps_continuous_next_5_avg():
    # 7 games, ascending scores. next_5_avg at game i is the mean of games
    # i+1..i+5 (strictly future, 5-game window, min 5 games):
    #   game 0: (2+3+4+5+6)/5 = 4.0
    #   game 1: (3+4+5+6+7)/5 = 5.0
    #   games 2-6: fewer than 5 future games -> row dropped
    df = pd.DataFrame({
        'playerId': [1] * 7,
        'season': [2023] * 7,
        'game_fantasy_points': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        'season_avg_so_far': [1.0] * 7,
    })

    out = buildLabel(df)

    assert list(out['next_5_avg']) == [4.0, 5.0]


def test_build_label_never_includes_current_game_in_target():
    # A huge score in the current game must not leak into its own label:
    # game 0's label averages games 1-5 (all zeros), not game 0 itself.
    df = pd.DataFrame({
        'playerId': [1] * 6,
        'season': [2023] * 6,
        'game_fantasy_points': [100.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        'season_avg_so_far': [1.0] * 6,
    })

    out = buildLabel(df)

    assert list(out['next_5_avg']) == [0.0]


def _rolling_frame(pp_icetimes, total_icetime=1200, onice_gf=None,
                   onice_sf=None, onice_ga=None, onice_sa=None, onice_xgf=None):
    """One player, ascending gameDates, constant total ice time."""
    n = len(pp_icetimes)
    zeros = [0] * n
    return pd.DataFrame({
        'playerId': [1] * n,
        'season': [2023] * n,
        'gameDate': [20231001 + i for i in range(n)],
        'game_fantasy_points': [2.0] * n,
        'gameScore': [0.5] * n,
        'icetime': [total_icetime] * n,
        'powerPlayIcetime': pp_icetimes,
        'pp_toi_share': [pp / total_icetime for pp in pp_icetimes],
        'I_F_goals': zeros, 'I_F_primaryAssists': zeros,
        'I_F_secondaryAssists': zeros, 'I_F_xGoals': [0.0] * n,
        'I_F_shotsOnGoal': zeros, 'ozone_start_pct': [0.5] * n,
        'xgoals_surplus': [0.0] * n, 'high_danger_rate': [0.0] * n,
        'onIce_corsiPercentage': [50.0] * n,
        'onIce_fenwickPercentage': [50.0] * n,
        'ev_onIce_goalsFor': onice_gf if onice_gf is not None else zeros,
        'ev_onIce_shotsFor': onice_sf if onice_sf is not None else zeros,
        'ev_onIce_xGoalsFor': onice_xgf if onice_xgf is not None else [0.0] * n,
        'ev_onIce_goalsAgainst': onice_ga if onice_ga is not None else zeros,
        'ev_onIce_shotsAgainst': onice_sa if onice_sa is not None else zeros,
    })


def test_pp_toi_share_is_a_rate_not_a_level():
    # 180s of PP out of 1200s total = 0.15. A 4th-liner and a 1st-liner with
    # the same raw PP seconds are different signals; the share separates them.
    df = _rolling_frame([180] * 5)
    out = buildRollingFeatures(df)
    assert out['rolling_5_pp_toi_share'].iloc[-1] == pytest.approx(0.15)
    assert out['rolling_5_powerPlayIcetime'].iloc[-1] == pytest.approx(180)


def test_pp_toi_delta_detects_a_promotion():
    # 20 games at 60s of PP, then 5 games at 300s -- a PP1 promotion.
    # rolling_5 = 300, rolling_20 = (15*60 + 5*300)/20 = (900+1500)/20 = 120.
    # delta = +180s. A rolling LEVEL alone cannot tell this apart from a
    # player who has always had 120s; the delta is the breakout signal.
    df = _rolling_frame([60] * 20 + [300] * 5)
    out = buildRollingFeatures(df)
    last = out.iloc[-1]
    assert last['rolling_5_powerPlayIcetime'] == pytest.approx(300)
    assert last['rolling_20_powerPlayIcetime'] == pytest.approx(120)
    assert last['rolling_delta_5_20_powerPlayIcetime'] == pytest.approx(180)


def test_trend_deltas_are_zero_for_a_steady_player():
    # No role change -> no trend signal. Guards against a delta that is really
    # measuring window-length artefacts rather than change.
    df = _rolling_frame([120] * 25)
    out = buildRollingFeatures(df)
    last = out.iloc[-1]
    assert last['rolling_delta_5_20_powerPlayIcetime'] == pytest.approx(0)
    assert last['rolling_delta_5_20_pp_toi_share'] == pytest.approx(0)
    assert last['rolling_delta_5_20_game_fantasy_points'] == pytest.approx(0)


def test_icetime_is_rolled_at_20_games_so_its_delta_exists():
    # icetime was previously rolled at 5 and 10 only; the 5-vs-20 delta needs
    # the 20 window. The 5 and 10 columns must still be produced.
    out = buildRollingFeatures(_rolling_frame([120] * 25))
    for col in ['rolling_5_icetime', 'rolling_10_icetime', 'rolling_20_icetime',
                'rolling_delta_5_20_icetime']:
        assert col in out.columns


def test_onice_shooting_pct_is_a_ratio_of_sums_not_a_mean_of_ratios():
    # 10 games. Nine quiet games: 1 goal on 5 on-ice shots (20%). One busy
    # game: 1 goal on 55 on-ice shots (1.8%).
    #   ratio of sums   = (9*1 + 1) / (9*5 + 55) = 10 / 100 = 0.10   <- correct
    #   mean of ratios  = (9*0.20 + 0.018) / 10  = 0.1818            <- wrong
    # The busy game must pull the estimate down in proportion to its shots.
    df = _rolling_frame([0] * 10,
                        onice_gf=[1] * 9 + [1],
                        onice_sf=[5] * 9 + [55],
                        onice_ga=[0] * 10,
                        onice_sa=[10] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_shooting_pct'].iloc[-1] == pytest.approx(0.10)


def test_onice_save_pct_is_one_minus_goals_against_over_shots_against():
    # 10 games x (1 GA on 10 SA) = 10 GA / 100 SA -> save % = 1 - 0.10 = 0.90
    df = _rolling_frame([0] * 10,
                        onice_gf=[0] * 10, onice_sf=[10] * 10,
                        onice_ga=[1] * 10, onice_sa=[10] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_save_pct'].iloc[-1] == pytest.approx(0.90)


def test_pdo_is_display_only_and_not_enrolled_as_a_model_feature():
    # PDO is the sum of two columns already present. It ships for the eyeball
    # gate and the board, but naming it outside the rolling_ prefix keeps
    # pickupFeatureCols' allowlist from feeding a collinear column to the model.
    df = _rolling_frame([0] * 10,
                        onice_gf=[1] * 10, onice_sf=[10] * 10,
                        onice_ga=[1] * 10, onice_sa=[10] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    # SH% = 10/100 = 0.10; SV% = 1 - 10/100 = 0.90; PDO = 1.00
    assert out['pdo_10'].iloc[-1] == pytest.approx(1.00)
    assert 'pdo_10' not in mlFeatures.pickupFeatureCols(out)
    assert 'rolling_10_onice_shooting_pct' in mlFeatures.pickupFeatureCols(out)


def test_onice_percentages_are_nan_below_the_shot_floor():
    # 10 games x 4 on-ice shots = 40 shots, under the 60-shot floor. A
    # percentage off that few shots is denominator noise; NaN is the honest
    # answer and XGBoost handles it natively.
    df = _rolling_frame([0] * 10,
                        onice_gf=[1] * 10, onice_sf=[4] * 10,
                        onice_ga=[1] * 10, onice_sa=[4] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert pd.isna(out['rolling_10_onice_shooting_pct'].iloc[-1])
    assert pd.isna(out['rolling_10_onice_save_pct'].iloc[-1])


def test_onice_features_need_a_full_window():
    # Partial windows have even smaller denominators than the floor allows,
    # so min_periods is the full window: the first 9 rows of a 10-game window
    # are NaN regardless of shot volume.
    df = _rolling_frame([0] * 12,
                        onice_gf=[1] * 12, onice_sf=[20] * 12,
                        onice_ga=[1] * 12, onice_sa=[20] * 12)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_shooting_pct'].iloc[:9].isna().all()
    assert out['rolling_10_onice_shooting_pct'].iloc[9] == pytest.approx(0.05)


def test_onice_gax_is_goals_above_expected_per_game():
    # 10 games x (2 on-ice goals, 1.0 on-ice xG, 20 shots):
    # (20 goals - 10.0 xG) / 10 games = +1.0 goals above expected per game.
    df = _rolling_frame([0] * 10,
                        onice_gf=[2] * 10, onice_sf=[20] * 10,
                        onice_xgf=[1.0] * 10,
                        onice_ga=[0] * 10, onice_sa=[20] * 10)
    out = mlFeatures.buildRollingFeatures(df)
    assert out['rolling_10_onice_gax'].iloc[-1] == pytest.approx(1.0)
