import argparse
import json
import os

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

    # VORP before the keeper filter: replacement level is about league-wide
    # talent depth, not about who happens to still be draftable.
    rankings['vorp'] = keeper.vorp_column(rankings)

    # Draft pool must exclude anyone already kept -- keeper lists aren't in the Yahoo
    # API until draft day, so they're maintained manually in data/raw/keepers.csv.
    # Missing/empty file = keepers not announced yet: warn loudly and rank everyone
    # rather than refuse, so pre-draft-day rankings (and the frontend) still work.
    try:
        keeper_names = keepers.loadKeepers()
        before = len(rankings)
        rankings = keepers.filterOutKeepers(rankings, keeper_names)
        print(f"Keepers: removed {before - len(rankings)} of {len(keeper_names)} listed keepers from the pool")
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  No keeper list applied ({e})")
        print("   Rankings include EVERY player. Fine before keepers are announced;")
        print("   on draft day, fill data/raw/keepers.csv and re-run.")

    # VORP is the default cross-position order (owner decision 2026-07-16).
    rankings = rankings.sort_values('vorp', ascending=False)
    out_path = os.path.join('data', 'processed', 'draft_rankings.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rankings.to_csv(out_path, index=False)
    print(f"\nWrote {len(rankings)} players to {out_path}")

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
    rankings = keeper.analyze_keepers(roster, projections)
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


def runMockDraft(year, refresh=False):
    """Replay a past draft with the board making the owner's picks.

    The board is rebuilt from the season BEFORE the draft -- the only data that
    existed on draft day -- and graded on what players actually scored in the
    season they were drafted for.
    """
    warning = mockDraft.leakage_warning(year)
    if warning:
        print(f"\n⚠️  {warning}\n")

    draft_df = yahooAPI.loadDraftResults(year, refresh=refresh)
    my_team_key = mockDraft.owner_team_key(draft_df)
    print(f"Loaded {len(draft_df)} picks from the {year} draft; owner is {my_team_key}")

    # Kept players were never in the pool. Yahoo records them as ordinary picks
    # in whatever round the keeper cost, so they have to be excluded explicitly
    # -- leaving them in is what voided the first 2025 run, where the board
    # drafted eight of other teams' keepers and "won" on the strength of it.
    keeper_names = mockDraft.load_season_keepers(year)
    before = len(draft_df)
    draft_df = draft_df[~draft_df['player_name'].isin(keeper_names)].copy()
    print(f"Keepers: dropped {before - len(draft_df)} of {len(keeper_names)} "
          f"keeper rows from the draft record")

    # Features from the season before the draft; outcomes from the season after.
    # Same display floors as the live board -- otherwise the backtest drafts
    # tiny-sample players the real tool would never have shown, and grades a
    # tool the owner does not have.
    board = applyDisplayFloors(buildFullProjections(feature_season=year - 1))
    # VORP before the keeper filter, matching runDraft: replacement level is
    # about league-wide talent depth, not about who happens to still be free.
    board['vorp'] = keeper.vorp_column(board)
    board = board.dropna(subset=['vorp'])
    board, unmatched_keepers = mockDraft.remove_keepers(board, keeper_names)
    if unmatched_keepers:
        print(f"⚠️  {len(unmatched_keepers)} keepers unmatched on the board and still "
              f"draftable: {unmatched_keepers}")
    print(f"Board rebuilt from season {year - 1}: {len(board)} draftable players")

    resolved = mockDraft.resolve_picks(draft_df, board)
    unmatched = int(resolved['playerId'].isna().sum())
    print(f"Name matching: {len(resolved) - unmatched} of {len(resolved)} picks resolved")

    # Grading ids are resolved separately: a pick the board never had (a rookie
    # off a non-NHL season) still produced, and must not be scored as a zero.
    outcomes = mockDraft.load_outcomes(year)
    resolved = mockDraft.attach_outcome_ids(resolved, outcomes)
    off_board = int(resolved['playerId'].isna().sum() - resolved['outcome_playerId'].isna().sum())
    print(f"Picks with production but no board row: {max(off_board, 0)}")

    replayed = mockDraft.replay(resolved, board, my_team_key)
    result = mockDraft.compare(replayed, outcomes)
    result['meta'] = {
        'draft_year': year,
        'feature_season': year - 1,
        'outcome_season': year,
        'unmatched_picks': unmatched,
        'leakage_warning': warning,
    }

    verdict = result['verdict']
    print(f"\n=== {year} mock draft ===")
    print(f"Actual roster: {verdict['actual_total_fp']:.1f} FP")
    print(f"Board roster:  {verdict['board_total_fp']:.1f} FP")
    print(f"Margin:        {verdict['board_minus_actual']:+.1f} FP "
          f"({'board wins' if verdict['board_wins'] else 'actual draft wins'})")
    print(f"Opponent substitutions forced by the board: {len(result['substitutions'])}")

    print("\n=== Pick by pick ===")
    print(pd.DataFrame(result['head_to_head']).to_string(index=False))

    path = mockDraft.write_report(result, year)
    print(f"\nWrote {path}")
    if warning:
        print("Remember: this run is contaminated. Harness check only.")


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
        runMockDraft(args.year, refresh=args.refresh)


if __name__ == "__main__":
    main()
