import pandas as pd

import api_export


BASE_ROW = {
    'playerId': 1, 'full_name': 'Test Goalie', 'position': 'G',
    'gamesPlayed': 60, 'fpPerGame': 4.2, 'projected_fpPerGame': 4.5,
    'projected_total': 270.0, 'delta_vs_last': 0.3, 'age': 30.0,
}


def test_build_draft_list_exports_vorp_and_projected_gp(tmp_path, monkeypatch):
    df = pd.DataFrame([{**BASE_ROW, 'vorp': 42.5, 'projected_gp': 60.0}])
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    entries = api_export.build_draft_list()

    assert entries[0]['vorp'] == 42.5
    assert entries[0]['projected_gp'] == 60.0
    assert entries[0]['positionCode'] == 'G'


def test_build_draft_list_survives_csv_without_vorp_columns(tmp_path, monkeypatch):
    df = pd.DataFrame([BASE_ROW])  # pre-goalie CSV shape
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    entries = api_export.build_draft_list()

    assert entries[0]['vorp'] is None
    assert entries[0]['projected_gp'] is None
