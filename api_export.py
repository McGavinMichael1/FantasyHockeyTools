#!/usr/bin/env python3
"""Export pickup/cooling data as JSON for the frontend."""

import argparse
import json
import os
import time

import pandas as pd

from src import dataProcessing
from src import fantasyPoints
from src import moneypuck
from src import yahooAPI
from src.features import mlFeatures
from src.features import pickups
from src.models import cooling as coolingModel
from src.models import pickups as pickupModel

CURRENT_SEASON = 2025
OUTPUT_PATH = os.path.join('data', 'processed', 'frontend_data.json')
DRAFT_RANKINGS_PATH = os.path.join('data', 'processed', 'draft_rankings.csv')
DRAFT_SUMMARIES_PATH = os.path.join('data', 'processed', 'draft_summaries.json')
KEEPER_RANKINGS_PATH = os.path.join('data', 'processed', 'keeper_rankings.csv')
KEEPER_SUMMARY_PATH = os.path.join('data', 'processed', 'keeper_summary.json')
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
    return f"https://assets.nhle.com/mugs/nhl/20252026/{player_id}.png"


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
            'confidence': confidence,
            'factors': _parse_factors(row),
            'summary': entry['summary'] if entry else None,
        })
    return draft_list


def _load_keeper_summary() -> dict:
    if not os.path.exists(KEEPER_SUMMARY_PATH):
        return {}
    try:
        with open(KEEPER_SUMMARY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        print(f"Could not read {KEEPER_SUMMARY_PATH} ({e}); exporting keeper rankings without a summary")
        return {}


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
    """Shape cached keeper rankings and their one-time LLM summary for the UI."""
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
    summary_cache = _load_keeper_summary()
    summary = summary_cache.get('summary') if summary_cache.get('season') == season else None
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

    return {
        'season': season,
        'summary': summary,
        'summary_generated_at': summary_cache.get('generated_at') if summary else None,
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

    # Get all player data from NHL API
    allPlayerData = dataProcessing.getAllPlayersWithCache()
    allPlayerData = dataProcessing.flattenPlayerNames(allPlayerData)

    # Get stats
    stats_df = dataProcessing.getAllStatsWithCache(allPlayerData['id'])
    stats_df['fantasyPoints'] = stats_df.apply(
        lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1
    )

    last5_df = dataProcessing.getAllLast5WithCache(allPlayerData['id'])
    last5_df['fantasyPoints'] = last5_df.apply(
        lambda row: fantasyPoints.calculateSkaterPoints(row), axis=1
    )

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
    results = pickups.rankFreeAgents(stats_df, last5_df, allPlayerData, rostered_nhle_ids)

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
        left_on='player_id',
        right_on='playerId',
        how='left'
    )
    combined = combined.dropna(subset=['ml_score'])
    combined['final_score'] = 0.3 * combined['weighted_score_normalized'] + 0.7 * combined['ml_score']

    # Prepare pickup list
    pickup_df = combined.sort_values('final_score', ascending=False).head(50)
    pickup_list = []
    for _, row in pickup_df.iterrows():
        pickup_list.append({
            'id': int(row['player_id']),
            'full_name': row['full_name'],
            'positionCode': row['positionCode'],
            'headshot': get_headshot_url(int(row['player_id'])),
            'sweaterNumber': int(row.get('sweaterNumber', 0)) if not pd.isna(row.get('sweaterNumber')) else 0,
            'gamesPlayed': int(row['gamesPlayed']),
            'goals': int(row['goals_season']),
            'assists': int(row['assists_season']),
            'points': int(row['points_season']),
            'plusMinus': int(row['plusMinus_season']),
            'powerPlayPoints': int(row.get('powerPlayPoints', 0)),
            'shorthandedPoints': int(row.get('shorthandedPoints', 0)),
            'shots': int(row['shots_season']),
            'avgToi': str(row.get('avgToi_season', '0:00')),
            'fantasyPoints': float(row['fantasyPoints_season']),
            'season_ppg': float(row['season_ppg']),
            'last5_goals': int(row['goals_last5']),
            'last5_assists': int(row['assists_last5']),
            'last5_points': int(row['points_last5']),
            'last5_fantasyPoints': float(row['fantasyPoints_last5']),
            'weighted_score': float(row['weighted_score']),
            'ml_score': float(row['ml_score']),
            'final_score': float(row['final_score']),
            'cooling_score': float(row.get('cooling_score', 0)),
            'rostered': False,
        })

    # Prepare cooling list (all players, not just free agents)
    cooling_df = current_players.sort_values('cooling_score', ascending=False).head(50)
    cooling_list = []

    # Need to get stats for cooling players too
    stats_merged = stats_df.merge(
        allPlayerData[['id', 'full_name', 'positionCode', 'sweaterNumber']],
        left_on='player_id',
        right_on='id',
        how='left'
    )
    last5_merged = last5_df.set_index('player_id')

    for _, row in cooling_df.iterrows():
        player_id = int(row['playerId'])
        player_stats = stats_merged[stats_merged['player_id'] == player_id]
        l5 = last5_merged.loc[player_id] if player_id in last5_merged.index else None

        if player_stats.empty:
            continue

        ps = player_stats.iloc[0]
        cooling_list.append({
            'id': player_id,
            'full_name': row.get('full_name', row.get('display_name', 'Unknown')),
            'positionCode': row.get('positionCode', ps.get('positionCode', 'C')),
            'headshot': get_headshot_url(player_id),
            'sweaterNumber': int(ps.get('sweaterNumber', 0)) if not pd.isna(ps.get('sweaterNumber')) else 0,
            'gamesPlayed': int(row['gamesPlayed']),
            'goals': int(ps.get('goals', 0)),
            'assists': int(ps.get('assists', 0)),
            'points': int(ps.get('points', 0)),
            'plusMinus': int(ps.get('plusMinus', 0)),
            'powerPlayPoints': int(ps.get('powerPlayPoints', 0)),
            'shorthandedPoints': int(ps.get('shorthandedPoints', 0)),
            'shots': int(ps.get('shots', 0)),
            'avgToi': str(ps.get('avgToi', '0:00')),
            'fantasyPoints': float(ps.get('fantasyPoints', 0)),
            'season_ppg': float(ps.get('fantasyPoints', 0) / max(1, int(ps.get('gamesPlayed', 1)))),
            'last5_goals': int(l5.get('goals', 0)) if l5 is not None else 0,
            'last5_assists': int(l5.get('assists', 0)) if l5 is not None else 0,
            'last5_points': int(l5.get('points', 0)) if l5 is not None else 0,
            'last5_fantasyPoints': float(l5.get('fantasyPoints', 0)) if l5 is not None else 0,
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
