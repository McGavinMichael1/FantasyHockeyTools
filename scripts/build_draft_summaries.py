r"""Batch-generate 3-4 sentence Claude summaries for the top draftable players.

Reads data/processed/draft_rankings.csv (built by `python main.py draft`), takes
the top N by projected FP/game, and for each player makes one Claude API call
(model claude-opus-4-8) with web search enabled to reconcile the model's
projection with current real-world context (injury, trade, line/role change).
The prompt is enriched with last-season production, power-play usage, and a
3-season GP/FPpg trend from data/processed/player_seasons.csv (optional --
summaries degrade gracefully without it), plus league scoring weights
(fantasyPoints.SKATER_WEIGHTS), positional rank within the projection set, and
a date/season anchor so web searches target fresh news. The top 50 players get
up to five targeted web searches; the rest get three.
Writes data/processed/draft_summaries.json:

    {playerId: {"summary": str, "generated_at": iso8601, "model": str}}

That JSON cache is the CONTRACT (see docs/superpowers/specs/): any producer that
writes this shape works, and api_export.py reads it. This script is the
canonical producer -- it is resumable (skips playerIds already cached), and
--force regenerates the --top slice in place while preserving cached entries
outside it.

Summaries are display-only: they never feed back into the rankings or the model.

Requires ANTHROPIC_API_KEY (pay-as-you-go platform billing -- a claude.ai Pro
subscription does NOT cover API/SDK calls). Fails fast if unset. Never commit
the key (same treatment as Yahoo creds).

    $env:ANTHROPIC_API_KEY = '...'
    .\.venv\Scripts\python.exe scripts/build_draft_summaries.py --top 200

Cost: token usage varies with Claude's adaptive thinking. Web search costs $10
per 1,000 searches, capped at 5 searches for the top 50 and 3 for the rest
(at most 700 searches, or about $7, for a 200-player refresh). Each run prints
its own measured token/search totals and an estimated dollar cost at the end.
Refresh rarely (pre-draft, maybe once mid-September).

Tuning knobs if runs are slow or expensive: EFFORT (the big lever -- Opus 4.8
defaults to 'high', which over-researches a short summary) and MODEL. MAX_TOKENS
is a ceiling, not a reservation: raising it costs nothing and prevents paying
for a truncated turn that gets discarded.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pandas as pd  # noqa: E402

from src.fantasyPoints import SKATER_WEIGHTS  # noqa: E402

MODEL = 'claude-opus-4-8'
RANKINGS_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'draft_rankings.csv')
SUMMARIES_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'draft_summaries.json')
PLAYER_SEASONS_PATH = os.path.join(REPO_ROOT, 'data', 'processed', 'player_seasons.csv')
FACTOR_COLS = [f'factor_{i}' for i in range(1, 7)]
STANDARD_SEARCH_USES = 3
DEEP_SEARCH_USES = 5
DEEP_SEARCH_TOP_N = 50
# Output ceiling per request. This is a CAP, not a reservation -- unused
# headroom costs nothing, and hitting the cap throws away everything already
# paid for (thinking + searches), so keep it generous. 4096 truncated
# news-heavy players mid-turn.
MAX_TOKENS = 16000
# Opus 4.8 defaults to effort='high', which suits long agentic coding, not a
# 110-word news summary: it drove 5-search deep dives and 12-50 minute turns.
# Lower effort => fewer, more-consolidated tool calls and less thinking spend.
EFFORT = 'medium'
MAX_CONTINUATIONS = 3
WEIGHTS_LINE = ', '.join(f'{stat}={w}' for stat, w in SKATER_WEIGHTS.items())
# A search-limit fallback is Claude reporting that its OWN web-search tooling
# failed; it is never hockey content. Match that conjunction -- a tool mention
# AND a failure report -- rather than one transcript's wording. Three phrasings
# of this same failure reached the cache on 2026-07-15 ("wasn't able to
# complete this request reliably", "unable to complete the web research",
# "unable to complete live web searches") and literal markers caught only one.
# The conjunction matters: "unable to complete" alone is ordinary injury prose
# ("unable to complete the season"), and _build_prompt forbids mentioning the
# search process at all, so a tool mention in output is itself the anomaly.
SEARCH_TOOL_MENTION = re.compile(
    r'web[- ]?search|search tool|web research|web searches')
SEARCH_FAILURE_MENTION = re.compile(
    r'usage limit|hard limit|rate limit|limit .{0,15}exceeded|exceeded'
    r'|no results|no readable results|unable to|not able to|hit its limit')
# Raw API error string -- not prose, so it needs no conjunction.
SEARCH_LIMIT_ERROR = 'max_uses_exceeded'


def _load_cache(path: str) -> dict:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_cache(path: str, cache: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _load_season_context(path: str) -> dict:
    """{playerId: DataFrame of that player's last <=3 seasons}, {} if absent.

    player_seasons.csv is a gitignored build artifact (scripts/build_player_seasons.py);
    when missing, summaries still generate -- just without the production/PP/trend lines.
    """
    if not os.path.exists(path):
        print(f"WARNING: {path} not found -- prompts will omit production/PP "
              "usage context. Run scripts/build_player_seasons.py to enable it.",
              file=sys.stderr)
        return {}
    seasons = pd.read_csv(path)
    recent = seasons.sort_values('season').groupby('playerId').tail(3)
    return {int(pid): g for pid, g in recent.groupby('playerId')}


def _fmt_season(start_year: int) -> str:
    """2026 -> '2026-27' (MoneyPuck season ints are the start year)."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _upcoming_season_label(season_ctx: dict) -> str:
    """The season the model projects: latest data season + 1 (e.g. '2026-27')."""
    if season_ctx:
        start = max(int(g['season'].max()) for g in season_ctx.values()) + 1
    else:  # fallback: NHL seasons start in October, so July+ means this year
        now = datetime.now()
        start = now.year if now.month >= 7 else now.year - 1
    return _fmt_season(start)


def _season_stat_lines(group) -> str:
    """Trend + production + PP-usage prompt lines from a player's recent
    player_seasons rows ('' if none)."""
    if group is None or len(group) == 0:
        return ''
    lines = ''
    if len(group) >= 2:
        trend = '; '.join(
            f"{_fmt_season(int(r['season']))}: {int(r['gamesPlayed'])} GP, "
            f"{r['fpPerGame']:.2f} FP/g"
            for _, r in group.iterrows())
        lines += f"Recent seasons: {trend}\n"
    latest = group.iloc[-1]
    goals = latest['totalGoals']
    assists = latest['totalPrimaryAssists'] + latest['totalSecondaryAssists']
    lines += (
        f"Production (last season): {goals:.0f}G / {assists:.0f}A, "
        f"{latest['totalShotsOnGoal']:.0f} shots, {latest['totalHits']:.0f} hits, "
        f"{latest['totalShotsBlocked']:.0f} blocks, "
        f"{latest['avgIcetime'] / 60:.1f} min/game icetime\n"
        f"Power play: {latest['totalPPP']:.0f} PP points "
        f"({latest['totalPPGoals']:.0f}G/{latest['totalPPAssists']:.0f}A)"
    )
    # PP share of fantasy value -- same fantasy-unit formula as the model's
    # PP_share feature (src/features/draft.py).
    if latest['totalFP'] > 0:
        pp_share = (latest['totalPPGoals'] * 3 + latest['totalPPAssists'] * 2
                    + latest['totalPPP'] * 1) / latest['totalFP']
        lines += f" -- {pp_share:.0%} of his fantasy value came on the power play"
    lines += (
        f"; {latest['totalSHP']:.0f} shorthanded points\n"
        f"Shooting luck: {goals:.0f} goals vs {latest['totalXGoals']:.1f} expected "
        f"({latest['xGoalsSurplus']:+.1f}; positive = ran hot, regression risk)\n"
    )
    return lines


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


# Block types that mark server-side tool activity in a response. Text emitted
# before the last of these is the model narrating its plan, not its answer.
TOOL_BLOCK_TYPES = frozenset({
    'server_tool_use', 'web_search_tool_result', 'tool_use', 'tool_result',
})


def _final_text(content) -> str:
    """The model's answer: the text blocks after the last server-tool block.

    With web search enabled, a response interleaves narration and tool
    activity -- text("I'll search for X...") -> server_tool_use ->
    web_search_tool_result -> text(the actual summary). Joining *every* text
    block staples the pre-search narration onto the front of the answer; that
    produced 16 of 18 contaminated cache entries on 2026-07-15, recognisable
    by the missing space where two blocks abut ("...2026-27 season.Suzuki is
    locked in..."). When no tool block is present (no search ran), every text
    block is part of the answer.
    """
    last_tool = -1
    for i, block in enumerate(content):
        if getattr(block, 'type', None) in TOOL_BLOCK_TYPES:
            last_tool = i
    return ''.join(b.text for b in content[last_tool + 1:]
                   if getattr(b, 'type', None) == 'text').strip()


def _is_usable_summary(summary: str) -> bool:
    """Reject a model-generated fallback when its web-search budget was exhausted."""
    normalized = ' '.join(summary.lower().split())
    if not normalized:
        return False
    if SEARCH_LIMIT_ERROR in normalized:
        return False
    return not (SEARCH_TOOL_MENTION.search(normalized)
                and SEARCH_FAILURE_MENTION.search(normalized))


def _search_budget(rank: int) -> int:
    """Searches allowed for a zero-indexed projection rank."""
    return DEEP_SEARCH_USES if rank < DEEP_SEARCH_TOP_N else STANDARD_SEARCH_USES


def _build_prompt(row, season_group, season_label: str,
                  max_uses: int = STANDARD_SEARCH_USES) -> str:
    pos_rank_line = ''
    if 'pos_rank' in row.index and pd.notna(row['pos_rank']):
        pos_rank_line = (
            f"Position rank: #{int(row['pos_rank'])} of {int(row['pos_count'])} "
            f"{row['position']} in this projection set\n")
    return (
        f"You are helping with a fantasy hockey draft ahead of the {season_label} "
        f"NHL season (today is {datetime.now():%B %d, %Y}).\n"
        f"League scoring weights: {WEIGHTS_LINE}.\n"
        "A machine-learning model projects next-season performance for this NHL "
        "skater:\n\n"
        f"Player: {row['full_name']} ({row['position']}), age {float(row['age']):.0f}\n"
        f"{pos_rank_line}"
        f"Last season: {float(row['fpPerGame']):.2f} fantasy points per game "
        f"over {int(row['gamesPlayed'])} games\n"
        f"{_season_stat_lines(season_group)}"
        f"Model projection: {float(row['projected_fpPerGame']):.2f} FP/game next "
        f"season (change of {float(row['delta_vs_last']):+.2f})\n"
        f"Model confidence: {row.get('confidence')}/100\n"
        f"Top model factors (SHAP): {_factor_phrases(row)}\n\n"
        f"Use no more than {max_uses} targeted web searches for this player's CURRENT "
        f"situation heading into the {season_label} season. Prioritize material "
        "injury, transaction, coaching, or power-play-role news; if there is no "
        "verified change, treat the role as stable rather than researching every "
        "category. Then write 3-4 short sentences (110 words maximum) that "
        "reconcile the model's projection with that current context for a fantasy "
        "manager. Do NOT restate the stats above or mention the search process. "
        "Do not invent unverified news. Respond with ONLY the summary, no preamble."
    )


def _summarize(client, row, season_group, season_label: str, max_uses: int):
    """One Claude call with server-side web search.

    Returns (summary_text, usage_totals). Every failure path names the
    stop_reason: spend is real whether or not a summary comes back, so a
    failure must say what consumed it.
    """
    messages = [{'role': 'user',
                 'content': _build_prompt(row, season_group, season_label, max_uses)}]
    tools = [{'type': 'web_search_20260209', 'name': 'web_search',
              'max_uses': max_uses}]
    totals = {'input': 0, 'output': 0, 'searches': 0}
    resp = None
    for attempt in range(MAX_CONTINUATIONS + 1):
        # Streaming keeps the HTTP connection active while Claude searches and
        # thinks. It avoids the ambiguous idle-connection failures of the
        # non-streaming endpoint for long server-tool requests.
        with client.messages.stream(
            model=MODEL, max_tokens=MAX_TOKENS,
            thinking={'type': 'adaptive', 'display': 'omitted'},
            output_config={'effort': EFFORT},
            tools=tools, messages=messages,
        ) as stream:
            resp = stream.get_final_message()
        totals['input'] += resp.usage.input_tokens
        totals['output'] += resp.usage.output_tokens
        server_use = getattr(resp.usage, 'server_tool_use', None)
        if server_use is not None:
            totals['searches'] += getattr(server_use, 'web_search_requests', 0) or 0
        # The server-side search loop can hit its iteration limit; re-send to
        # resume where it left off (no extra user turn -- the API detects the
        # trailing server_tool_use block).
        if resp.stop_reason == 'pause_turn':
            if attempt == MAX_CONTINUATIONS:
                raise RuntimeError(
                    f"still searching after {MAX_CONTINUATIONS} resumptions "
                    f"({totals['searches']} searches spent)")
            print("    ...long search turn, resuming", flush=True)
            messages.append({'role': 'assistant', 'content': resp.content})
            continue
        break
    if resp.stop_reason == 'max_tokens':
        raise RuntimeError(
            f"hit the {MAX_TOKENS}-token output ceiling before writing the "
            f"summary ({totals['output']} output tokens, "
            f"{totals['searches']} searches spent) -- raise MAX_TOKENS or "
            f"lower EFFORT")
    if resp.stop_reason == 'refusal':
        raise RuntimeError('model declined this request (stop_reason=refusal)')
    summary = _final_text(resp.content)
    if not summary:
        raise ValueError(f'no text returned (stop_reason={resp.stop_reason}, '
                         f"{totals['searches']} searches spent)")
    if not _is_usable_summary(summary):
        raise ValueError('Claude returned a web-search-limit fallback; not saving it')
    return summary, totals


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
    # The resumable cache makes an explicit re-run safer than an automatic
    # retry after an ambiguous network drop, which can otherwise duplicate a
    # completed, billable request with no response delivered to this process.
    client = anthropic.Anthropic(timeout=300.0, max_retries=0)

    df = (pd.read_csv(RANKINGS_PATH)
          .sort_values('projected_fpPerGame', ascending=False)
          .head(args.top))
    season_ctx = _load_season_context(PLAYER_SEASONS_PATH)
    season_label = _upcoming_season_label(season_ctx)
    df['pos_rank'] = (df.groupby('position')['projected_fpPerGame']
                        .rank(ascending=False, method='first'))
    df['pos_count'] = df.groupby('position')['playerId'].transform('count')
    # Always load the existing cache: --force regenerates the --top slice in
    # place but must never discard entries outside it (e.g. --force --top 5
    # against a 200-entry cache keeps the other 195).
    cache = _load_cache(SUMMARIES_PATH)

    done, failed = 0, 0
    spend = {'input': 0, 'output': 0, 'searches': 0}
    for rank, (_, row) in enumerate(df.iterrows()):
        pid = str(int(row['playerId']))
        if pid in cache and not args.force:
            continue
        max_uses = _search_budget(rank)
        # Liveness line BEFORE the call -- a player can legitimately take
        # minutes of silence; this makes "working on X" vs "hung" observable.
        print(f"[rank {rank + 1}/{len(df)}] {row['full_name']} "
              f"(searches<={max_uses})...", flush=True)
        try:
            summary, used = _summarize(client, row,
                                       season_ctx.get(int(row['playerId'])),
                                       season_label, max_uses)
            for k in spend:
                spend[k] += used[k]
            cache[pid] = {
                'summary': summary,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'model': MODEL,
            }
            _save_cache(SUMMARIES_PATH, cache)  # write after each player: resumable
            done += 1
            print(f"[{done}] {row['full_name']} "
                  f"({used['searches']} searches, {used['output']} out): "
                  f"{summary}", flush=True)
        except Exception as e:  # per-player failure: log, skip, continue
            failed += 1
            print(f"FAILED {row['full_name']} ({pid}): {e}", file=sys.stderr)

    cost = (spend['input'] / 1e6 * 5 + spend['output'] / 1e6 * 25
            + spend['searches'] / 1000 * 10)
    print(f"\nDone: {done} generated, {failed} failed, {len(cache)} total in cache.")
    print(f"Spend this run: {spend['input']:,} in + {spend['output']:,} out "
          f"tokens, {spend['searches']} searches ~= ${cost:.2f} "
          f"(successful players only; failures also billed)")


if __name__ == '__main__':
    main()
