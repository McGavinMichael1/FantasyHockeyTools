import pandas as pd
import pytest

from src.features.draft import build_draft_features


def _season_row(playerId, season, onice_sh=0.08, pp_share=0.10, **kwargs):
    """Minimal player_seasons row for build_draft_features."""
    row = {
        'playerId': playerId, 'season': season, 'gamesPlayed': 82,
        'full_name': f'Player {playerId}', 'position': 'C',
        'avgIcetime': 1100.0, 'avgGameScore': 0.6,
        'avgCorsiPercentage': 50.0, 'avgFenwickPercentage': 50.0,
        'totalGoals': 20, 'totalPrimaryAssists': 20, 'totalSecondaryAssists': 10,
        'totalPoints': 50, 'totalShotsOnGoal': 200, 'totalHits': 50,
        'totalShotsBlocked': 40, 'totalXGoals': 18.0,
        'totalHighDangerShots': 40, 'totalPPP': 15, 'totalPPGoals': 5,
        'totalPPAssists': 10, 'totalSHP': 1, 'totalFP': 200.0,
        'fpPerGame': 2.44, 'xGoalsSurplus': 2.0, 'highDangerShare': 0.2,
        'ppToiShare': pp_share, 'avgPPIcetime': 150.0,
        'oniceShootingPct': onice_sh, 'oniceSavePct': 0.92,
        'pdo': onice_sh + 0.92, 'oniceGaxPerGame': 0.1,
    }
    row.update(kwargs)
    return row


def test_onice_sh_luck_is_deviation_from_the_players_own_baseline():
    # Three seasons at 8% on-ice SH%, then a 12% season.
    # prior 3-season mean = 0.08 -> luck = 0.12 - 0.08 = +0.04.
    # Deviation from his OWN history, not the league: on-ice SH% has a real
    # talent component (elite linemates convert more) and only the transient
    # part regresses.
    df = pd.DataFrame([
        _season_row(1, 2020, onice_sh=0.08),
        _season_row(1, 2021, onice_sh=0.08),
        _season_row(1, 2022, onice_sh=0.08),
        _season_row(1, 2023, onice_sh=0.12),
    ])
    out = build_draft_features(df).sort_values('season')
    assert out['onice_sh_luck'].iloc[-1] == pytest.approx(0.04)


def test_onice_sh_luck_is_nan_in_a_players_first_season():
    # A rookie has no baseline to deviate from. NaN is correct and matches
    # fp_delta's treatment; XGBoost handles it natively.
    df = pd.DataFrame([_season_row(1, 2023, onice_sh=0.14)])
    out = build_draft_features(df)
    assert pd.isna(out['onice_sh_luck'].iloc[0])


def test_pp_toi_share_delta_tracks_a_role_change():
    # 6% of ice time on the PP, then 18% -- a PP2-to-PP1 promotion.
    df = pd.DataFrame([
        _season_row(1, 2022, pp_share=0.06),
        _season_row(1, 2023, pp_share=0.18),
    ])
    out = build_draft_features(df).sort_values('season')
    assert out['pp_toi_share_delta'].iloc[-1] == pytest.approx(0.12)
    assert pd.isna(out['pp_toi_share_delta'].iloc[0])


def test_luck_residual_keeps_players_separate():
    # Player 2's history must not bleed into player 1's baseline.
    df = pd.DataFrame([
        _season_row(1, 2022, onice_sh=0.08),
        _season_row(2, 2022, onice_sh=0.20),
        _season_row(1, 2023, onice_sh=0.10),
    ])
    out = build_draft_features(df)
    row = out[(out['playerId'] == 1) & (out['season'] == 2023)].iloc[0]
    assert row['onice_sh_luck'] == pytest.approx(0.02)


def test_deployment_and_luck_are_computed_but_not_model_features():
    # Both families were tested at the 2026-08-24 gate and neither earned a
    # place: all five moved val Spearman 0.8259 -> 0.8256, deployment alone
    # 0.8259 -> 0.8244, and onice_sh_luck's Ridge coefficient came out POSITIVE
    # when a luck residual must be negative. They stay COMPUTED so the board
    # and future experiments can read them; this test is the tripwire against
    # wiring them back into the model by reflex.
    from src.models.draft import BASE_FEATURE_COLS
    for col in ['ppToiShare', 'avgPPIcetime', 'pp_toi_share_delta',
                'onice_sh_luck', 'oniceGaxPerGame']:
        assert col not in BASE_FEATURE_COLS
