# Pre-registration — 2025 mock draft (the one held-out look)

**Written and committed before the run.** Nothing below may be edited after
`main.py mock-draft --year 2025` executes. If the result disappoints and this
document then changes, the exercise was worthless.

## Why this needs a pre-registration at all

The 2025 mock draft **is** the one-time test-2024 confirm. They are not two
separate items, though PROJECT-PLAN and the handoff list them as such. A board
built for the Oct 2025 draft uses season-2024 features graded on season-2025
outcomes — exactly `season.DRAFT_TEST_SEASON = 2024`, the season reserved at
`src/models/draft.py:47`.

Running it spends the only clean look permanently. `fht-quality-gates` §2:
*re-running against the test season to "see how we did" and then tuning against
what you saw burns the one held-out look.*

Leakage status is clean here, and that is the whole reason this year is worth
spending: the shipped model's newest training label is season 2024 (2024-25,
finished April 2025), and the Oct 2025 draft is graded on 2025-26. The model
could not have seen it. **No retrain is needed or permitted before the run** — a
retrain would change what is being tested.

## Primary metric (the verdict)

**Total actual fantasy points of the 18-player roster**, board vs. the owner's
real 2025 draft, with opponents replaying their actual picks.

Agreed with the owner in advance: roster total is the verdict; per-pick
head-to-head is diagnostic colour only.

## Decision rule — committed in advance

| Outcome | Margin (board − actual, as % of actual) | Reading |
|---|---|---|
| **Board wins meaningfully** | **≥ +5%** | The tool adds real draft value. Ship it and trust the board on draft day. |
| Inconclusive | −5% to +5% | The board is roughly a wash with the owner's own judgement. Usable as a reference, not as an authority. Do not claim it beats hand-drafting. |
| **Board loses** | ≤ −5% | The ranking does not survive contact with a real draft. Everything downstream needs rethinking *before* October. |

A loss is a legitimate outcome, not a failure state — the same stance GATE B3
takes when it says shipping Baseline B is legitimate. It is far better to learn
this in July than on draft day.

## Point prediction (so this can be wrong)

I predict the board **wins by roughly +15%** (~+400 to +600 FP on a ~3,400 FP
roster). Reasoning: the owner's real 2025 draft is a human draft with visible
biases, and best-available-by-VORP is a strong strategy against that. I expect a
smaller margin than the 2024 rehearsal's +1,483 FP, because that run was
contaminated — the model had trained on the outcomes it was being graded on.

If the margin lands **above +30%**, I will not celebrate it; I will suspect a
remaining harness artifact, because that is larger than a valuation edge should
plausibly produce.

## Validity gates — check these BEFORE reading the verdict

The 2024 rehearsal found three scoring bugs that all inflated the board's
margin. These gates exist because that is the failure mode with form.

1. **Owner picks unresolved ≤ 2.** Each unresolved owner pick that also has no
   outcome row scores zero and understates the actual roster.
2. **`unmatched_opponent_picks` ≤ 10.** An unresolved opponent pick removes
   nobody from the pool, so that player wrongly stays available to the board.
   This favours the board directly.
3. **Substitutions < 40 (~20% of 180 picks).** Above that, the result is driven
   by the fallback rule for displaced opponents rather than by the board.
4. **Eyeball gate** (`fht-quality-gates` §2: *if the top-20 looks wrong, it is
   wrong*). If the board's roster contains an obvious absurdity — a player who
   did not play, a tiny-sample fluke — debug before believing the number.

If any gate fails, the run is **void for harness reasons**, not evidence either
way. Fix and re-run is permitted in that case: a void run grades a broken
mechanism, not the held-out season.

## Fragility check (diagnostic, not a gate)

Record what share of the 18 individual picks the board won. If the board wins
the roster total but loses a majority of individual picks, the margin rests on
one or two outliers and should be reported as fragile rather than as a clean win.

## What is NOT allowed after the run

- Re-running with different `MAX_BY_POSITION` caps, a different match cutoff, or
  a retrained model to improve the number.
- Reporting the margin without the validity-gate values alongside it.
- Treating a second 2025 run as independent evidence. There is one look.

## Result

*(to be filled in once, immediately after the run, in a separate commit)*
