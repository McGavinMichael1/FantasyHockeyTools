import json

import pandas as pd

import api_export


def _write_rankings(path):
    selected = {
        "playerId": 8471,
        "full_name": "Example Skater",
        "position": "C",
        "keeper_rank": 1,
        "assigned_round": 18,
        "pick_cost": 150.4,
        "raw_keeper_value": 52.2,
        "net_keeper_value": 91.4,
        "projected_fpPerGame": 3.1,
        "projected_total": 241.8,
        "fpPerGame": 2.5,
        "gamesPlayed": 70,
        "confidence": 88,
        "target_season": "2026-27",
        "is_recommended": True,
    }
    unselected = {
        **selected,
        "playerId": 8472,
        "full_name": "Example Prospect",
        "position": "R",
        "keeper_rank": None,
        "assigned_round": None,
        "is_recommended": False,
    }
    pd.DataFrame([selected, unselected]).to_csv(path, index=False)


def test_build_keeper_section_exports_matching_advisor_metadata(tmp_path, monkeypatch):
    rankings_path = tmp_path / "keeper_rankings.csv"
    context_path = tmp_path / "keeper_advisor_context.json"
    _write_rankings(rankings_path)
    context_path.write_text(json.dumps({
        "schema_version": 1,
        "context_id": "abc123",
        "generated_at": "2026-07-17T12:00:00+00:00",
        "season": "2026-27",
    }), encoding="utf-8")
    monkeypatch.setattr(api_export, "KEEPER_RANKINGS_PATH", str(rankings_path))
    monkeypatch.setattr(api_export, "KEEPER_ADVISOR_CONTEXT_PATH", str(context_path))

    section = api_export.build_keeper_section()

    assert section["advisor_ready"] is True
    assert section["advisor_context_id"] == "abc123"
    assert section["advisor_generated_at"] == "2026-07-17T12:00:00+00:00"
    assert section["advisor_roster"] == [
        {"player_id": 8471, "name": "Example Skater"},
        {"player_id": 8472, "name": "Example Prospect"},
    ]
    assert "summary" not in section
    assert section["recommendations"][0]["full_name"] == "Example Skater"


def test_build_keeper_section_keeps_rankings_when_context_is_missing(tmp_path, monkeypatch):
    rankings_path = tmp_path / "keeper_rankings.csv"
    _write_rankings(rankings_path)
    monkeypatch.setattr(api_export, "KEEPER_RANKINGS_PATH", str(rankings_path))
    monkeypatch.setattr(
        api_export, "KEEPER_ADVISOR_CONTEXT_PATH", str(tmp_path / "missing.json")
    )

    section = api_export.build_keeper_section()

    assert section["advisor_ready"] is False
    assert section["advisor_context_id"] is None
    assert section["recommendations"][0]["full_name"] == "Example Skater"


def test_build_keeper_section_rejects_context_for_another_season(tmp_path, monkeypatch):
    rankings_path = tmp_path / "keeper_rankings.csv"
    context_path = tmp_path / "keeper_advisor_context.json"
    _write_rankings(rankings_path)
    context_path.write_text(json.dumps({
        "schema_version": 1,
        "context_id": "stale",
        "generated_at": "2026-07-17T12:00:00+00:00",
        "season": "2025-26",
    }), encoding="utf-8")
    monkeypatch.setattr(api_export, "KEEPER_RANKINGS_PATH", str(rankings_path))
    monkeypatch.setattr(api_export, "KEEPER_ADVISOR_CONTEXT_PATH", str(context_path))

    section = api_export.build_keeper_section()

    assert section["advisor_ready"] is False
    assert section["advisor_context_id"] is None
