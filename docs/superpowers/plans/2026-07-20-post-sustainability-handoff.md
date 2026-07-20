# Handoff — post-sustainability pass (2026-07-20)

For a fresh Claude session picking this repo up. Everything here was verified against
merged `main` (`0abf3dc`) on 2026-07-20.

**Read first, don't duplicate:** `CLAUDE.md`, then the skill matching your task
(`.claude/skills/fht-*`), then PROJECT-PLAN.md's *Current Phase*. This document only
covers what those don't: what just changed, what to do next, and what a fresh session
is likely to get wrong.

---

## Where things stand

PR #12 merged (squashed as `0abf3dc`): an offseason sustainability pass. Four tools ship
today — pickup analyzer, draft board, goalie ranker, keeper analyzer + advisor chat.

Verified state on `main` right now:

| Check | Value |
|---|---|
| `pytest -q` | **97 passed, 0 failed** |
| `data/processed/` | 61 MB (was ~620 MB) |
| `draft_rankings.csv` | 774 players |
| `draft_summaries.json` | **50** players have summaries |
| `data/raw/keepers.csv` | **missing** (expected — keepers aren't announced yet) |
| `.github/workflows/` | **does not exist** — no CI |
| Advisor context | 18 roster players → 3,060 scenario sets, 3.9 MB |

What the pass changed, in one line each: NHL API calls can no longer hang (timeouts +
resumable checkpointing); `src/season.py` owns every season constant; torch/streamlit are
out of a base install; game-log caches are Parquet; both long-standing test failures are
fixed.

**The green suite is the important part.** It was 65 passed / 2 failed for months, so a
failure meant nothing. It now means something — treat any red as a real regression.

---

## The decision you're facing

The draft is **~October 2026**. Milestones in PROJECT-PLAN say M2 Aug 23, M3 Sept 6,
M4 (draft-ready) Sept 20. That's roughly two months of runway, and the infra debt is
now cleared, so this is the moment to spend it on draft value rather than plumbing.

**Ask the owner what they want to prioritize before starting anything large.** The list
below is ordered by my read of leverage, not by their stated preference — they have not
picked yet.

---

## Recommended next steps

### 1. Add CI (small, now unblocked)

`.github/workflows/` doesn't exist. A green baseline is the prerequisite for CI being
worth anything, and that prerequisite is now met.

```yaml
# pytest + (cd frontend && npm run typecheck && npm run test:unit)
```

**Landmine:** model `.pkl` files are gitignored, so CI cannot run anything that needs a
trained model without retraining first. Scope CI to the tests that don't (all 97 current
tests pass without models — verified). Don't try to train in CI.

### 2. Mock-draft backtest (PROJECT-PLAN Phase D)

*"Would this board have beaten my actual 2025 draft?"* This is the only honest end-to-end
validation of the draft tool, and it's still unchecked. Highest confidence-per-hour before
the draft. If the board loses to the owner's real draft, everything downstream needs
rethinking — better to learn that in July than in October.

### 3. The one-time test-2024 confirm (B4 remainder)

Deliberate, irreversible: it burns the only held-out look at 2024. Read
`fht-quality-gates` before touching it, and **do not do this casually or as a side effect
of other work.** Get explicit owner sign-off. Once spent, it's gone.

### 4. Finish the draft summaries (B5 remainder)

50 of 774 players have summaries. The target is the top ~200 before draft day. See
`fht-player-summaries` for the two producer paths — the owner has API billing *and* Pro,
so both work. Resumable; run in chunks. Then re-run `api_export.py`.

> PROJECT-PLAN's B5 remainder line says *"Only 5 of 704 players"* — that's stale on both
> numbers. It's 50 of 774. Worth correcting when you're next in that file.

### 5. Live draft-day assistant (biggest product win)

The board is static. Add "mark drafted" so VORP recomputes against the *remaining* pool
and positional runs surface. Reuses `keeper.vorp_column` wholesale. This is the feature
that actually helps on draft day, and it needs to exist *before* draft day, not during.

### 6. Deferred Tier 2 items

- **Advisor context scaling.** `_scenario_sets` materializes every C(n,4) combination:
  3,060 sets / 3.9 MB at 18 roster players, 12,650 at 25, 27,405 at 30. Separately,
  `loadAdvisorContext` re-reads and re-validates that whole file on *every* chat POST.
  Fine at 18; degrades badly past ~25. Not urgent unless the roster grows.
- **Orchestration smoke tests** for `main.py draft`/`keeper` and `api_export` against small
  fixtures. The Learning Log records a signature-drift bug that one smoke test would have
  caught.
- **Structured run logs** → `reports/metrics.jsonl`. Model metrics currently survive only
  in stdout and overwritable PNGs; a plot-collision incident already destroyed one AUC
  record.

### 7. Open modelling questions (Phase E, post-draft)

Both were raised by the owner and both are **empirical, not matters of taste** — settle
them with `backtest.py`, not intuition:

- **How long to wait after the season starts before running pickups?** There's already an
  implicit gate: `latestGameState` filters to `gamesPlayed >= 20`, roughly mid-November.
  So the tool is already quiet early, just not deliberately. Replay Oct/Nov as-of dates
  and find where top-15 hit rate crosses the ~32% baseline.
- **Is the 5-game label window right?** Short = fitting noise, long = missing the pickup
  window. Set in one place (`mlFeatures.buildLabel`). Sweep 3/5/7/10 and compare on the
  **product metric** (spot-check top-K hit rate), not Spearman. Changes the label, so it
  needs a full retrain plus a pre-registered prediction per `fht-quality-gates`.

---

## Landmines for a fresh session

**Season constants.** `src/season.py` is now the only place `CURRENT_SEASON` is defined.
Do not reintroduce literals. `tests/test_season.py` pins the derived split boundaries
against what the shipped models actually trained on — if you change them, that's a
deliberate rollover, not a cleanup.

**`backtest.KNOWN_PICKUPS` does not roll.** It's hand-curated for 2025-26 and can't be
derived. A rollover that forgets it makes the "known gems" report silently meaningless.

**Parquet caches are gitignored** (`data/**/*.parquet`). If you add a new cache path,
check `git status` is clean afterwards — an untracked 100 MB file is one `git add -A` away
from a very bad commit.

**torch is not installed.** `src/models/lstmPickups.py` and `src/features/lstmFeatures.py`
import it at module level and will `ImportError` on a base install. That's expected — the
LSTM is parked. `uv pip install -e ".[lstm]"` if you genuinely need it, which you almost
certainly don't.

**`api_export.py` was never run end-to-end** in the sustainability pass — Yahoo OAuth can
block on stdin non-interactively (see the Windows liveness notes). The headshot-URL change
is verified by test and directly, but that export path itself is unexercised since the
refactor. Run it manually before trusting the frontend after any change to it.

**MoneyPuck stale-CSV warnings are expected noise** June→October. Don't chase them.

---

## Don't relitigate these

`fht-architecture-contract` has the full list with citations. The ones most likely to
tempt a fresh session:

- MoneyPuck is the single stats source; the NHL API is identity/roster only.
- **There is no auto-downloader by design** — MoneyPuck requires a data license for
  scrapers. Do not "helpfully" add one.
- One scoring source per stat type (`SKATER_WEIGHTS` / `GOALIE_WEIGHTS`).
- Splits are season-based, never random rows.
- Draft target is next-season FP **per game**, not totals.
- The LSTM stays parked until after draft season.

---

## Not in the repo: the owner wants to productize this eventually

Stated 2026-07-20. It's recorded in session memory but deliberately **not** in the
codebase, because it isn't a current constraint.

If it comes up: **the blocker is data licensing, not architecture.** MoneyPuck requires a
license for automated access, and redistributing derived MoneyPuck data in a paid product
is a conversation to have with them *first* — it can invalidate the whole data strategy,
and no refactor fixes it. NHL and Yahoo APIs carry commercial restrictions too.

Architecturally the tool is single-tenant by construction: league rules are hardcoded
constants in `src/keeper.py` (10 teams, 4 keepers, rounds 15–18), scoring weights are
module constants, models are trained for *this* league's scoring, and state is files on
one disk read directly by the Next route. Each is a real project, not a refactor.

**Owner's decision: keep productization a separate, later track.** Don't let it pull scope
into draft-season work.

---

## Stale docs worth fixing in passing

- PROJECT-PLAN milestone **M4** still says *"Draft-day Streamlit board"* — `ui/` was
  deleted; the Next.js frontend is the only UI.
- PROJECT-PLAN **B5 remainder**: "5 of 704" → actually 50 of 774.
- `fht-draft-campaign` still describes a Streamlit draft board as the Phase D target and
  cites the old "48 passed, 2 failed" counts in a couple of places.
