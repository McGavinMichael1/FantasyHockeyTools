import pandas as pd
import pytest

from src import keeper, mockDraft, season


MINE = '465.l.33072.t.1'
THEIRS = '465.l.33072.t.2'


def make_board(rows):
    """rows: (playerId, full_name, position, vorp)"""
    return pd.DataFrame(
        [{'playerId': p, 'full_name': n, 'position': pos, 'vorp': v}
         for p, n, pos, v in rows]
    )


def make_draft(rows):
    """rows: (pick, team_key, player_name)"""
    return pd.DataFrame(
        [{'pick': pick, 'round': 1, 'team_key': team, 'player_name': name,
          'yahoo_player_id': 1000 + pick}
         for pick, team, name in rows]
    )


def make_outcomes(rows):
    """rows: (playerId, actual_fp) or (playerId, actual_fp, full_name)"""
    return pd.DataFrame(
        [{'playerId': r[0], 'actual_fp': r[1],
          'full_name': r[2] if len(r) > 2 else f'Player {r[0]}'}
         for r in rows]
    ).set_index('playerId')


# --- name resolution ------------------------------------------------------

def test_resolve_picks_matches_names_that_are_not_byte_identical():
    board = make_board([(1, 'Tim Stutzle', 'C', 10.0)])
    draft = make_draft([(1, MINE, 'Tim Stützle')])

    resolved = mockDraft.resolve_picks(draft, board)

    assert resolved.loc[0, 'playerId'] == 1
    assert resolved.loc[0, 'board_name'] == 'Tim Stutzle'


def test_resolve_picks_keeps_unmatched_rows_so_pick_order_is_preserved():
    # Dropping a row would shift every later pick's position in the replay.
    board = make_board([(1, 'Connor McDavid', 'C', 10.0)])
    draft = make_draft([(1, MINE, 'Connor McDavid'),
                        (2, THEIRS, 'Some Undrafted Junior')])

    resolved = mockDraft.resolve_picks(draft, board)

    assert len(resolved) == 2
    # pandas stores the unmatched marker as NaN in a numeric column; replay()
    # reads it with pd.isna, so NaN is the contract, not None.
    assert pd.isna(resolved.loc[1, 'playerId'])


def test_resolve_picks_refuses_to_claim_one_board_row_twice():
    # Two Yahoo names collapsing onto one row would double-count his season.
    board = make_board([(1, 'Sebastian Aho', 'C', 10.0)])
    draft = make_draft([(1, MINE, 'Sebastian Aho'), (2, THEIRS, 'Sebastian Aho')])

    resolved = mockDraft.resolve_picks(draft, board)

    assert resolved.loc[0, 'playerId'] == 1
    assert pd.isna(resolved.loc[1, 'playerId'])


# --- replay ---------------------------------------------------------------

def test_board_takes_highest_vorp_available_at_the_owners_pick():
    board = make_board([(1, 'Best Guy', 'C', 30.0),
                        (2, 'Good Guy', 'L', 20.0),
                        (3, 'Okay Guy', 'R', 10.0)])
    # The owner really took the worst of the three.
    draft = make_draft([(1, MINE, 'Okay Guy')])

    replayed = mockDraft.replay(mockDraft.resolve_picks(draft, board), board, MINE)

    assert [p['name'] for p in replayed['board_roster']] == ['Best Guy']
    assert [p['name'] for p in replayed['my_actual']] == ['Okay Guy']


def test_opponents_keep_their_real_picks():
    board = make_board([(1, 'Best Guy', 'C', 30.0),
                        (2, 'Second Guy', 'L', 20.0),
                        (3, 'Third Guy', 'R', 10.0)])
    draft = make_draft([(1, THEIRS, 'Best Guy'), (2, MINE, 'Third Guy')])

    replayed = mockDraft.replay(mockDraft.resolve_picks(draft, board), board, MINE)

    # Best Guy went to the opponent before the owner's turn, so the board
    # cannot have him -- it takes the best of what is left.
    assert [p['name'] for p in replayed['board_roster']] == ['Second Guy']


def test_opponent_falls_back_when_the_board_stole_their_player():
    board = make_board([(1, 'Best Guy', 'C', 30.0),
                        (2, 'Second Guy', 'L', 20.0),
                        (3, 'Third Guy', 'R', 10.0)])
    # Owner picks first and really took Third Guy; the board takes Best Guy,
    # which is who the opponent really drafted at pick 2.
    draft = make_draft([(1, MINE, 'Third Guy'), (2, THEIRS, 'Best Guy')])

    replayed = mockDraft.replay(mockDraft.resolve_picks(draft, board), board, MINE)

    assert len(replayed['substitutions']) == 1
    assert replayed['substitutions'][0]['wanted'] == 'Best Guy'
    assert replayed['substitutions'][0]['got'] == 'Second Guy'


def test_positional_caps_stop_the_board_drafting_only_centers():
    # A pure best-available board would take five centers and post a fake win.
    board = make_board([(i, f'Center {i}', 'C', 100.0 - i) for i in range(1, 7)]
                       + [(99, 'A Defenseman', 'D', 1.0)])
    draft = make_draft([(pick, MINE, 'A Defenseman') for pick in range(1, 6)])

    replayed = mockDraft.replay(mockDraft.resolve_picks(draft, board), board, MINE)

    positions = [p['position'] for p in replayed['board_roster']]
    assert positions.count('C') == mockDraft.MAX_BY_POSITION['C']


def test_the_board_cannot_re_draft_a_player_the_owner_really_took():
    # Regression from the 2025 run: the owner's real picks were never removed
    # from the pool, so a player he took early floated down to the board later
    # for free (Adam Fox, owner's pick 3, taken by the board at 78 for 155.7 FP).
    # No opponent takes him either, since opponents replay their actual picks.
    board = make_board([(1, 'Best Guy', 'C', 30.0),
                        (2, 'Second Guy', 'L', 20.0),
                        (3, 'Third Guy', 'R', 10.0)])
    # Owner really took Third Guy at pick 1, then picks again at pick 2.
    draft = make_draft([(1, MINE, 'Third Guy'), (2, MINE, 'Third Guy')])
    resolved = mockDraft.resolve_picks(draft, board)

    replayed = mockDraft.replay(resolved, board, MINE)

    board_names = [p['name'] for p in replayed['board_roster']]
    assert 'Third Guy' not in board_names


def test_a_player_is_never_drafted_twice():
    board = make_board([(1, 'Best Guy', 'C', 30.0), (2, 'Second Guy', 'L', 20.0)])
    draft = make_draft([(1, MINE, 'Best Guy'), (2, MINE, 'Second Guy')])

    replayed = mockDraft.replay(mockDraft.resolve_picks(draft, board), board, MINE)

    ids = [p['playerId'] for p in replayed['board_roster']]
    assert len(ids) == len(set(ids))


# --- grading --------------------------------------------------------------

def test_grade_sums_actual_points():
    outcomes = make_outcomes([(1, 500.0), (2, 300.0)])

    graded = mockDraft.grade([{'playerId': 1, 'name': 'A'},
                              {'playerId': 2, 'name': 'B'}], outcomes)

    assert graded['total_fp'] == 800.0


def test_a_pick_who_never_played_scores_zero_rather_than_being_skipped():
    # Skipping would flatter whichever roster whiffed more.
    outcomes = make_outcomes([(1, 500.0)])

    graded = mockDraft.grade([{'playerId': 1, 'name': 'A'},
                              {'playerId': 404, 'name': 'Injured All Year'}], outcomes)

    assert graded['total_fp'] == 500.0
    assert graded['players'] == 2
    assert graded['no_outcome_rows'] == 1


def test_compare_reports_the_margin_and_who_won():
    outcomes = make_outcomes([(1, 500.0), (2, 100.0)])
    replayed = {
        'my_actual': [{'pick': 1, 'playerId': 2, 'name': 'Okay Guy'}],
        'board_roster': [{'pick': 1, 'playerId': 1, 'name': 'Best Guy'}],
        'substitutions': [],
        'unmatched_opponent_picks': 0,
    }

    result = mockDraft.compare(replayed, outcomes)

    assert result['verdict']['board_wins'] is True
    assert result['verdict']['board_minus_actual'] == 400.0
    assert result['head_to_head'][0]['delta'] == 400.0


def test_load_outcomes_rejects_duplicate_player_rows(tmp_path):
    # A duplicate would make .loc return a Series and inflate the total.
    path = tmp_path / 'player_seasons.csv'
    pd.DataFrame([{'playerId': 1, 'season': 2025, 'totalFP': 10.0, 'full_name': 'A'},
                  {'playerId': 1, 'season': 2025, 'totalFP': 20.0, 'full_name': 'A'}]
                 ).to_csv(path, index=False)

    with pytest.raises(ValueError, match='duplicate playerIds'):
        mockDraft.load_outcomes(2025, path=str(path), goalie_path=str(tmp_path / 'none.csv'))


def _write_outcome_tables(tmp_path, skaters, goalies=None):
    skater_path = tmp_path / 'player_seasons.csv'
    pd.DataFrame(skaters).to_csv(skater_path, index=False)
    goalie_path = tmp_path / 'goalie_seasons.csv'
    if goalies is not None:
        pd.DataFrame(goalies).to_csv(goalie_path, index=False)
    return str(skater_path), str(goalie_path)


def test_goalies_are_graded_from_the_goalie_table(tmp_path):
    # Regression: player_seasons.csv has no goalie rows, so reading only it
    # scored every drafted goalie zero -- several picks per roster.
    skater_path, goalie_path = _write_outcome_tables(
        tmp_path,
        skaters=[{'playerId': 1, 'season': 2025, 'totalFP': 500.0, 'full_name': 'A Skater'}],
        goalies=[{'playerId': 2, 'season': 2025, 'fantasyPoints': 300.0,
                  'full_name': 'A Goalie'}],
    )

    outcomes = mockDraft.load_outcomes(2025, path=skater_path, goalie_path=goalie_path)

    assert outcomes.loc[2, 'actual_fp'] == 300.0
    graded = mockDraft.grade([{'playerId': 2, 'name': 'A Goalie'}], outcomes)
    assert graded['total_fp'] == 300.0


def test_missing_goalie_table_degrades_loudly_rather_than_fatally(tmp_path, capsys):
    skater_path, goalie_path = _write_outcome_tables(
        tmp_path,
        skaters=[{'playerId': 1, 'season': 2025, 'totalFP': 500.0, 'full_name': 'A Skater'}],
    )

    outcomes = mockDraft.load_outcomes(2025, path=skater_path, goalie_path=goalie_path)

    assert len(outcomes) == 1
    assert 'goalie' in capsys.readouterr().out.lower()


def test_a_pick_the_board_never_had_is_graded_on_real_production():
    # Michkov, drafted in 2024 off a KHL season: no row in the 2023 board, but a
    # real NHL season afterwards. Scoring him zero would hand the board a free
    # win it did not earn.
    board = make_board([(1, 'Established Guy', 'C', 30.0)])
    draft = make_draft([(1, MINE, 'Rookie Sensation')])
    outcomes = make_outcomes([(1, 100.0, 'Established Guy'),
                              (77, 250.0, 'Rookie Sensation')])

    resolved = mockDraft.attach_outcome_ids(
        mockDraft.resolve_picks(draft, board), outcomes)

    assert pd.isna(resolved.loc[0, 'playerId'])          # not on the board
    assert resolved.loc[0, 'outcome_playerId'] == 77     # but he did produce

    replayed = mockDraft.replay(resolved, board, MINE)
    assert mockDraft.grade(replayed['my_actual'], outcomes)['total_fp'] == 250.0


# --- deriving who was kept ------------------------------------------------

def _team_draft(team_picks):
    """team_picks: {team_key: [(pick, name), ...]}"""
    rows = []
    for team, picks in team_picks.items():
        for pick, name in picks:
            rows.append({'pick': pick, 'round': 1 + (pick - 1) // 2,
                         'team_key': team, 'player_name': name,
                         'yahoo_player_id': pick, 'is_mine': team == MINE})
    return pd.DataFrame(rows)


def test_keepers_are_each_teams_last_picks_by_pick_number():
    # Owner's rule (2026-07-20): "the final 4 picks of every team are always the
    # kept players." Keeping costs a late pick, so Yahoo records it in that slot.
    draft = _team_draft({
        MINE: [(1, 'Early A'), (5, 'Early B'), (70, 'Kept A'), (90, 'Kept B')],
        THEIRS: [(2, 'Their Early'), (60, 'Their Kept A'), (80, 'Their Kept B')],
    })

    kept = mockDraft.derive_keepers(draft, keeper_count=2)

    assert set(kept[kept['team_key'] == MINE]['player_name']) == {'Kept A', 'Kept B'}
    assert set(kept[kept['team_key'] == THEIRS]['player_name']) == {
        'Their Kept A', 'Their Kept B'}


def test_keepers_are_derived_per_team_not_by_round():
    # Rounds cannot work: picks are traded wholesale, so in 2025 one team held
    # only rounds 1-9 and another only 10-18. A round-based rule would call the
    # early-only team's keepers "real picks" and miss them entirely.
    draft = _team_draft({
        MINE: [(1, 'A'), (2, 'B'), (3, 'Kept Early')],          # all early picks
        THEIRS: [(150, 'C'), (160, 'D'), (179, 'Kept Late')],   # all late picks
    })

    kept = mockDraft.derive_keepers(draft, keeper_count=1)

    assert set(kept['player_name']) == {'Kept Early', 'Kept Late'}


def test_deriving_keepers_raises_when_a_team_has_too_few_picks():
    draft = _team_draft({MINE: [(1, 'Only Pick')], THEIRS: [(2, 'A'), (3, 'B')]})

    with pytest.raises(ValueError, match='fewer than'):
        mockDraft.derive_keepers(draft, keeper_count=2)


# --- keepers were never in the pool ---------------------------------------

def test_kept_players_are_removed_from_the_draftable_pool():
    # The bug that voided the 2025 run: Yahoo records a kept player as an
    # ordinary pick in the round the keeper cost, so the board treated McDavid,
    # MacKinnon and Kucherov as available from pick 1 and "won" on them.
    board = make_board([(1, 'Connor McDavid', 'C', 99.0),
                        (2, 'Available Guy', 'C', 10.0)])

    filtered, unmatched = mockDraft.remove_keepers(board, ['Connor McDavid'])

    assert list(filtered['full_name']) == ['Available Guy']
    assert unmatched == []


def test_a_keeper_the_board_cannot_match_is_reported_not_swallowed():
    # An unmatched keeper is still in the pool and can still hand the board a
    # player it could never have had -- silence there is how this went wrong.
    board = make_board([(1, 'Connor McDavid', 'C', 99.0)])

    _, unmatched = mockDraft.remove_keepers(board, ['Some Unknown Keeper'])

    assert unmatched == ['Some Unknown Keeper']


def test_the_board_cannot_draft_a_keeper_end_to_end():
    board = make_board([(1, 'Connor McDavid', 'C', 99.0),
                        (2, 'Available Guy', 'L', 10.0)])
    filtered, _ = mockDraft.remove_keepers(board, ['Connor McDavid'])
    draft = make_draft([(1, MINE, 'Available Guy')])

    replayed = mockDraft.replay(mockDraft.resolve_picks(draft, filtered), filtered, MINE)

    assert 'Connor McDavid' not in [p['name'] for p in replayed['board_roster']]


def test_missing_keeper_file_refuses_rather_than_running_unfiltered(tmp_path):
    # Running without the list is exactly the void run. Failing loudly is the
    # only safe default, because the unfiltered result looks plausible.
    with pytest.raises(FileNotFoundError, match='keeper list'):
        mockDraft.load_season_keepers(2025, path=str(tmp_path / 'nope.csv'))


def test_empty_keeper_file_refuses(tmp_path):
    path = tmp_path / 'keepers_2025.csv'
    pd.DataFrame({'player_name': []}).to_csv(path, index=False)

    with pytest.raises(ValueError, match='empty keeper list'):
        mockDraft.load_season_keepers(2025, path=str(path))


def _write_keepers(tmp_path, count):
    path = tmp_path / 'keepers_2025.csv'
    pd.DataFrame({'player_name': [f'Keeper {i}' for i in range(count)]}).to_csv(
        path, index=False)
    return str(path)


def test_season_keepers_round_trip(tmp_path):
    full = keeper.TEAM_COUNT * keeper.KEEPER_COUNT
    path = _write_keepers(tmp_path, full)

    assert len(mockDraft.load_season_keepers(2025, path=path)) == full


def test_a_partial_keeper_list_is_rejected(tmp_path):
    # The dangerous case. An obviously-empty file fails loudly on its own; a
    # 24-of-40 file completes, looks plausible, and quietly leaves 16 keepers
    # draftable -- which is the exact shape of the bug that voided the 2025 run.
    path = _write_keepers(tmp_path, keeper.TEAM_COUNT * keeper.KEEPER_COUNT - 16)

    with pytest.raises(ValueError, match='expected'):
        mockDraft.load_season_keepers(2025, path=path)


# --- leakage guard --------------------------------------------------------

def test_a_draft_year_the_model_trained_through_is_flagged_contaminated():
    contaminated_year = max(season.DRAFT_VAL_SEASONS) + 1

    assert 'CONTAMINATED' in mockDraft.leakage_warning(contaminated_year)


def test_the_first_clean_draft_year_is_not_flagged():
    clean_year = max(season.DRAFT_VAL_SEASONS) + 2

    assert mockDraft.leakage_warning(clean_year) is None
