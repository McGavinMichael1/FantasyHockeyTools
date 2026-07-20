# OPEN QUESTIONS — answers assumed by the skill library

Written 2026-07-05 by the retiring maintainer's skill-library build session (autonomous;
no human was available to answer). Every answer below is a best guess from the repo.
Where a skill depends on one of these, it carries the same `ASSUMED` label.
Confirm or correct these, then update the affected skills and delete the resolved entries.

---

## 1. What is the hardest live problem right now?

**ASSUMED — needs confirmation:** Shipping the **draft analyzer + keeper analyzer before the
October 2026 draft** (Phases B and C of PROJECT-PLAN.md). Evidence: PROJECT-PLAN.md "Current
Phase" says Phase B as of July 3, 2026; PR #2 (baa1ab1, July 5) landed draft-ranker groundwork.
Confidence: high — this is nearly stated outright in the plan.

~~Secondary live problem: the test suite fails on `main`.~~ **RESOLVED July 2026.**
`tests/test_moneypuck.py::test_load_game_logs_filters_season_and_keeps_situations` failed
because commit bb9bf9d (PR #1) added a missing-file guard to `src/moneypuck.py::loadGameLogs`
that ran *before* the cache check, breaking the documented cache contract. The guard now runs
after the cache lookup. The suite is fully green (92 passed).

## 2. What unwritten discipline rules exist?

**ASSUMED — needs confirmation:**
- Never auto-download from MoneyPuck (this one IS written — data-license notice; manual browser
  download only).
- Never commit data files, model binaries, or credentials (`.env`, `oauth2.json`) — enforced by
  `.gitignore`, and `.gitignore` wins over the stale PROJECT-PLAN decision #9 claim that model
  binaries stay committed.
- Don't touch the parked LSTM (`src/models/lstmPickups.py`) before the October draft.
- Update the "Current Phase" section of PROJECT-PLAN.md every working session (stated in the
  July 2026 Learning Log as a lesson, treated here as a rule).
- House style: camelCase function names (`loadGameLogs`, `buildPlayerSeasons`), modules own
  their own IO, comments explain constraints rather than restate code.

## 3. Who is the audience for this library, and what do they NOT know?

**ASSUMED — needs confirmation:** (a) the owner returning after weeks/months away, and
(b) AI coding assistants (Sonnet-class) working in this repo. Neither can be assumed to know:
MoneyPuck's situation-row data model, the league's exact scoring weights, why leakage-safe
season splits are non-negotiable, which caches exist and when they lie, or which battles
(LSTM, label definition, auto-downloader) are already settled.

## 4. What past failures cost the most time?

Evidenced directly in PROJECT-PLAN.md's Learning Log (low risk, barely assumed):
the ML label silently diverging from league scoring (months of training on the wrong target);
the plot-collision bug that destroyed the only record of the old pickup AUC; requirements.txt
drift (streamlit was never installed — the UI skeleton had never run); a `save()` signature
change breaking an untested caller. These drive fht-debugging-playbook and fht-quality-gates.

## 5. What does "beyond state of the art" mean for this project?

**ASSUMED — needs confirmation:** Not academic SOTA. It means: (a) beating the naive baselines
("last season's PPG", "3-season weighted PPG") on Spearman rank correlation for the draft model;
(b) beating the "chase last-10-games fantasy points" baseline on the backtest's top-K hit rate
for pickups; and (c) the mock-draft test — would this board have beaten the owner's actual 2025
draft? Model work that doesn't clear these bars ships the baseline instead.
