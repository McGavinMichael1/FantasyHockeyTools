# Draft ranking explainability + Claude summaries — design

Approved 2026-07-15. Adds per-player explanation, a data-driven confidence score, and a
batch-generated 1–2 sentence Claude summary to the draft rankings, surfaced via an
expandable row in The Rink's Draft board.

## Decisions (settled with owner)

- **Summaries are batch pre-generated** for the top ~200 draftable players before draft
  day — zero latency and zero API dependency during the live draft. Not on-demand.
- **Confidence is data-driven**, computed in Python from model/stats inputs. Not
  LLM-assigned.
- Summaries are **display-only**: they never feed back into rankings or the model.

## Data flow

```
main.py draft ──► draft_rankings.csv            (+ confidence, + 6 SHAP factor columns)
                        │
scripts/build_draft_summaries.py ──► data/processed/draft_summaries.json  (NEW, cached, resumable)
                        │                      │
api_export.py ◄─────────┴──────────────────────┘
     └──► frontend_data.json draft section (+ summary, confidence, factors)
                        └──► DraftBoard.tsx: click row → expandable detail
```

`draft_summaries.json` is the **contract**: any producer that writes
`{playerId: {summary, generated_at, model}}` works (see Producers below).

## 1. Deterministic explanation (computed in `runDraft`)

- **Factors:** XGBoost per-player SHAP contributions via the booster
  (`predict(..., pred_contribs=True)` — native XGBoost, no new dependency). Keep top 3
  positive and top 3 negative contributions with human-readable feature names, written
  into `draft_rankings.csv`.
- **Confidence (0–100):** transparent formula from data depth + stability: seasons of
  history, feature-season GP, age band (peak-age projections more reliable than 19 or
  35+), and |projection − fp_w3| (large deviation = model out on a limb). Weights
  documented in code. Pure function → pytest coverage (repo testing doctrine).

## 2. Summary generation — `scripts/build_draft_summaries.py`

- Reads `draft_rankings.csv`, takes top 200 (`--top N`).
- Per player: one Claude API call — model `claude-opus-4-8`, server tool
  `web_search_20260209` with `max_uses: 3`. Prompt = stats line + projection + SHAP
  factors + confidence; asks for 1–2 sentences reconciling the model's view with
  current context (injury, team/role change); must not restate what the stats say.
- **Resumable cache:** append to `data/processed/draft_summaries.json` after every
  player; re-runs skip existing entries; `--force` regenerates. Gitignored.
- Auth: `ANTHROPIC_API_KEY` from env; fail fast with a clear message if unset.
  Never committed (same treatment as Yahoo creds).
- Cost: ~200 calls ≈ $8–15 per full refresh at Opus 4.8 rates + per-search fees.
  Refreshed rarely (pre-draft, maybe once mid-September).
- New dependency `anthropic`, pinned in pyproject + requirements frozen in the same
  change (repo dependency gate).

### Producers (subscription vs API)

The script requires an API key (pay-as-you-go platform billing — a claude.ai Pro
subscription does not cover SDK/API calls). Because the JSON cache is the contract,
an alternative producer is a Claude Code session (covered by the Pro subscription):
Claude Code reads `draft_rankings.csv`, uses its own web search, and writes the same
`draft_summaries.json` schema, in chunks to respect session limits. Slower and less
repeatable; acceptable for a rare batch. The script remains the canonical producer.

## 3. Export + frontend

- `api_export.build_draft_list`: merge `draft_summaries.json` (absent file → summaries
  omitted, section still exports) and pass through `confidence` + factors.
- `DraftBoard.tsx`: RinkTable-style expandable row (`expandedId` pattern + detail
  styling): summary text, confidence meter (reuse `ScoreMeter`), factor list as ± items
  (red = pushed ranking up, blue = pulled down). Add a compact confidence column to the
  main table.

## 4. Error handling & gates

- Per-player API failure: log, skip, continue; missing summary renders as "—".
- pytest: confidence formula + SHAP factor extraction/naming (pure functions only; no
  tests for the API script per repo doctrine).
- Eyeball gate: spot-check 5 generated summaries against known player situations before
  trusting the batch.

## Out of scope

- On-demand generation, LLM-assigned confidence, feeding summaries back into any model,
  goalie summaries (goalies v1 has no ML rankings).
