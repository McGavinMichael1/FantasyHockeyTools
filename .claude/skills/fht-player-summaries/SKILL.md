---
name: fht-player-summaries
description: Use when generating, re-running, or refreshing the Claude draft player summaries (draft_summaries.json), choosing between the in-session and API producer paths, pushing new summaries to the frontend (api_export.py / frontend_data.json), or when summaries on the draft board look stale, missing, mojibake'd, or wrongly formatted.
---

# fht-player-summaries

Producer runbook for the Claude draft summaries. Facts verified 2026-07-15 by
actually running both the prompt build and a top-5 in-session refresh end to
end on this machine. Summaries are **display-only** — they never feed back into
rankings or models (`scripts/build_draft_summaries.py` docstring).

## 1. The contract

`data/processed/draft_summaries.json` (gitignored) is the interface. Any
producer that writes this shape works; `api_export.py::_load_draft_summaries`
is the only consumer:

```json
{"<playerId>": {"summary": "3-4 sentences", "generated_at": "<iso8601 UTC>", "model": "<producer>"}}
```

- Keys are **string** playerIds (`str(int(row['playerId']))`).
- `model` provenance convention: the API script writes the bare model id
  (`claude-opus-4-8`); in-session generation writes
  `"<model-id> (claude-code session)"` — keep this so cache entries are
  auditable.
- Write UTF-8, `ensure_ascii=False`, `indent=2` (match `_save_cache`).
- Absence of the file is legal — export prints a note and ships
  `summary: null`.

## 2. Choosing a producer path

| Path | When | Cost |
|---|---|---|
| **In-session** (Claude Code does the searches + writes JSON) | Small batches (top 5-20), owner's default — Pro subscription, no API billing | $0 |
| **API script** `scripts/build_draft_summaries.py` | Full 150-200 player refresh, requires `ANTHROPIC_API_KEY` (pay-as-you-go; Pro does NOT cover API) | Token cost varies; search caps at 5 for the top 50, then 3 (up to 700 searches for 200 players, or ~$7) |
| **Batch API** | **Rejected 2026-07-15, don't relitigate**: search fees get no batch discount, `pause_turn` results need resubmission rounds, batches throttle search-heavy orgs — saves <$13/refresh you do twice a season | — |

## 3. In-session runbook (the proven path)

**Step 1 — dump the canonical prompts.** Never hand-write them; drift from the
script's `_build_prompt` is the failure mode this step exists to prevent.
Write a scratchpad `.py` (NOT PowerShell `python -c` — PS 5.1 mangles the
embedded quotes, verified failure):

```python
import sys
sys.path.insert(0, r'd:\repos\FantasyHockeyTools\scripts')
sys.path.insert(0, r'd:\repos\FantasyHockeyTools')
import pandas as pd
import build_draft_summaries as bds

df = (pd.read_csv(bds.RANKINGS_PATH)
      .sort_values('projected_fpPerGame', ascending=False).head(200))
ctx = bds._load_season_context(bds.PLAYER_SEASONS_PATH)
label = bds._upcoming_season_label(ctx)
df['pos_rank'] = (df.groupby('position')['projected_fpPerGame']
                    .rank(ascending=False, method='first'))
df['pos_count'] = df.groupby('position')['playerId'].transform('count')
for rank in range(5):                       # whatever slice you're refreshing
    row = df.iloc[rank]
    print(bds._build_prompt(row, ctx.get(int(row['playerId'])), label,
                            bds._search_budget(rank)))
```

**Step 2 — research each player** with web search, honoring the script's tier
(rank < 50 → up to 5 searches, else 3). Prioritize what the prompt asks for:
injury/trade/coach/contract news and PP1-vs-PP2 role.

**Step 3 — write summaries to the prompt's output contract**: 3-4 sentences,
reconcile the model's projection with the news, note whether the PP role is
stable/improved/at-risk, do not restate the stat block.

**Step 4 — merge into the cache** with a scratchpad script that loads the
existing JSON, sets only the refreshed playerIds, and rewrites UTF-8
`ensure_ascii=False, indent=2` — this preserves other entries, matching the
API script's `--force` semantics.

**Step 5 — push to the frontend**:

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe api_export.py
```

Needs `models/{pickups,cooling}/model.pkl` (see `fht-operations` if missing).
The Next.js app reads `data/processed/frontend_data.json` per request
(`frontend/src/app/api/players/route.ts`) — no rebuild needed.

**Step 6 — verify**: load `frontend_data.json`, confirm each refreshed
playerId's `summary` contains a marker phrase unique to the new content (a
team/coach name from your research). `with summary: N` should equal the cache
size.

## 4. API script runbook

```powershell
$env:PYTHONUTF8='1'; $env:ANTHROPIC_API_KEY='...'
.\.venv\Scripts\python.exe scripts/build_draft_summaries.py --top 200
```

**Cost/latency knobs, in order of leverage** (each run prints measured
tokens/searches and an estimated `$` total):

| Knob | Why it matters |
|---|---|
| `EFFORT` | The big lever. Opus 4.8 **defaults to `high`** — tuned for long agentic coding, not a 110-word summary. Unset, it drove 5-search deep dives and 12-50 min turns on news-heavy players. Now `'medium'`; drop to `'low'` if still slow. |
| `MODEL` | `claude-sonnet-5` is ~2x faster and ~40% the token cost; fine for news summaries. |
| `MAX_TOKENS` | A **ceiling, not a reservation** — unused headroom is free. Raising it never costs money; hitting it throws away everything already paid for. Was 4096 (truncated news-heavy players), now 16000. |

Requires the `anthropic` package (pinned in pyproject, already installed).
Resumable: cached playerIds are skipped, cache written after every player.
`--force` regenerates the `--top` slice in place and preserves entries outside
it (wipe bug fixed 2026-07-15, verified by behavioral test). Prompt enrichment
reads `data/processed/player_seasons.csv` (soft dependency — warns and
degrades to a stats-light prompt if absent; rebuild via
`scripts/build_player_seasons.py`). The top 50 projected players get up to 5
targeted searches; the rest get 3 (`_search_budget`). Every request has a
4,096-token ceiling.

The Claude called by this script **cannot see `.claude/skills/*`** — it
receives only the request payload (`_build_prompt` + the web_search tool).
This skill is for the agent operating the pipeline; the summary-writing
instructions live in `_build_prompt`, the single source of truth both producer
paths share. For a scripted run that DOES load this skill, use headless Claude
Code on the subscription instead (in-session path, $0):

```powershell
claude -p "Use the fht-player-summaries skill to refresh draft summaries for the top 10 players and update the frontend" --permission-mode acceptEdits
```

## 5. Traps

- **Re-running specific players from the API script** — `--force --top N`
  regenerates the whole top-N slice (entries outside it are safe since the
  2026-07-15 wipe fix). For a handful of arbitrary mid-list players, delete
  just their keys from the JSON and re-run without `--force`, or use the
  in-session merge pattern (step 4 above).
- **`$env:PYTHONUTF8='1'` on every run** — player names are non-ASCII;
  cp1252 consoles crash or mangle (known repo issue, CLAUDE.md).
- **Mojibake in PowerShell output is usually display-only** — PS 5.1
  `Get-Content` defaults to ANSI; the file on disk is fine UTF-8. Inspect JSON
  with a Python scratch script, not `Get-Content`.
- **The season anchor is derived, not hardcoded** — `_upcoming_season_label`
  = latest `player_seasons` season + 1. A stale `player_seasons.csv` after
  rollover makes prompts name the wrong season; rebuild it first.
- **"It looks hung" / slow, expensive, news-heavy players** — root-caused
  2026-07-15: per-player wall time scales with **news volume**, because
  unset `EFFORT` left Opus 4.8 at its `high` default. Measured spread on an
  identical task: 0.9 min (quiet: Matthews, Makar) → 12.5 min (trade sagas:
  Rantanen, Guentzel, Forsberg) → Eichel never finishing. Diagnose from
  outside via `draft_summaries.json`'s mtime (written after every player):
  >10 min stale with a live process = one player over-researching. Fix is
  `EFFORT`/`MODEL` (table above), not a bigger timeout.
- **Never let a failure be silent about spend** — searches and thinking are
  billed even when no summary comes back, so every failure path names its
  `stop_reason` and the searches spent. A truncated turn (`max_tokens`) is
  the expensive one: it pays for the whole research turn and discards it.
  Failures are never cached, so a re-run retries them.
- **The script prints `[rank N/M] Name...` before each call** and streams the
  response, so the connection stays active while server-side tools run. SDK
  auto-retries are disabled (`max_retries=0`): after an ambiguous network
  drop, re-run manually rather than risk a duplicated billable request.
- **Longer summaries are expected** — 3-4 sentences (~700 chars) since
  2026-07-15; a mix of short and long entries means part of the cache predates
  the prompt change — regenerate the short ones.

## When NOT to use this skill

- Running/retraining models, cache mechanics, env setup → `fht-operations`.
- Draft rankings pipeline itself (`main.py draft`, features, model) →
  `fht-draft-campaign`.
- What MoneyPuck/PP columns mean → `fht-domain-reference`.
- Claude API syntax/pricing in general → the `claude-api` skill.

## Provenance and maintenance

- `grep -n "DEEP_SEARCH\|MAX_TOKENS\|max_uses\|3-4 short" scripts/build_draft_summaries.py`
  — search tiers, token ceiling, and sentence cap still as documented.
- `grep -n "_load_draft_summaries\|summary" api_export.py` — consumer contract
  unchanged.
- Prompt shape drifts with `_build_prompt` — re-dump one prompt (step 3.1)
  before a big refresh rather than trusting this file.
- Cost figures date to 2026-07-15 pricing (Opus 4.8 $5/$25 per MTok, search
  $10/1k); re-check the `claude-api` skill before quoting them.
