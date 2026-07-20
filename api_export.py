#!/usr/bin/env python3
"""Export pickup/cooling data as JSON for the frontend."""

import argparse
import json
import os
import time

import pandas as pd

from src import dataProcessing
from src import moneypuck
from src import season
from src import yahooAPI
from src.features import mlFeatures
from src.features import pickups
from src.models import cooling as coolingModel
from src.models import pickups as pickupModel

CURRENT_SEASON = season.CURRENT_SEASON
OUTPUT_PATH = os.path.join('data', 'processed', 'frontend_data.json')
DRAFT_RANKINGS_PATH = os.path.join('data', 'processed', 'draft_rankings.csv')
DRAFT_SUMMARIES_PATH = os.path.join('data', 'processed', 'draft_summaries.json')
KEEPER_RANKINGS_PATH = os.path.join('data', 'processed', 'keeper_rankings.csv')
KEEPER_ADVISOR_CONTEXT_PATH = os.path.join(
    'data', 'processed', 'keeper_advisor_context.json')
FACTOR_COLS = [f'factor_{i}' for i in range(1, 7)]


def _load_draft_summaries() -> dict:
    """Load the {playerId: {summary, generated_at, model}} cache, or {} if the
    file is missing/corrupt. Absence is normal -- summaries are optional and
    batch-generated separately (scripts/build_draft_summaries.py)."""
    if not os.path.exists(DRAFT_SUMMARIES_PATH):
        return {}
    try:
        with open(DRAFT_SUMMARIES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        print(f"⚠️  Could not read {DRAFT_SUMMARIES_PATH} ({e}); exporting without summaries")
        return {}


def _parse_factors(row) -> list:
    """Parse the factor_1..factor_6 JSON cells into [{label, value}], skipping
    empty/malformed slots (pandas reads an unused slot as NaN). The sign of
    value encodes direction, so the frontend colours by sign."""
    factors = []
    for col in FACTOR_COLS:
        if col not in row.index:
            continue
        cell = row[col]
        if isinstance(cell, str) and cell:
            try:
                obj = json.loads(cell)
                factors.append({'label': obj['label'],
                                'value': round(float(obj['value']), 3)})
            except (ValueError, KeyError, TypeError):
                pass
    return factors


def get_headshot_url(player_id: int) -> str:
    """NHL headshot URL for a player."""
    return (f"https://assets.nhle.com/mugs/nhl/"
            f"{season.nhl_season_id(CURRENT_SEASON)}/{player_id}.png")


def _format_toi(seconds) -> str:
    """Mean icetime in seconds -> 'MM:SS' for display."""
    if pd.isna(seconds):
        return '0:00'
    minutes, secs = divmod(int(round(float(seconds))), 60)
    return f"{minutes}:{secs:02d}"


def latestGameState():
    """Most recent game-state row per current-season player with >= 20 GP."""
    cache_file = os.path.join('data', 'processed', 'current_players_features.csv')

    if os.path.exists(cache_file):
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 24:
            print(f"Loading cached current player features ({age_hours:.1f}h old)")
            return pd.read_csv(cache_file)

    print("Computing current player features...")
    df = mlFeatures.loadMoneyPuckData()
    df = mlFeatures.buildRollingFeatures(df)
    current_df = df[df['season'] == CURRENT_SEASON].copy()
    games_played = current_df.groupby('playerId').size().reset_index(name='gamesPlayed')
    current_players = current_df.groupby('playerId').last().reset_index()
    current_players = current_players.merge(games_played, on='playerId')
    current_players = current_players[current_players['gamesPlayed'] >= 20]

    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    current_players.to_csv(cache_file, index=False)
    return current_players


def build_draft_list():
    """Draft rankings from `python main.py draft`'s CSV (the single computation
    path for draft projections -- this only reshapes it for the frontend).
    Returns [] if the CSV hasn't been built, so pickup/cooling export still works."""
    if not os.path.exists(DRAFT_RANKINGS_PATH):
        print(f"{DRAFT_RANKINGS_PATH} not found -- run 'python main.py draft' "
              "to include draft rankings; skipping draft section")
        return []

    df = pd.read_csv(DRAFT_RANKINGS_PATH)
    summaries = _load_draft_summaries()
    # Guard the explainability columns: a draft_rankings.csv written before
    # they existed should still export rather than crash.
    has_confidence = 'confidence' in df.columns
    draft_list = []
    for _, row in df.iterrows():
        player_id = int(row['playerId'])
        entry = summaries.get(str(player_id))
        confidence = None
        if has_confidence and not pd.isna(row['confidence']):
            confidence = int(row['confidence'])
        draft_list.append({
            'id': player_id,
            'full_name': row['full_name'],
            'positionCode': row['position'],
            'headshot': get_headshot_url(player_id),
            'age': round(float(row['age']), 1) if not pd.isna(row['age']) else None,
            'gamesPlayed': int(row['gamesPlayed']),
            'last_fpPerGame': round(float(row['fpPerGame']), 3),
            'projected_fpPerGame': round(float(row['projected_fpPerGame']), 3),
            'projected_total': round(float(row['projected_total']), 1),
            'delta_vs_last': round(float(row['delta_vs_last']), 3),
            'vorp': (round(float(row['vorp']), 1)
                     if 'vorp' in df.columns and not pd.isna(row['vorp']) else None),
            'projected_gp': (round(float(row['projected_gp']), 1)
                             if 'projected_gp' in df.columns and not pd.isna(row['projected_gp']) else None),
            'confidence': confidence,
            'factors': _parse_factors(row),
            'summary': entry['summary'] if entry else None,
        })
    return draft_list


def _load_keeper_advisor_metadata() -> dict:
    if not os.path.exists(KEEPER_ADVISOR_CONTEXT_PATH):
        return {}
    try:
        with open(KEEPER_ADVISOR_CONTEXT_PATH, 'r', encoding='utf-8') as file:
            context = json.load(file)
    except (OSError, ValueError) as error:
        print(f"Could not read {KEEPER_ADVISOR_CONTEXT_PATH} ({error}); "
              "exporting keeper rankings without advisor chat")
        return {}
    if context.get('schema_version') != 1 or not isinstance(context.get('context_id'), str):
        return {}
    return {
        'schema_version': context['schema_version'],
        'context_id': context['context_id'],
        'generated_at': context.get('generated_at'),
        'season': str(context.get('season', '')),
    }


def _optional_number(row, column, digits=None):
    value = row.get(column)
    if pd.isna(value):
        return None
    value = float(value)
    return round(value, digits) if digits is not None else value


def _optional_int(row, column):
    value = _optional_number(row, column)
    return int(value) if value is not None else None


def build_keeper_section():
    """Shape cached keeper rankings and advisor-chat readiness for the UI."""
    if not os.path.exists(KEEPER_RANKINGS_PATH):
        print(f"{KEEPER_RANKINGS_PATH} not found -- run 'python main.py keeper' first")
        return None

    rankings = pd.read_csv(KEEPER_RANKINGS_PATH)
    if 'is_recommended' not in rankings.columns:
        return None
    recommendations = rankings[
        rankings['is_recommended'].astype(str).str.lower() == 'true'
    ].sort_values('keeper_rank')
    if recommendations.empty:
        return None

    season = str(recommendations.iloc[0].get('target_season', ''))
    keeper_list = []
    for _, row in recommendations.iterrows():
        player_id = _optional_int(row, 'playerId')
        keeper_list.append({
            'id': player_id,
            'full_name': row['full_name'],
            'positionCode': row['position'],
            'headshot': get_headshot_url(player_id) if player_id is not None else None,
            'keeper_rank': _optional_int(row, 'keeper_rank'),
            'assigned_round': _optional_int(row, 'assigned_round'),
            'pick_cost': _optional_number(row, 'pick_cost', 1),
            'raw_keeper_value': _optional_number(row, 'raw_keeper_value', 1),
            'net_keeper_value': _optional_number(row, 'net_keeper_value', 1),
            'last_fpPerGame': _optional_number(row, 'fpPerGame', 3),
            'gamesPlayed': _optional_int(row, 'gamesPlayed'),
            'projected_fpPerGame': _optional_number(row, 'projected_fpPerGame', 3),
            'projected_total': _optional_number(row, 'projected_total', 1),
            'confidence': _optional_int(row, 'confidence'),
        })

    advisor_roster = []
    for _, row in rankings.iterrows():
        name = next(
            (str(row[column]) for column in ("full_name", "yahoo_name")
             if column in rankings.columns and pd.notna(row.get(column))
             and str(row.get(column)).strip()),
            "Unknown roster player",
        )
        advisor_roster.append({
            'player_id': _optional_int(row, 'playerId'),
            'name': name,
        })

    advisor = _load_keeper_advisor_metadata()
    advisor_ready = advisor.get('season') == season

    return {
        'season': season,
        'advisor_ready': advisor_ready,
        'advisor_context_id': advisor.get('context_id') if advisor_ready else None,
        'advisor_generated_at': advisor.get('generated_at') if advisor_ready else None,
        'advisor_roster': advisor_roster,
        'recommendations': keeper_list,
    }


def export_keeper_only():
    """Update only the cached keeper block without refreshing live player data."""
    output = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
                output = json.load(f)
        except (ValueError, OSError):
            output = {}

    output.setdefault('pickups', [])
    output.setdefault('cooling', [])
    output.setdefault('draft', [])
    output['keeper'] = build_keeper_section()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    print(f"Exported cached keeper data to {OUTPUT_PATH}")


def export_data():
    """Generate JSON data for frontend consumption."""
    moneypuck.checkCurrentFreshness()

    # Identity/roster only -- the sole remaining NHL API use in this path
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)

    # Heuristic stats from MoneyPuck (full league scoring incl. hits/blocks)
    game_df = moneypuck.loadGameLogs(min_season=2020)
    pickup_stats = moneypuck.buildPickupStats(game_df, CURRENT_SEASON)

    # Get rostered players (optional)
    rostered_nhle_ids = set()
    try:
        lg = yahooAPI.getLeague()
        rostered_names = yahooAPI.getRosteredIds(lg)
        rostered_nhle_ids = yahooAPI.getRosteredNHLIds(rostered_names, allPlayerData)
        print(f"Yahoo API: Filtering out {len(rostered_nhle_ids)} rostered players")
    except FileNotFoundError as e:
        print(f"Yahoo API disabled: {e}")
    except Exception as e:
        print(f"Yahoo API error: {e}")

    # Heuristic ranking
    results = pickups.rankFreeAgents(pickup_stats, allPlayerData, rostered_nhle_ids)

    # ML predictions. Models regress next-5-game FP/g; convert to 0-1
    # percentile ranks so the blend and frontend score bars keep a bounded
    # scale. Low predicted FP/g = cooling down, so the cooling score is
    # inverted (higher = stronger drop candidate, as before).
    current_players = latestGameState()
    current_players['ml_score'] = pickupModel.predict(current_players).rank(pct=True)
    current_players['cooling_score'] = 1 - coolingModel.predict(current_players).rank(pct=True)
    current_players = current_players.merge(
        allPlayerData[['id', 'full_name', 'positionCode', 'sweaterNumber']],
        left_on='playerId',
        right_on='id',
        how='left'
    )
    current_players['display_name'] = current_players['full_name'].fillna(current_players['name'])

    # Combine heuristic + ML for pickups
    results['weighted_score_normalized'] = (
        (results['weighted_score'] - results['weighted_score'].min())
        / (results['weighted_score'].max() - results['weighted_score'].min())
    )
    combined = results.merge(
        current_players[['playerId', 'ml_score', 'cooling_score']],
        on='playerId',
        how='left'
    )
    combined = combined.dropna(subset=['ml_score'])
    combined['final_score'] = 0.3 * combined['weighted_score_normalized'] + 0.7 * combined['ml_score']

    # Prepare pickup list
    pickup_df = combined.sort_values('final_score', ascending=False).head(50)
    pickup_list = []
    for _, row in pickup_df.iterrows():
        pickup_list.append({
            'id': int(row['playerId']),
            'full_name': row['full_name'],
            'positionCode': row['positionCode'],
            'headshot': get_headshot_url(int(row['playerId'])),
            'sweaterNumber': int(row['sweaterNumber']) if not pd.isna(row.get('sweaterNumber')) else 0,
            'gamesPlayed': int(row['gamesPlayed']),
            'goals': int(round(row['goals'])),
            'assists': int(round(row['assists'])),
            'points': int(round(row['points'])),
            'powerPlayPoints': int(round(row['powerPlayPoints'])),
            'shorthandedPoints': int(round(row['shorthandedPoints'])),
            'shots': int(round(row['shots'])),
            'avgToi': _format_toi(row['avgToiSeconds']),
            'fantasyPoints': float(row['fantasyPoints']),
            'season_ppg': float(row['season_ppg']),
            'last5_goals': int(round(row['last5_goals'])),
            'last5_assists': int(round(row['last5_assists'])),
            'last5_points': int(round(row['last5_points'])),
            'last5_fantasyPoints': float(row['last5_fantasyPoints']),
            'weighted_score': float(row['weighted_score']),
            'ml_score': float(row['ml_score']),
            'final_score': float(row['final_score']),
            'cooling_score': float(row.get('cooling_score', 0)),
            'rostered': False,
        })

    # Prepare cooling list (all players, not just free agents)
    cooling_df = current_players.sort_values('cooling_score', ascending=False).head(50)
    cooling_list = []

    # Need to get stats for cooling players too -- pickup_stats covers ALL
    # current-season players (rostered included), unlike the filtered ranker output.
    stats_lookup = pickup_stats.merge(
        allPlayerData[['id', 'full_name', 'positionCode', 'sweaterNumber']],
        left_on='playerId', right_on='id', how='left'
    ).set_index('playerId')

    for _, row in cooling_df.iterrows():
        player_id = int(row['playerId'])
        if player_id not in stats_lookup.index:
            continue
        ps = stats_lookup.loc[player_id]
        cooling_list.append({
            'id': player_id,
            'full_name': row.get('full_name') if not pd.isna(row.get('full_name')) else ps['name'],
            'positionCode': row.get('positionCode') if not pd.isna(row.get('positionCode')) else ps['position'],
            'headshot': get_headshot_url(player_id),
            'sweaterNumber': int(ps['sweaterNumber']) if not pd.isna(ps.get('sweaterNumber')) else 0,
            'gamesPlayed': int(row['gamesPlayed']),
            'goals': int(round(ps['goals'])),
            'assists': int(round(ps['assists'])),
            'points': int(round(ps['points'])),
            'powerPlayPoints': int(round(ps['powerPlayPoints'])),
            'shorthandedPoints': int(round(ps['shorthandedPoints'])),
            'shots': int(round(ps['shots'])),
            'avgToi': _format_toi(ps['avgToiSeconds']),
            'fantasyPoints': float(ps['fantasyPoints']),
            'season_ppg': float(ps['season_ppg']),
            'last5_goals': int(round(ps['last5_goals'])),
            'last5_assists': int(round(ps['last5_assists'])),
            'last5_points': int(round(ps['last5_points'])),
            'last5_fantasyPoints': float(ps['last5_fantasyPoints']),
            'weighted_score': 0,
            'ml_score': float(row.get('ml_score', 0)),
            'final_score': 0,
            'cooling_score': float(row['cooling_score']),
            'rostered': player_id in rostered_nhle_ids,
        })

    draft_list = build_draft_list()

    # Write output
    output = {
        'pickups': pickup_list,
        'cooling': cooling_list,
        'draft': draft_list,
        'keeper': build_keeper_section(),
        'generated_at': pd.Timestamp.now().isoformat(),
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nExported {len(pickup_list)} pickups, {len(cooling_list)} cooling candidates, "
          f"and {len(draft_list)} draft rankings")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export data for the frontend.')
    parser.add_argument(
        '--keeper-only', action='store_true',
        help='export cached keeper data without refreshing pickup or cooling data',
    )
    args = parser.parse_args()
    if args.keeper_only:
        export_keeper_only()
    else:
        export_data()
