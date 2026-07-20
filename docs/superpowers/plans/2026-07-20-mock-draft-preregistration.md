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

## ⛔ RESULT VOID — keepers were never excluded from the pool

**Do not cite the +29.3% figure below. It is an artifact, not a finding.**

Caught by the owner on 2026-07-20, reading the board's roster: *"was that with
Nikita Kucherov taken first overall? The active draft at the time had Kucherov
and others as kept players."* Correct.

In a keeper league, Yahoo records each kept player as a "pick" in the round the
keeper cost. The 2025 draft results place Makar at pick 172, Draisaitl 174,
McDavid 175, MacKinnon 176, Kucherov 177 — rounds 15-18, i.e.
`keeper.KEEPER_ROUNDS`. The real round 1 opens Hedman, Hutson, Fox precisely
because every superstar was already kept and was **never in the draft pool**.

`replay()` treated those players as available from pick 1, so the board drafted
eight players who belonged to other teams before the draft began. The margin
measures that, and nothing else.

**Why the validity gates missed it:** gate 4 (eyeball) should have caught it. A
board roster of McDavid + MacKinnon + Kucherov + Makar + Draisaitl looks
*plausible* in isolation — every player is real and productive — so it passed a
check aimed at absurd players rather than at absurd *availability*. The gate was
looking for the wrong kind of wrong.

**The held-out look is NOT spent.** Per the protocol above, a run failing a
validity gate is "void for harness reasons, not evidence either way", and fix-
and-re-run is permitted: a void run grades a broken mechanism, not the season.
That is what happened, and it is the second time the pre-registration's own rules
have done real work.

Yahoo exposes no `is_keeper` flag (verified against the raw payload: draft_result
records carry only pick, round, team_key, player_key), so keeper identification
has to be inferred. Rounds 15-18 hold exactly 40 picks — 10 teams x 4 keepers —
but across only 8 teams (one with 9, one with 7, two with none), which implies
traded picks mixed in with keepers. **Resolving that is the blocker before any
re-run.**

---

## Superseded result — run 2026-07-20, code at commit `6298898` (VOID, see above)

**The board wins by +1,071.2 FP (+29.3%).** Above the pre-registered +5% bar by
a wide margin.

| | Total actual FP |
|---|---|
| Owner's real 2025 draft | 3,656.6 |
| Board (best-available by VORP) | 4,727.8 |
| **Margin** | **+1,071.2 (+29.3%)** |

`leakage_warning: None` — this is the clean year, as designed.

### Validity gates — all four pass, checked before the verdict was read

| Gate | Threshold | Actual |
|---|---|---|
| Owner picks with no outcome row | ≤ 2 | **0 of 18** |
| `unmatched_opponent_picks` | ≤ 10 | **5** |
| Substitutions | < 40 | **24** |
| Eyeball | no absurdities | Board roster is McDavid, MacKinnon, Kucherov, Makar, Draisaitl, Pastrnak, Kaprizov, Vasilevskiy… all plausible |

### Fragility check

The board won **12 of 18** individual picks. The margin is broad-based, not one
or two outliers — so it is not the fragile kind of win.

### My point prediction was wrong

I predicted ~+15% (+400 to +600 FP). The actual margin is roughly double that.
Recording this because a pre-registration that only ever confirms the author is
worthless.

### Disclosed artifact — the margin is overstated by ~4 points

I pre-registered that a margin above +30% should make me suspect a harness
artifact rather than celebrate. At +29.3% that trigger effectively fired, so I
went looking, and found one.

**Players the owner really drafted are never removed from the pool** (`replay()`
adds the board's choice to `taken` but not the owner's actual pick). In the
counterfactual those picks never happen, so the player is genuinely free — but
no opponent takes him either, because opponents replay their actual picks. He
therefore floats down to the board for free. The board re-drafted **Adam Fox**
at pick 78, whom the owner had really taken at pick 3.

Scope: exactly one of 18 board picks, worth 155.7 FP.

**Corrected margin: +915.5 FP (+25.0%).** Still far above the +5% bar, so the
verdict is unchanged. Every correction here moves against the board, which is
why the conclusion survives.

**Per this document, 2025 is not re-run.** The four gates passed, so the run is
not void; re-running to collect a cleaner number would be a second look at a
season that gets exactly one. The artifact is fixed for future seasons in a
follow-up commit, and the result above stands as produced by `6298898`.

### Verdict

The draft board beats hand-drafting by a wide, broad-based margin on the one
honest test available. **Trust the board on draft day.** The live draft-day mode
is worth having, and the remaining pre-draft work (summaries, keeper filtering)
is worth doing on top of a ranking that has now earned it.
