from scripts import build_keeper_summary as summary


def test_cache_is_current_only_for_a_nonempty_same_season_summary():
    assert summary.cache_is_current({'season': '2026-27', 'summary': 'Keep them.'}, '2026-27')
    assert not summary.cache_is_current({'season': '2025-26', 'summary': 'Keep them.'}, '2026-27')
    assert not summary.cache_is_current({'season': '2026-27', 'summary': ''}, '2026-27')


def test_build_prompt_includes_model_and_keeper_context():
    prompt = summary.build_prompt(
        '2026-27',
        [{
            'keeper_rank': 1,
            'full_name': 'Example Skater',
            'position': 'C',
            'fpPerGame': 2.5,
            'gamesPlayed': 70,
            'projected_fpPerGame': 3.1,
            'projected_total': 241.8,
            'raw_keeper_value': 52.2,
            'assigned_round': 18,
            'pick_cost': 150.4,
            'net_keeper_value': 91.4,
            'confidence': 88,
        }],
    )

    assert 'Example Skater' in prompt
    assert '3.10 FP/game' in prompt
    assert 'round 18' in prompt
    assert 'net keeper value' in prompt
