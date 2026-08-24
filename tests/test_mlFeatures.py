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


def _rolling_frame(pp_icetimes, total_icetime=1200):
    """One player, ascending gameDates, constant total ice time."""
    n = len(pp_icetimes)
    return pd.DataFrame({
        'playerId': [1] * n,
        'season': [2023] * n,
        'gameDate': [20231001 + i for i in range(n)],
        'game_fantasy_points': [2.0] * n,
        'gameScore': [0.5] * n,
        'icetime': [total_icetime] * n,
        'powerPlayIcetime': pp_icetimes,
        'pp_toi_share': [pp / total_icetime for pp in pp_icetimes],
        'I_F_goals': [0] * n, 'I_F_primaryAssists': [0] * n,
        'I_F_secondaryAssists': [0] * n, 'I_F_xGoals': [0.0] * n,
        'I_F_shotsOnGoal': [0] * n, 'ozone_start_pct': [0.5] * n,
        'xgoals_surplus': [0.0] * n, 'high_danger_rate': [0.0] * n,
        'onIce_corsiPercentage': [50.0] * n,
        'onIce_fenwickPercentage': [50.0] * n,
        'ev_onIce_goalsFor': [0] * n, 'ev_onIce_shotsFor': [0] * n,
        'ev_onIce_xGoalsFor': [0.0] * n, 'ev_onIce_goalsAgainst': [0] * n,
        'ev_onIce_shotsAgainst': [0] * n,
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
