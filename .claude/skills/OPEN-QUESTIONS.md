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

## 1b. What do keepers cost? — RESOLVED 2026-07-20 (owner)

**The rule: keeping a player costs you your final 4 picks — whichever picks those happen to be.**
Owner-stated twice on 2026-07-20: *"The final 4 picks of every team are always the kept players"*
and *"keepers are always final 4 picks you hold."*

It is **not** a fixed round. Rounds 15-18 are only what "your last four picks" resolves to in a
draft where nobody has traded picks.

Verified against the 2025 record: `derive_keepers()` in `src/mockDraft.py` implements the rule as
each team's last four picks by **pick number** and reproduces the owner's stated keepers exactly
(Swayman p70, Michkov p71, Johnston p78, Stützle p90), plus all 40 league-wide — including Auston
Matthews at round 10, which no round-based rule would have found.

### Consequence for the shipped keeper analyzer — NOT yet fixed

`src/keeper.py` hardcodes `KEEPER_ROUNDS = (18, 17, 16, 15)` and `round_pick_costs()` prices a
keeper as the mean projected value of the board slice in those rounds (picks 141-180). That is
correct **only when you actually hold your rounds 15-18 picks.**

The owner traded late picks away in 2025 and held only rounds 1-9, so his final four picks were
overall **70, 71, 78 and 90** — far more valuable slots than 141-180. Measured against the
current 774-player board:

| | Modelled cost (rounds 15-18) | Real cost (picks 70/71/78/90) |
|---|---|---|
| Four keepers | 722.4 projected FP | 898.3 projected FP |

**A 175.9 FP understatement — 24%, or ~44 FP per keeper.** `net_keeper_value` is overstated by
that much whenever late picks have been traded away, which can flip a marginal keep/don't-keep
call.

### What a fix needs

Keeper cost should come from the picks the owner **actually holds**, not an assumed round range.
Pick ownership before draft day is not currently fetched from Yahoo, so the practical shape is
probably a configurable "my final four pick numbers" input, defaulting to rounds 15-18 for an
untraded draft.

`KEEPER_ROUNDS` is a fine *default*; the bug is that it is an assumption presented as a rule. Any
fix touches keeper math — `fht-quality-gates` class (a), highest bar.

<details>
<summary>Original investigation (superseded by the owner's answer)</summary>

**This one affects a shipped tool, not just docs.** `src/keeper.py` hardcodes
`KEEPER_ROUNDS = (18, 17, 16, 15)`, and `round_pick_costs()` prices a keeper by averaging the
projected value of the picks in those rounds. CLAUDE.md records the rule as owner-confirmed.

Evidence from the 2025 draft record says it is at least not the whole story:

- Six of ten teams show a textbook pattern: exactly one pick in each of rounds 15, 16, 17, 18
  (t.1, t.2, t.3, t.4, t.6, t.8), and those picks are stars — Makar, Kucherov, McDavid,
  MacKinnon, Draisaitl, B. Tkachuk. Clearly keepers.
- Four teams do not. t.10 has nine picks in rounds 15-18, t.7 has seven, and **t.5 and t.9 (the
  owner's own team) have none at all.**
- Auston Matthews sits at **round 10** for t.5 — too good to be a genuine round-10 pick if the
  pool were full.
- The owner, asked directly on 2026-07-20, said t.5 and t.9 did keep players and they are
  "recorded elsewhere" — i.e. keeper cost varies by player rather than being fixed at 15-18.
- Every team holds exactly 18 picks, but clustered: t.9 holds only rounds 1-9, t.10 only rounds
  10-18. So picks were traded wholesale between early and late.

**Why it matters:** if keeper cost is not a fixed round, `round_pick_costs()` is pricing keepers
against the wrong baseline, and `net_keeper_value` on the shipped keeper board is off by
whatever the difference is. The mock-draft backtest now sidesteps this by reading an explicit
per-season keeper list (`data/raw/keepers_{year}.csv`), but the keeper analyzer does not.

**Do not "fix" `KEEPER_ROUNDS` on the strength of this.** It needs the owner to state the actual
rule. It is equally possible the rule changed between seasons, or that Yahoo's recording differs
from the league's stated cost.

*Resolution: the owner stated the rule — final 4 picks you hold. The "keeper cost varies by
player" reading above was wrong; it varies by which picks you hold, which is why traded picks
made it look irregular.*

</details>

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
