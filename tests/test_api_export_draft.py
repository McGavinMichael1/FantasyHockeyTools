import pandas as pd

import api_export
from src import keeper, mockDraft


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


def test_draft_roster_rules_serialize_the_python_slot_constants():
    """The roster panel must not become a third hand-maintained copy of the slots.

    keeper.py owns them, mockDraft caps against them, and the frontend needs the
    same numbers to say what a roster still needs. Shipping them through the
    export keeps one source of truth instead of a TS constant that drifts.
    """
    rules = api_export._draft_roster_rules()

    assert rules['starting_slots'] == keeper.STARTING_SLOTS
    assert rules['max_by_position'] == mockDraft.MAX_BY_POSITION
    assert rules['util_slots'] == keeper.ROSTER_SLOTS['UTIL']
    assert rules['roster_slots'] == keeper.ROSTER_SLOTS


def test_draft_roster_rules_floor_only_the_positions_the_board_ranks():
    # UTIL/BN/IR+ take any skater, so they impose no positional floor. A panel
    # that treated them as required would demand a roster nobody can draft.
    rules = api_export._draft_roster_rules()

    assert set(rules['starting_slots']) == set(keeper.REPLACEMENT_RANKS)
    assert set(rules['max_by_position']) == set(keeper.REPLACEMENT_RANKS)


SKATER_STATS = {
    'totalGoals': 31, 'totalAssists': 45, 'totalShotsOnGoal': 240,
    'totalHits': 88, 'totalShotsBlocked': 41, 'totalPPP': 22,
    'avgIcetime': 1140.0, 'ppToiShare': 0.184,
}

GOALIE_STATS = {
    'wins': 34, 'losses': 21, 'shutouts': 4, 'save_pct': 0.918,
    'gsax': 12.4, 'gamesStarted': 58,
}


def _labels(entry) -> list:
    return [stat['label'] for stat in entry['stats']]


def _value(entry, label) -> str:
    return next(stat['value'] for stat in entry['stats'] if stat['label'] == label)


def test_skaters_export_a_display_stat_line(tmp_path, monkeypatch):
    """The board shows projections and SHAP labels but no actual production.

    Without a stat line there is nothing on screen to sanity-check a projection
    against -- every number is the model talking about itself.
    """
    df = pd.DataFrame([{**BASE_ROW, 'position': 'C', **SKATER_STATS}])
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    entry = api_export.build_draft_list()[0]

    assert _labels(entry) == ['G', 'A', 'SOG', 'HIT', 'BLK', 'PPP', 'TOI/G', 'PP%']
    assert _value(entry, 'G') == '31'
    assert _value(entry, 'TOI/G') == '19:00', 'icetime is stored in seconds'
    assert _value(entry, 'PP%') == '18%'


def test_goalies_export_their_own_stat_line(tmp_path, monkeypatch):
    # A goalie's line shares no columns with a skater's, so the export emits
    # label/value pairs and the board renders whatever it is handed.
    df = pd.DataFrame([{**BASE_ROW, 'position': 'G', **GOALIE_STATS}])
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    entry = api_export.build_draft_list()[0]

    assert _labels(entry) == ['GS', 'W', 'L', 'SO', 'SV%', 'GSAx']
    assert _value(entry, 'W') == '34'
    assert _value(entry, 'SV%') == '.918'


def test_a_csv_without_stat_columns_exports_an_empty_stat_line(tmp_path, monkeypatch):
    # Boards built before these columns existed must still export rather than
    # raise -- the same degrade-never-crash rule vorp and confidence follow.
    df = pd.DataFrame([BASE_ROW])
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    assert api_export.build_draft_list()[0]['stats'] == []


def test_a_missing_stat_is_dropped_rather_than_shown_as_zero(tmp_path, monkeypatch):
    # A blank hit count is "we do not have it", not "he threw none" -- and the
    # board has no way to tell those apart once a zero is rendered.
    stats = {**SKATER_STATS}
    stats['totalHits'] = float('nan')
    df = pd.DataFrame([{**BASE_ROW, 'position': 'C', **stats}])
    path = tmp_path / 'draft_rankings.csv'
    df.to_csv(path, index=False)
    monkeypatch.setattr(api_export, 'DRAFT_RANKINGS_PATH', str(path))

    assert 'HIT' not in _labels(api_export.build_draft_list()[0])
