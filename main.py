import argparse
import json
import os
from collections import Counter

import pandas as pd

from src import backtest
from src import dataProcessing
from src import draft_explain
from src import keeper
from src import keeper_advisor
from src import keepers
from src import mockDraft
from src import moneypuck
from src import season
from src import yahooAPI
from src.features import draft as draftFeatures
from src.features import goalies as goalieFeatures
from src.features import mlFeatures
from src.features import pickups
from src.models import cooling as coolingModel
from src.models import draft as draftModel
from src.models import goalieDraft as goalieDraftModel
from src.models import pickups as pickupModel

CURRENT_SEASON = season.CURRENT_SEASON
KEEPER_RANKINGS_PATH = os.path.join('data', 'processed', 'keeper_rankings.csv')
GOALIE_SEASONS_PATH = os.path.join('data', 'processed', 'goalie_seasons.csv')
PLAYER_SEASONS_PATH = os.path.join('data', 'processed', 'player_seasons.csv')


def loadLabeledHistory():
    """Rolling features + next-5-game FP target on completed seasons."""
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    # current season has no future games to label — train on completed seasons
    historical_df = df[df['season'] <= season.LAST_COMPLETED_SEASON].copy()
    return mlFeatures.buildLabel(historical_df)


def trainPickups():
    historical_df = loadLabeledHistory()
    print("=== Training pickup (heating up) model ===")
    pickupModel.train(historical_df)
    print("=== Training cooling model ===")
    coolingModel.train(historical_df)


def runPickups():
    moneypuck.checkCurrentFreshness()

    # Identity/roster only -- the sole remaining NHL API use in this path
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)

    # Heuristic stats from MoneyPuck: full league scoring incl. hits/blocks
    # (no plusMinus/GWG -- the same accepted approximation as the ML label)
    game_df = moneypuck.loadGameLogs(min_season=2020)
    pickup_stats = moneypuck.buildPickupStats(game_df, CURRENT_SEASON)

    # Try to get rostered players from Yahoo (optional)
    rostered_nhle_ids = set()
    try:
        lg = yahooAPI.getLeague()
        rostered_names = yahooAPI.getRosteredIds(lg)
        rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)
        print(f"Yahoo API: Filtering out {len(rostered_nhle_ids)} rostered players")
    except FileNotFoundError as e:
        print(f"⚠️  Yahoo API disabled: {e}")
        print("   To enable, create oauth2.json with Yahoo OAuth credentials")
        print("   See: https://github.com/josuebrunel/yahoo-oauth#setup-oauth2")
    except Exception as e:
        print(f"⚠️  Yahoo API error (continuing without roster filter): {e}")

    results = pickups.rankFreeAgents(pickup_stats, allPlayerData, rostered_nhle_ids)

    # ML score from the saved model (train with: python main.py train-pickups)
    # Models regress next-5-game FP/g; convert to 0-1 percentile ranks so the
    # heuristic blend and score displays keep a bounded scale. Low predicted
    # FP/g = cooling down, so the cooling score is inverted.
    current_players = pickups.latestGameState()
    current_players['pred_next5_fp'] = pickupModel.predict(current_players)
    current_players['ml_score'] = current_players['pred_next5_fp'].rank(pct=True)
    current_players['cooling_pred_next5_fp'] = coolingModel.predict(current_players)
    current_players['cooling_score'] = 1 - current_players['cooling_pred_next5_fp'].rank(pct=True)
    current_players = current_players.merge(
        allPlayerData[['id', 'full_name', 'positionCode']],
        left_on='playerId',
        right_on='id',
        how='left'
    )
    current_players['display_name'] = current_players['full_name'].fillna(current_players['name'])

    results['weighted_score_normalized'] = (results['weighted_score'] - results['weighted_score'].min()) / (results['weighted_score'].max() - results['weighted_score'].min())
    combined = results.merge(current_players[['playerId', 'ml_score', 'pred_next5_fp']],
                             on='playerId', how='left')
    combined = combined.dropna(subset=['ml_score'])
    combined['final_score'] = pickups.blendScores(
        combined['weighted_score_normalized'], combined['ml_score'])

    print("\n=== Top available pickups (heuristic + ML blend) ===")
    print(combined[['full_name', 'positionCode', 'weighted_score', 'pred_next5_fp', 'ml_score', 'final_score']]
          .sort_values('final_score', ascending=False)
          .head(20)
          .to_string())

    print("\n=== Cooling down (drop candidates watch list) ===")
    print(current_players[['display_name', 'positionCode', 'cooling_pred_next5_fp', 'cooling_score', 'gamesPlayed']]
          .sort_values('cooling_score', ascending=False)
          .head(20)
          .to_string())


def loadPlayerSeasonFeatures():
    """Draft feature rows from the cached player-season table (built by
    scripts/build_player_seasons.py -- see fht-operations; not rebuilt here
    because that re-reads the 2.6 GB MoneyPuck history)."""
    seasons_path = os.path.join('data', 'processed', 'player_seasons.csv')
    if not os.path.exists(seasons_path):
        raise FileNotFoundError(
            f"{seasons_path} missing -- run scripts/build_player_seasons.py first")
    player_seasons = pd.read_csv(seasons_path)
    return draftFeatures.build_draft_features(player_seasons)


def trainDraft():
    """Train the draft ranker on historical player-season data (Phase B, see PROJECT-PLAN.md)."""
    draftModel.train(loadPlayerSeasonFeatures())


def loadGoalieSeasonFeatures():
    """Goalie draft feature rows from the cached goalie-season table (built by
    scripts/build_goalie_seasons.py -- see data/raw/goalies/README.md)."""
    if not os.path.exists(GOALIE_SEASONS_PATH):
        raise FileNotFoundError(
            f"{GOALIE_SEASONS_PATH} missing -- run scripts/build_goalie_seasons.py first")
    return goalieFeatures.build_goalie_features(pd.read_csv(GOALIE_SEASONS_PATH))


def trainGoalies():
    """Train the goalie draft ranker (GATE G3 protocol, see the spec)."""
    goalieDraftModel.train(loadGoalieSeasonFeatures())


def buildCurrentDraftProjections(feature_season=None):
    """Build every skater projection used by draft and keeper tools.

    `feature_season` is the season whose stats feed the model; the projection is
    for the season AFTER it. Defaults to CURRENT_SEASON, which is what the live
    draft board wants. The mock-draft backtest passes an earlier season to
    rebuild the board as it would have looked on a past draft day -- hence the
    parameter rather than mutating the season constant, which tests pin.
    """
    feature_season = CURRENT_SEASON if feature_season is None else feature_season
    df = loadPlayerSeasonFeatures()
    current = df[df['season'] == feature_season].copy()
    if current.empty:
        raise ValueError(
            f"No player-season rows for season {feature_season}. "
            f"Available: {sorted(df['season'].unique())}")
    current['projected_fpPerGame'] = draftModel.predict(current)

    rankings = current[['playerId', 'full_name', 'position', 'gamesPlayed',
                        'fpPerGame', 'projected_fpPerGame']].copy()
    # age at the UPCOMING season start (draft-day age), one year past the
    # feature season's age_at_season_start
    rankings['age'] = current['age_at_season_start'] + 1
    rankings['projected_total'] = rankings['projected_fpPerGame'] * 78
    rankings['delta_vs_last'] = rankings['projected_fpPerGame'] - rankings['fpPerGame']

    # --- Explainability: data-driven confidence + top SHAP factors ---
    # Computed here, before the sort and keeper filter, so the columns ride
    # along with their rows. Display-only: nothing below feeds the model.
    # Seasons of prior history feeds confidence: distinct seasons each player
    # appears in, up to and including the feature season.
    seasons_of_history = (df[df['season'] <= feature_season]
                          .groupby('playerId')['season'].nunique())
    rankings['confidence'] = [
        draft_explain.compute_confidence(
            seasons_of_history=int(seasons_of_history.get(pid, 1)),
            feature_gp=int(gp),
            age=age,
            projection=float(proj),
            fp_w3=fp_w3,
        )
        for pid, gp, age, proj, fp_w3 in zip(
            current['playerId'], current['gamesPlayed'], rankings['age'],
            current['projected_fpPerGame'], current['fp_w3'])
    ]

    # Six factor columns: top 3 positive then top 3 negative SHAP contributions,
    # each a JSON {"label", "value"} cell (empty string when a slot is unused).
    contribs = draftModel.shap_contributions(current)
    factor_cols = [f'factor_{i}' for i in range(1, 7)]
    factor_rows = []
    for idx in current.index:
        factors = draft_explain.top_factors(contribs.loc[idx].to_dict(), top_n=3)
        cells = [json.dumps({'label': f['label'], 'value': round(f['value'], 4)})
                 for f in factors]
        cells += [''] * (len(factor_cols) - len(cells))
        factor_rows.append(cells[:len(factor_cols)])
    for col, values in zip(factor_cols, zip(*factor_rows)):
        rankings[col] = list(values)

    return rankings


GOALIE_GP_CAP = 65        # a goalie season tops out around 65 starts
GOALIE_DISPLAY_MIN_GP = 15  # display floor, mirrors goalieDraft.MIN_GP


def buildCurrentGoalieProjections(feature_season=None):
    """Current-season goalie projections shaped like the skater board.

    projected_total = projected FP/GP x projected GP, where projected GP is
    the 50/30/20 weighted games played capped at GOALIE_GP_CAP -- the x78
    skater assumption is wrong for goalies, where workload IS the value.
    No confidence/factor columns in v1 (the ranker may be Baseline B).
    """
    feature_season = CURRENT_SEASON if feature_season is None else feature_season
    df = loadGoalieSeasonFeatures()
    current = df[df['season'] == feature_season].copy()
    if current.empty:
        raise ValueError(
            f"No goalie-season rows for season {feature_season}. "
            f"Available: {sorted(df['season'].unique())}")
    current['projected_fpPerGame'] = goalieDraftModel.predict(current)

    rankings = current[['playerId', 'full_name', 'position', 'gamesPlayed',
                        'fpPerGame', 'projected_fpPerGame']].copy()
    rankings['age'] = current['age_at_season_start'] + 1
    rankings['projected_gp'] = current['gp_w3'].clip(upper=GOALIE_GP_CAP)
    rankings['projected_total'] = (rankings['projected_fpPerGame']
                                   * rankings['projected_gp'])
    rankings['delta_vs_last'] = (rankings['projected_fpPerGame']
                                 - rankings['fpPerGame'])
    return rankings


def buildFullProjections(feature_season=None):
    """Skater + goalie projection board. Goalie prerequisites missing (no
    goalie_seasons.csv or no trained goalie model) degrades to skaters-only
    with a loud warning -- never silently, never fatally."""
    projections = buildCurrentDraftProjections(feature_season)
    projections['projected_gp'] = 78
    try:
        projections = pd.concat(
            [projections, buildCurrentGoalieProjections(feature_season)], ignore_index=True)
    except FileNotFoundError as e:
        print(f"⚠️  Goalie projections unavailable ({e})")
        print("   Board is SKATERS-ONLY. Run scripts/build_goalie_seasons.py and")
        print("   'python main.py train-goalies' to include goalies.")
    return projections


SKATER_DISPLAY_MIN_GP = 20  # tiny-sample rate stats are too noisy to rank


def applyDisplayFloors(rankings):
    """Drop tiny-sample players from a projection board.

    An injury-shortened season can still carry keeper value, but a rate stat off
    a handful of games is noise. Shared by the live board and the mock-draft
    backtest: if the backtest ranked players the real board never shows, it would
    be grading a tool the owner does not have.
    """
    is_goalie = rankings['position'] == 'G'
    return rankings[
        (~is_goalie & (rankings['gamesPlayed'] >= SKATER_DISPLAY_MIN_GP))
        | (is_goalie & (rankings['gamesPlayed'] >= GOALIE_DISPLAY_MIN_GP))
    ].copy()


def runDraft():
    """Rank this year's draft-eligible (non-keeper) players by projected fantasy value."""
    rankings = applyDisplayFloors(buildFullProjections())

    # Draft pool must exclude anyone already kept -- keeper lists aren't in the Yahoo
    # API until draft day, so they're maintained manually in data/raw/keepers.csv.
    # Missing/empty file = keepers not announced yet: warn loudly and rank everyone
    # rather than refuse, so pre-draft-day rankings (and the frontend) still work.
    kept_counts = None
    try:
        keeper_names = keepers.loadKeepers()
        kept_counts = keeper.keeper_position_counts(keeper_names, rankings)
        before = len(rankings)
        rankings = keepers.filterOutKeepers(rankings, keeper_names)
        print(f"Keepers: removed {before - len(rankings)} of {len(keeper_names)} listed keepers from the pool")
        print(f"   kept by position: {kept_counts}")
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  No keeper list applied ({e})")
        print("   Rankings include EVERY player. Fine before keepers are announced;")
        print("   on draft day, fill data/raw/keepers.csv and re-run.")

    # VORP AFTER the keeper filter, and against demand-adjusted ranks. Both
    # halves matter and neither is optional:
    #   - the pool is who you can actually draft; a kept player is not an
    #     alternative to a pick, so he cannot set the price of one.
    #   - the RANK has to come down with him. Replacement level is the marginal
    #     drafted starter, and the league does not draft the slots its keepers
    #     already fill. Holding C at rank 24 while removing 15 kept centers
    #     double-counts the removal.
    # Getting only the pool right measurably does not fix the board: the 2025
    # all-teams sweep drafted 60 D, 40 L, 20 G, 20 R and ZERO centers, and a
    # post-keeper pool at the base ranks still produced 6 D and 1 C. The floor
    # rule in mockDraft._best_available is what fixes the roster; this is what
    # makes the price honest.
    rankings['vorp'] = keeper.vorp_column(rankings, kept_counts=kept_counts)

    # VORP is the default cross-position order (owner decision 2026-07-16).
    rankings = rankings.sort_values('vorp', ascending=False)
    out_path = os.path.join('data', 'processed', 'draft_rankings.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rankings.to_csv(out_path, index=False)
    print(f"\nWrote {len(rankings)} players to {out_path}")

    # The ranks this board's vorp was computed with. api_export.py cannot
    # re-derive them -- the CSV above is keeper-filtered, so the kept players'
    # positions are gone from it -- and the frontend's draft-day recomputation
    # has to use the same ranks or it silently disagrees with the column.
    ranks_path = os.path.join('data', 'processed', 'draft_replacement_ranks.json')
    with open(ranks_path, 'w') as handle:
        json.dump(keeper.replacement_ranks(kept_counts), handle, indent=2)

    print("\n=== Top 20 by VORP (cross-position) ===")
    print(rankings[['full_name', 'position', 'age', 'gamesPlayed',
                    'fpPerGame', 'projected_fpPerGame', 'projected_gp',
                    'projected_total', 'vorp', 'delta_vs_last']]
          .head(20)
          .to_string(index=False))

    goalie_rows = rankings[rankings['position'] == 'G']
    if not goalie_rows.empty:
        print("\n=== Top 10 goalies (GATE G4 eyeball) ===")
        print(goalie_rows[['full_name', 'age', 'gamesPlayed', 'fpPerGame',
                           'projected_fpPerGame', 'projected_gp',
                           'projected_total', 'vorp']]
              .head(10)
              .to_string(index=False))


def runKeeper():
    """Rank the authenticated Yahoo roster and build advisor context."""
    projections = buildFullProjections()
    league = yahooAPI.getLeague()
    roster = yahooAPI.getMyRoster(league)

    # What you get INSTEAD of keeping someone is a draft pick, and a draft pick
    # cannot fetch a player another team kept. So replacement levels and pick
    # costs come from the pool with all 40 keepers removed -- while `projections`
    # keeps them, because your own four are exactly who this is rating.
    pool, kept_counts = None, None
    try:
        keeper_names = keepers.loadKeepers()
        kept_counts = keeper.keeper_position_counts(keeper_names, projections)
        pool = keepers.filterOutKeepers(projections, keeper_names)
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  No keeper list applied ({e})")
        print("   Keeper values are priced against the FULL pool, which overstates")
        print("   what your picks could fetch. Fill data/raw/keepers.csv and re-run.")

    rankings = keeper.analyze_keepers(roster, projections, pool=pool,
                                      kept_counts=kept_counts)
    rankings['target_season'] = keeper.target_season_label(CURRENT_SEASON)

    os.makedirs(os.path.dirname(KEEPER_RANKINGS_PATH), exist_ok=True)
    rankings.to_csv(KEEPER_RANKINGS_PATH, index=False)
    print(f"\nWrote {len(rankings)} roster rows to {KEEPER_RANKINGS_PATH}")

    try:
        skater_history = (
            pd.read_csv(PLAYER_SEASONS_PATH)
            if os.path.exists(PLAYER_SEASONS_PATH) else None
        )
        goalie_history = (
            pd.read_csv(GOALIE_SEASONS_PATH)
            if os.path.exists(GOALIE_SEASONS_PATH) else None
        )
        context = keeper_advisor.build_context(
            rankings,
            projections,
            skater_history=skater_history,
            goalie_history=goalie_history,
            yahoo_settings=league.settings(),
            pool=pool,
            kept_counts=kept_counts,
        )
        keeper_advisor.write_context(context)
        print(f"Wrote keeper advisor context {context['context_id'][:12]} to "
              f"{keeper_advisor.CONTEXT_PATH}")
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"WARNING: keeper rankings are ready, but advisor context failed: {error}")

    recommended = rankings[rankings['is_recommended']].sort_values('keeper_rank')
    if recommended.empty:
        print("No keeper recommendations were matched to the projection board.")
        return

    print("\n=== Recommended keepers ===")
    print(recommended[[
        'keeper_rank', 'full_name', 'position', 'projected_fpPerGame',
        'projected_total', 'raw_keeper_value', 'assigned_round', 'pick_cost',
        'net_keeper_value'
    ]].to_string(index=False))


def _mockDraftBoard(year, draft_df, exclude_unavailable, outcomes):
    """The draftable pool for a mock draft: keepers out, optionally absentees out.

    Split out from runMockDraft so an all-teams sweep builds it once. Rebuilding
    per team would be ten passes over the projection pipeline for an identical
    result -- the board does not depend on whose picks are being replaced.
    """
    # Kept players were never in the pool. Yahoo records them as ordinary picks
    # in the late slot the keeper cost, so they have to be excluded -- leaving
    # them in is what voided the first 2025 run, where the board drafted eight
    # of other teams' keepers and "won" on the strength of it.
    #
    # Derived from each team's last picks (owner's rule). An explicit
    # data/raw/keepers_{year}.csv overrides, for a season the rule does not fit.
    kept_by_team = None
    try:
        keeper_names = mockDraft.load_season_keepers(year)
        print(f"Keepers: using the explicit list ({len(keeper_names)} players)")
    except FileNotFoundError:
        kept = mockDraft.derive_keepers(draft_df)
        keeper_names = kept['player_name'].dropna().tolist()
        kept_by_team = {
            team_key: rows['player_name'].dropna().tolist()
            for team_key, rows in kept.groupby('team_key')
        }
        print(f"Keepers: derived {len(keeper_names)} from each team's last "
              f"{keeper.KEEPER_COUNT} picks")

    before = len(draft_df)
    draft_df = draft_df[~draft_df['player_name'].isin(keeper_names)].copy()
    print(f"   removed {before - len(draft_df)} keeper rows from the draft record")

    # Features from the season before the draft; outcomes from the season after.
    # Same display floors as the live board -- otherwise the backtest drafts
    # tiny-sample players the real tool would never have shown, and grades a
    # tool the owner does not have.
    board = applyDisplayFloors(buildFullProjections(feature_season=year - 1))

    # Positions have to be read off the UNFILTERED board -- the keepers are
    # about to be removed from it.
    kept_counts = keeper.keeper_position_counts(keeper_names, board)
    kept_positions_by_team = None
    if kept_by_team is not None:
        kept_positions_by_team = {
            team_key: keeper.keeper_position_counts(names, board)
            for team_key, names in kept_by_team.items()
        }

    board, unmatched_keepers = mockDraft.remove_keepers(board, keeper_names)
    if unmatched_keepers:
        print(f"⚠️  {len(unmatched_keepers)} keepers unmatched on the board and still "
              f"draftable: {unmatched_keepers}")

    # VORP AFTER the keeper filter and against demand-adjusted ranks, matching
    # runDraft. See the comment there for why both halves are needed.
    board['vorp'] = keeper.vorp_column(board, kept_counts=kept_counts)
    board = board.dropna(subset=['vorp'])
    print(f"   kept by position: {kept_counts}")

    dropped = []
    if exclude_unavailable:
        board, dropped = mockDraft.drop_unavailable(board, outcomes)
        print(f"⚠️  DIRECTIONAL RUN: dropped {len(dropped)} players who never played "
              f"season {year}. This uses hindsight the board would not have had, so "
              f"the margin is inflated by an unknown amount -- not evidence.")

    print(f"Board rebuilt from season {year - 1}: {len(board)} draftable players")
    return board, draft_df, dropped, kept_positions_by_team


def _mockDraftOneTeam(year, draft_df, board, outcomes, team_key, warning,
                      exclude_unavailable, dropped, verbose=True,
                      kept_positions=None):
    """Replay a single team's draft against an already-built board.

    `kept_positions` is this team's own keepers by position: slots already
    filled, which the board's positional floors must not ask it to fill again.
    """
    resolved = mockDraft.resolve_picks(draft_df, board)
    unmatched = int(resolved['playerId'].isna().sum())

    # Grading ids are resolved separately: a pick the board never had (a rookie
    # off a non-NHL season) still produced, and must not be scored as a zero.
    resolved = mockDraft.attach_outcome_ids(resolved, outcomes)

    replayed = mockDraft.replay(resolved, board, team_key, kept_counts=kept_positions)
    result = mockDraft.compare(replayed, outcomes)

    # The human keeps eating absentees even when the board no longer can. This
    # number is the price of that asymmetry, reported rather than absorbed.
    human_zeros = mockDraft.count_unavailable(replayed['my_actual'], outcomes)

    result['meta'] = {
        'draft_year': year,
        'feature_season': year - 1,
        'outcome_season': year,
        'unmatched_picks': unmatched,
        'leakage_warning': warning,
        'team_key': team_key,
        'exclude_unavailable': exclude_unavailable,
        'players_dropped_as_unavailable': len(dropped),
        'human_picks_that_never_played': human_zeros,
        'directional_only': exclude_unavailable,
    }

    if verbose:
        verdict = result['verdict']
        print(f"Name matching: {len(resolved) - unmatched} of {len(resolved)} picks resolved")
        print(f"\n=== {year} mock draft vs {team_key} ===")
        # Startable lineup is the verdict; the all-picks sum is shown alongside
        # because it is what runs before lineup grading recorded.
        print(f"Actual lineup: {verdict['actual_lineup_fp']:.1f} FP "
              f"(all picks {verdict['actual_total_fp']:.1f})")
        print(f"Board lineup:  {verdict['board_lineup_fp']:.1f} FP "
              f"(all picks {verdict['board_total_fp']:.1f})")
        print(f"Margin:        {verdict['board_minus_actual']:+.1f} FP "
              f"({'board wins' if verdict['board_wins'] else 'actual draft wins'})")
        board_mix = Counter(p['position'] for p in result['board_roster']['picks'])
        print(f"Board position mix: {dict(sorted(board_mix.items()))}")
        print(f"Opponent substitutions forced by the board: {len(result['substitutions'])}")
        print(f"Their picks that never played: {human_zeros}")
        print("\n=== Pick by pick ===")
        print(pd.DataFrame(result['head_to_head']).to_string(index=False))

    return result


def runMockDraft(year, refresh=False, team=None, all_teams=False,
                 exclude_unavailable=False):
    """Replay a past draft with the board making one team's picks.

    The board is rebuilt from the season BEFORE the draft -- the only data that
    existed on draft day -- and graded on what players actually scored in the
    season they were drafted for.

    `team` replays a league-mate instead of the owner; `all_teams` sweeps every
    manager in the league, which turns a single anecdote into a distribution.
    """
    warning = mockDraft.leakage_warning(year)
    if warning:
        print(f"\n⚠️  {warning}\n")

    draft_df = yahooAPI.loadDraftResults(year, refresh=refresh)
    outcomes = mockDraft.load_outcomes(year)
    board, draft_df, dropped, kept_by_team = _mockDraftBoard(
        year, draft_df, exclude_unavailable, outcomes)
    kept_by_team = kept_by_team or {}

    if not all_teams:
        team_key = mockDraft.select_team_key(draft_df, team)
        result = _mockDraftOneTeam(year, draft_df, board, outcomes, team_key,
                                   warning, exclude_unavailable, dropped,
                                   kept_positions=kept_by_team.get(team_key))
        # A league-mate's run gets its own file: the owner's 2025 report is the
        # recorded FINAL GATE result and must not be overwritten by a variant.
        suffix = '' if team is None else f"_{team_key.split('.')[-1]}"
        suffix += '_noinj' if exclude_unavailable else ''
        path = mockDraft.write_report(result, f"{year}{suffix}")
        print(f"\nWrote {path}")
        if warning:
            print("Remember: this run is contaminated. Harness check only.")
        return result

    owner_key = mockDraft.owner_team_key(draft_df)
    rows, results = [], {}
    for team_key in sorted(draft_df['team_key'].astype(str).unique()):
        result = _mockDraftOneTeam(year, draft_df, board, outcomes, team_key,
                                   warning, exclude_unavailable, dropped, verbose=False,
                                   kept_positions=kept_by_team.get(team_key))
        verdict = result['verdict']
        results[team_key] = result
        mix = Counter(p['position'] for p in result['board_roster']['picks'])
        rows.append({
            'team': team_key.split('.')[-1] + (' (you)' if team_key == owner_key else ''),
            'actual_fp': verdict['actual_lineup_fp'],
            'board_fp': verdict['board_lineup_fp'],
            'margin': verdict['board_minus_actual'],
            'pct': round(100 * verdict['board_minus_actual'] / verdict['actual_lineup_fp'], 2),
            'board_wins': verdict['board_wins'],
            'mix': ''.join(f"{position}{mix[position]}"
                           for position in sorted(mix) if mix[position]),
            'subs': len(result['substitutions']),
            'their_zeros': result['meta']['human_picks_that_never_played'],
        })

    table = pd.DataFrame(rows).sort_values('pct', ascending=False)
    print(f"\n=== {year} mock draft: all {len(rows)} teams ===")
    print(table.to_string(index=False))
    wins = int(table['board_wins'].sum())
    print(f"\nBoard beat {wins} of {len(rows)} managers")
    print(f"Mean margin:   {table['margin'].mean():+.1f} FP ({table['pct'].mean():+.2f}%)")
    print(f"Median margin: {table['margin'].median():+.1f} FP ({table['pct'].median():+.2f}%)")
    if exclude_unavailable:
        print("\n⚠️  DIRECTIONAL ONLY -- absentees were removed with hindsight.")

    suffix = '_all' + ('_noinj' if exclude_unavailable else '')
    path = mockDraft.write_report(
        {'per_team': results, 'summary': rows}, f"{year}{suffix}")
    print(f"Wrote {path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Fantasy hockey tools")
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('train-pickups', help='train pickup + cooling models on historical seasons')
    sub.add_parser('pickups', help='rank available free agents (uses saved models)')
    sub.add_parser('train-draft', help='train the draft ranker on historical player-seasons')
    sub.add_parser('train-goalies', help='train the goalie draft ranker on historical goalie-seasons')
    sub.add_parser('draft', help='rank this year\'s non-keeper players for the draft')
    sub.add_parser('keeper', help='rank four keepers from the authenticated Yahoo roster')
    spot = sub.add_parser('spot-check', help='replay the pickup ranking at historical dates and grade it')
    spot.add_argument('--date', type=int, help='single as-of date as YYYYMMDD (default: several across the season)')
    spot.add_argument('--top', type=int, default=15, help='size of the ranked list to grade')
    mock = sub.add_parser('mock-draft', help='replay a past draft with the board making your picks')
    mock.add_argument('--year', type=int, required=True, help='draft year (Oct 2025 draft = 2025)')
    mock.add_argument('--refresh', action='store_true',
                      help='re-fetch draft results from Yahoo instead of using the cache')
    mock.add_argument('--team', help="replay a league-mate's draft instead of your own "
                                     "(full team_key, or just its number e.g. 5)")
    mock.add_argument('--all-teams', action='store_true',
                      help='sweep every manager in the league and summarise')
    mock.add_argument('--exclude-unavailable', action='store_true',
                      help='drop players who never played the outcome season from the '
                           'pool. Uses hindsight -- makes the run DIRECTIONAL ONLY')

    args = parser.parse_args()
    if args.command == 'train-pickups':
        trainPickups()
    elif args.command == 'pickups':
        runPickups()
    elif args.command == 'train-draft':
        trainDraft()
    elif args.command == 'train-goalies':
        trainGoalies()
    elif args.command == 'draft':
        runDraft()
    elif args.command == 'keeper':
        runKeeper()
    elif args.command == 'spot-check':
        backtest.runSpotChecks(dates=[args.date] if args.date else None, top_n=args.top)
    elif args.command == 'mock-draft':
        runMockDraft(args.year, refresh=args.refresh, team=args.team,
                     all_teams=args.all_teams,
                     exclude_unavailable=args.exclude_unavailable)


if __name__ == "__main__":
    main()
