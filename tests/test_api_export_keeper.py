import json

import pandas as pd

import api_export


def test_build_keeper_section_uses_the_cached_summary(tmp_path, monkeypatch):
    rankings_path = tmp_path / 'keeper_rankings.csv'
    summary_path = tmp_path / 'keeper_summary.json'
    pd.DataFrame([{
        'playerId': 8471,
        'full_name': 'Example Skater',
        'position': 'C',
        'keeper_rank': 1,
        'assigned_round': 18,
        'pick_cost': 150.4,
        'raw_keeper_value': 52.2,
        'net_keeper_value': 91.4,
        'projected_fpPerGame': 3.1,
        'projected_total': 241.8,
        'fpPerGame': 2.5,
        'gamesPlayed': 70,
        'confidence': 88,
        'target_season': '2026-27',
        'is_recommended': True,
    }]).to_csv(rankings_path, index=False)
    summary_path.write_text(json.dumps({
        'season': '2026-27',
        'summary': 'A cached keeper explanation.',
        'generated_at': '2026-07-15T12:00:00+00:00',
    }), encoding='utf-8')
    monkeypatch.setattr(api_export, 'KEEPER_RANKINGS_PATH', str(rankings_path))
    monkeypatch.setattr(api_export, 'KEEPER_SUMMARY_PATH', str(summary_path))

    section = api_export.build_keeper_section()

    assert section['summary'] == 'A cached keeper explanation.'
    assert section['recommendations'][0]['assigned_round'] == 18
    assert section['recommendations'][0]['full_name'] == 'Example Skater'
