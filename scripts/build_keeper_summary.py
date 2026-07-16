"""Create one cached explanation for this season's four keeper recommendations.

Run ``main.py keeper`` first. Once a summary exists for the target season, this
script reuses it and makes no further LLM calls until the following season.
"""

import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402


MODEL = os.environ.get('KEEPER_LLM_MODEL', 'claude-haiku-4-5-20251001')
RANKINGS_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'keeper_rankings.csv')
SUMMARY_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'keeper_summary.json')


def cache_is_current(cache: dict, season: str) -> bool:
    return cache.get('season') == season and bool(cache.get('summary'))


def _factor_text(row: dict) -> str:
    factors = []
    for number in range(1, 7):
        cell = row.get(f'factor_{number}')
        if not isinstance(cell, str) or not cell:
            continue
        try:
            factor = json.loads(cell)
            factors.append(f"{factor['label']} ({float(factor['value']):+.2f})")
        except (TypeError, ValueError, KeyError):
            continue
    return '; '.join(factors) or 'not available'


def build_prompt(season: str, candidates: list[dict]) -> str:
    player_lines = []
    for candidate in candidates:
        player_lines.append(
            f"#{int(candidate['keeper_rank'])}: {candidate['full_name']} "
            f"({candidate['position']})\n"
            f"- Last season: {float(candidate['fpPerGame']):.2f} FP/game in "
            f"{int(candidate['gamesPlayed'])} games\n"
            f"- Draft model: {float(candidate['projected_fpPerGame']):.2f} FP/game, "
            f"{float(candidate['projected_total']):.1f} projected points, "
            f"confidence {int(candidate['confidence'])}/100\n"
            f"- Keeper value: {float(candidate['raw_keeper_value']):.1f} above "
            f"position replacement; costs round {int(candidate['assigned_round'])} "
            f"({float(candidate['pick_cost']):.1f} projected points); net keeper value "
            f"{float(candidate['net_keeper_value']):.1f}\n"
            f"- Model factors: {_factor_text(candidate)}"
        )

    return (
        f"You are advising a fantasy hockey manager in a four-keeper league for "
        f"{season}. Keepers cost the manager's final four draft picks, assigned "
        f"from round 18 through round 15. These are the model's recommended skater "
        f"keepers, ranked by keeper value:\n\n"
        + '\n\n'.join(player_lines)
        + "\n\nWrite one concise paragraph (80-120 words) explaining why these are "
        "the strongest players to keep. Ground it in the model projection, prior "
        "production, replacement value, and cheap round cost. Do not mention goalies, "
        "invent facts, or add a heading."
    )


def _load_cache() -> dict:
    if not os.path.exists(SUMMARY_PATH):
        return {}
    with open(SUMMARY_PATH, 'r', encoding='utf-8') as file:
        return json.load(file)


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(SUMMARY_PATH, 'w', encoding='utf-8') as file:
        json.dump(cache, file, indent=2, ensure_ascii=False)


def main() -> None:
    if not os.path.exists(RANKINGS_PATH):
        sys.exit(f"{RANKINGS_PATH} not found -- run main.py keeper first.")

    rankings = pd.read_csv(RANKINGS_PATH)
    candidates = rankings[rankings['is_recommended'].astype(str).str.lower() == 'true']
    candidates = candidates.sort_values('keeper_rank')
    if candidates.empty:
        sys.exit('No matched keeper recommendations found in keeper_rankings.csv.')

    season = str(candidates.iloc[0]['target_season'])
    cache = _load_cache()
    if cache_is_current(cache, season):
        print(f"Using cached keeper summary for {season}; no LLM request made.")
        return

    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('ANTHROPIC_API_KEY not set. Add it before generating the one-time keeper summary.')

    import anthropic

    response = anthropic.Anthropic().messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{'role': 'user', 'content': build_prompt(season, candidates.to_dict('records'))}],
    )
    summary = ''.join(block.text for block in response.content if block.type == 'text').strip()
    if not summary:
        sys.exit('LLM returned an empty keeper summary.')

    _save_cache({
        'season': season,
        'candidate_ids': [int(player_id) for player_id in candidates['playerId']],
        'summary': summary,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'model': MODEL,
    })
    print(f"Saved keeper summary for {season} to {SUMMARY_PATH}")


if __name__ == '__main__':
    main()
