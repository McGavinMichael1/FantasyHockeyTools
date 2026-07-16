import pandas as pd
import pytest

from src.features import goalies as goalie_features


def _seasons(rows):
    base = {'full_name': 'G', 'position': 'G', 'gamesStarted': 50,
            'icetime': 180000.0, 'gsax': 5.0, 'save_pct': 0.91,
            'xsave_delta': 0.004, 'fantasyPoints': 250.0,
            'wins': 30, 'losses': 15, 'shutouts': 3, 'goalsAgainst': 140,
            'saves': 1500, 'shotsAgainst': 1640, 'xGoals': 145.0,
            'goals': 140.0, 'ongoal': 1640.0, 'games_played': 55}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_target_is_next_consecutive_season_only():
    df = _seasons([
        {'playerId': 1, 'season': 2020, 'gamesPlayed': 50, 'fpPerGame': 4.0},
        {'playerId': 1, 'season': 2021, 'gamesPlayed': 55, 'fpPerGame': 4.5},
        {'playerId': 1, 'season': 2023, 'gamesPlayed': 60, 'fpPerGame': 5.0},  # gap
    ])
    out = goalie_features.build_goalie_features(df).set_index('season')

    assert out.loc[2020, 'target_fpPerGame'] == pytest.approx(4.5)
    assert out.loc[2020, 'target_gamesPlayed'] == 55
    # 2021 -> 2023 is a gap season: no target (GATE G2 leakage discipline)
    assert pd.isna(out.loc[2021, 'target_fpPerGame'])
    assert pd.isna(out.loc[2023, 'target_fpPerGame'])


def test_lags_do_not_bleed_across_players():
    df = _seasons([
        {'playerId': 1, 'season': 2022, 'gamesPlayed': 60, 'fpPerGame': 5.0},
        {'playerId': 2, 'season': 2023, 'gamesPlayed': 40, 'fpPerGame': 2.0},
    ])
    out = goalie_features.build_goalie_features(df)
    player2 = out[out['playerId'] == 2].iloc[0]
    assert pd.isna(player2['fp_delta'])  # not 2.0 - 5.0


def test_fp_w3_and_gp_w3_renormalize_missing_history():
    df = _seasons([
        {'playerId': 1, 'season': 2021, 'gamesPlayed': 40, 'fpPerGame': 3.0},
        {'playerId': 1, 'season': 2022, 'gamesPlayed': 60, 'fpPerGame': 5.0},
    ])
    out = goalie_features.build_goalie_features(df).set_index('season')
    # 2022 has 2 seasons of history: (0.5*5 + 0.3*3) / 0.8
    assert out.loc[2022, 'fp_w3'] == pytest.approx((0.5 * 5.0 + 0.3 * 3.0) / 0.8)
    assert out.loc[2022, 'gp_w3'] == pytest.approx((0.5 * 60 + 0.3 * 40) / 0.8)
    # single-season goalie: weight renormalizes to just the own season
    assert out.loc[2021, 'fp_w3'] == pytest.approx(3.0)


def test_workload_and_rate_features():
    df = _seasons([{'playerId': 1, 'season': 2023, 'gamesPlayed': 60,
                    'fpPerGame': 5.0, 'gamesStarted': 58,
                    'icetime': 200000.0, 'gsax': 10.0}])
    out = goalie_features.build_goalie_features(df).iloc[0]
    assert out['gs_share'] == pytest.approx(58 / 82)
    assert out['gsax_per60'] == pytest.approx(10.0 / 200000.0 * 3600)
    assert out['career_games'] == 60
