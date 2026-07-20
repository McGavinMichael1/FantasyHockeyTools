"""End-to-end smoke tests for the export path that feeds the frontend.

The unit tests next door exercise build_draft_list and build_keeper_section in
isolation. Nothing exercised the orchestration that actually writes
frontend_data.json -- and that file is the only thing the Next.js app reads, so
a break there takes the whole UI down while every test stays green.

The Learning Log records exactly this failure mode: a function signature changed
without its caller being updated, and no test noticed because the calling path
had none. These are the cheap tests that would have caught it.

export_data() is deliberately not covered: it needs MoneyPuck game logs, trained
models and the NHL API. export_keeper_only() is the same write path minus those
prerequisites, so it is what the contract is pinned against.
"""

import json

import pandas as pd
import pytest

import api_export


DRAFT_ROW = {
    'playerId': 8471214, 'full_name': 'Test Skater', 'position': 'C',
    'gamesPlayed': 78, 'fpPerGame': 3.1, 'projected_fpPerGame': 3.4,
    'projected_total': 265.2, 'delta_vs_last': 0.3, 'age': 27.0,
    'vorp': 51.7, 'projected_gp': 78.0, 'confidence': 82,
}

KEEPER_ROW = {
    'playerId': 8471214, 'full_name': 'Test Skater', 'position': 'C',
    'keeper_rank': 1, 'assigned_round': 18, 'pick_cost': 150.4,
    'raw_keeper_value': 52.2, 'net_keeper_value': 91.4,
    'projected_fpPerGame': 3.4, 'projected_total': 265.2,
    'fpPerGame': 3.1, 'gamesPlayed': 78, 'confidence': 82,
    'target_season': '2026-27', 'is_recommended': True,
}

# Every key frontend/src/types/player.ts::DraftPlayer requires. The board reads
# these directly; a rename on the Python side is a blank column in the UI.
DRAFT_PLAYER_KEYS = {
    'id', 'full_name', 'positionCode', 'headshot', 'age', 'gamesPlayed',
    'last_fpPerGame', 'projected_fpPerGame', 'projected_total',
    'delta_vs_last', 'vorp', 'projected_gp', 'confidence', 'factors', 'summary',
}


@pytest.fixture
def export_paths(tmp_path, monkeypatch):
    """Point every api_export path at a temp dir so nothing real is touched."""
    output = tmp_path / 'frontend_data.json'
    draft = tmp_path / 'draft_rankings.csv'
    keeper = tmp_path / 'keeper_rankings.csv'
    monkeypatch.setattr(api_export, 'OUTPUT_PATH', str(output))
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(draft))
    monkeypatch.setattr(api_export, 'KEEPER_RANKINGS_PATH', str(keeper))
    monkeypatch.setattr(api_export, 'DRAFT_SUMMARIES_PATH', str(tmp_path / 'summaries.json'))
    monkeypatch.setattr(
        api_export, 'KEEPER_ADVISOR_CONTEXT_PATH', str(tmp_path / 'advisor.json'))
    pd.DataFrame([DRAFT_ROW]).to_csv(draft, index=False)
    pd.DataFrame([KEEPER_ROW]).to_csv(keeper, index=False)
    return {'output': output, 'draft': draft, 'keeper': keeper}


def test_keeper_export_writes_every_key_the_frontend_reads(export_paths):
    api_export.export_keeper_only()

    payload = json.loads(export_paths['output'].read_text(encoding='utf-8'))

    # The API route hands these straight to the UI; a missing key is a crash or
    # a blank panel, not a degraded one.
    for key in ('pickups', 'cooling', 'draft', 'keeper'):
        assert key in payload, f"frontend_data.json is missing '{key}'"


def test_keeper_export_preserves_the_blocks_it_does_not_own(export_paths):
    # --keeper-only exists precisely so a keeper refresh does not require
    # retraining; silently blanking the pickup board would defeat that.
    existing = {
        'pickups': [{'id': 1}],
        'cooling': [{'id': 2}],
        'draft': [{'id': 3}],
        'keeper': None,
        'generated_at': 'earlier',
    }
    export_paths['output'].write_text(json.dumps(existing), encoding='utf-8')

    api_export.export_keeper_only()

    payload = json.loads(export_paths['output'].read_text(encoding='utf-8'))
    assert payload['pickups'] == [{'id': 1}]
    assert payload['cooling'] == [{'id': 2}]
    assert payload['draft'] == [{'id': 3}]
    assert payload['keeper'] is not None


def test_keeper_export_recovers_from_a_corrupt_existing_file(export_paths):
    # A half-written file from an interrupted run must not wedge every later
    # export -- the fix would be manual and non-obvious mid-draft-season.
    export_paths['output'].write_text('{ not json', encoding='utf-8')

    api_export.export_keeper_only()

    payload = json.loads(export_paths['output'].read_text(encoding='utf-8'))
    assert payload['keeper'] is not None
    assert payload['pickups'] == []


def test_keeper_export_writes_utf8_readable_json(export_paths):
    # Names carry accents (Stutzle, Forsberg). Writing them in the wrong codec
    # is the mojibake class of bug that has bitten the summaries before.
    row = {**KEEPER_ROW, 'full_name': 'Tim Stützle'}
    pd.DataFrame([row]).to_csv(export_paths['keeper'], index=False, encoding='utf-8')

    api_export.export_keeper_only()

    payload = json.loads(export_paths['output'].read_text(encoding='utf-8'))
    names = [r['full_name'] for r in payload['keeper']['recommendations']]
    assert 'Tim Stützle' in names


def test_draft_payload_matches_the_frontend_type(export_paths):
    entries = api_export.build_draft_list()

    assert set(entries[0]) == DRAFT_PLAYER_KEYS, (
        "build_draft_list drifted from frontend/src/types/player.ts::DraftPlayer"
    )


def test_draft_payload_types_survive_the_json_round_trip(export_paths):
    # numpy scalars serialize fine in some pandas versions and raise in others;
    # the export must emit plain Python types, not whatever pandas handed back.
    entries = api_export.build_draft_list()

    revived = json.loads(json.dumps(entries))

    assert isinstance(revived[0]['id'], int)
    assert isinstance(revived[0]['projected_total'], float)
    assert isinstance(revived[0]['factors'], list)
