r"""Batch-generate 1-2 sentence Claude summaries for the top draftable players.

Reads data/processed/draft_rankings.csv (built by `python main.py draft`), takes
the top N by projected FP/game, and for each player makes one Claude API call
(model claude-opus-4-8) with web search enabled to reconcile the model's
projection with current real-world context (injury, trade, line/role change).
Writes data/processed/draft_summaries.json:

    {playerId: {"summary": str, "generated_at": iso8601, "model": str}}

That JSON cache is the CONTRACT (see docs/superpowers/specs/): any producer that
writes this shape works, and api_export.py reads it. This script is the
canonical producer -- it is resumable (skips playerIds already cached) and
--force regenerates.

Summaries are display-only: they never feed back into the rankings or the model.

Requires ANTHROPIC_API_KEY (pay-as-you-go platform billing -- a claude.ai Pro
subscription does NOT cover API/SDK calls). Fails fast if unset. Never commit
the key (same treatment as Yahoo creds).

    $env:ANTHROPIC_API_KEY = '...'
    .\.venv\Scripts\python.exe scripts/build_draft_summaries.py --top 200

Cost: ~200 calls ~= $8-15 per full refresh at Opus 4.8 rates + per-search fees.
Refresh rarely (pre-draft, maybe once mid-September).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402

MODEL = 'claude-opus-4-8'
RANKINGS_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'draft_rankings.csv')
SUMMARIES_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'draft_summaries.json')
FACTOR_COLS = [f'factor_{i}' for i in range(1, 7)]


def _load_cache(path: str) -> dict:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _factor_phrases(row) -> str:
    """The row's SHAP factors as 'Label (+0.42)' phrases for the prompt."""
    phrases = []
    for col in FACTOR_COLS:
        cell = row.get(col)
        if isinstance(cell, str) and cell:
            try:
                obj = json.loads(cell)
                sign = '+' if obj['value'] >= 0 else '-'
                phrases.append(f"{obj['label']} ({sign}{abs(obj['value']):.2f})")
            except (ValueError, KeyError, TypeError):
                pass
    return '; '.join(phrases) if phrases else 'n/a'


def _build_prompt(row) -> str:
    return (
        "You are helping with a fantasy hockey draft. A machine-learning model "
        "projects next-season performance for this NHL skater:\n\n"
        f"Player: {row['full_name']} ({row['position']}), age {float(row['age']):.0f}\n"
        f"Last season: {float(row['fpPerGame']):.2f} fantasy points per game "
        f"over {int(row['gamesPlayed'])} games\n"
        f"Model projection: {float(row['projected_fpPerGame']):.2f} FP/game next "
        f"season (change of {float(row['delta_vs_last']):+.2f})\n"
        f"Model confidence: {row.get('confidence')}/100\n"
        f"Top model factors (SHAP): {_factor_phrases(row)}\n\n"
        "Search the web for this player's CURRENT situation heading into the "
        "upcoming season -- injuries, trades, line/role or team changes, "
        "contract or coaching news. Then write 1-2 sentences that reconcile the "
        "model's projection with that current context, for a fantasy manager "
        "deciding whether to draft him. Do NOT simply restate the stats above "
        "(the manager can already see them); add the real-world context the "
        "model cannot know. Respond with ONLY the 1-2 sentence summary, no preamble."
    )


def _summarize(client, row) -> str:
    """One Claude call with server-side web search. Returns the summary text."""
    messages = [{'role': 'user', 'content': _build_prompt(row)}]
    tools = [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 3}]
    resp = None
    for _ in range(4):
        resp = client.messages.create(
            model=MODEL, max_tokens=1024,
            thinking={'type': 'adaptive'},
            tools=tools, messages=messages,
        )
        # The server-side search loop can hit its iteration limit; re-send to
        # resume where it left off (no extra user turn -- the API detects the
        # trailing server_tool_use block).
        if resp.stop_reason == 'pause_turn':
            messages.append({'role': 'assistant', 'content': resp.content})
            continue
        break
    return ''.join(b.text for b in resp.content if b.type == 'text').strip()


def main():
    parser = argparse.ArgumentParser(
        description='Batch-generate Claude draft summaries.')
    parser.add_argument('--top', type=int, default=200,
                        help='number of top-projected players to summarize')
    parser.add_argument('--force', action='store_true',
                        help='regenerate summaries even if already cached')
    args = parser.parse_args()

    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit("ANTHROPIC_API_KEY not set. Export it first (pay-as-you-go API "
                 "billing; a claude.ai Pro subscription does not cover API calls).")
    if not os.path.exists(RANKINGS_PATH):
        sys.exit(f"{RANKINGS_PATH} not found -- run "
                 r"'.\.venv\Scripts\python.exe main.py draft' first.")

    import anthropic
    client = anthropic.Anthropic()

    df = (pd.read_csv(RANKINGS_PATH)
          .sort_values('projected_fpPerGame', ascending=False)
          .head(args.top))
    cache = {} if args.force else _load_cache(SUMMARIES_PATH)

    done, failed = 0, 0
    for _, row in df.iterrows():
        pid = str(int(row['playerId']))
        if pid in cache and not args.force:
            continue
        try:
            summary = _summarize(client, row)
            if not summary:
                raise ValueError('empty response')
            cache[pid] = {
                'summary': summary,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'model': MODEL,
            }
            _save_cache(SUMMARIES_PATH, cache)  # write after each player: resumable
            done += 1
            print(f"[{done}] {row['full_name']}: {summary}")
        except Exception as e:  # per-player failure: log, skip, continue
            failed += 1
            print(f"FAILED {row['full_name']} ({pid}): {e}", file=sys.stderr)

    print(f"\nDone: {done} generated, {failed} failed, {len(cache)} total in cache.")


if __name__ == '__main__':
    main()
