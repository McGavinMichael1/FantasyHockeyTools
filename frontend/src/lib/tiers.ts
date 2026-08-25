import type { DraftPlayer, Position } from '@/types/player';
import { REPLACEMENT_RANKS, remaining } from './liveDraft';

/**
 * Tier breaks: where the board falls off a cliff.
 *
 * A ranked list is a continuous sort, which is the wrong shape for the decision
 * actually being made. "Three players left in this tier" tells you whether to
 * take one now or wait a round; "he is ranked 41st" does not.
 *
 * ## This is a DISPLAY HEURISTIC, not a model output
 *
 * Nothing here is fitted, validated, or gated. It clusters the projections the
 * model already produced by looking for unusually large gaps -- no more. It must
 * never be presented as a projection, and it must never feed one. The repo's
 * gate discipline (`fht-quality-gates`) exists precisely so that a plausible
 * heuristic cannot quietly acquire the authority of a measured result.
 *
 * ## The rule
 *
 * Within a position, over the players still available: a new tier opens wherever
 * the gap to the next player exceeds `TIER_GAP_MULTIPLIER` times the median gap.
 * Adaptive rather than a fixed fantasy-point threshold, so it means the same
 * thing for goalies as for centres and does not need retuning when scoring or
 * projections shift.
 */

/** How much bigger than a typical gap a gap must be to count as a cliff. */
export const TIER_GAP_MULTIPLIER = 1.6;

/**
 * Below this many players a position is a single tier.
 *
 * A median gap off one or two observations is not a median, and late in a draft
 * tiers have stopped mattering anyway. A confident-looking break drawn from a
 * single gap would be noise wearing a number.
 */
export const MIN_FOR_TIERING = 3;

export interface TierInfo {
  /** 1-based tier within the player's own position. */
  tier: number;
  /** How many players are still available in that tier, this one included. */
  remainingInTier: number;
}

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

/**
 * Tier assignments for every player still on the board.
 *
 * Drafted players are absent from the result: they have no tier because they
 * are not in the pool the tiers describe.
 */
export function tiers(
  players: DraftPlayer[],
  drafted: ReadonlySet<number>,
  ranks: Record<Position, number> = REPLACEMENT_RANKS,
): Map<number, TierInfo> {
  const byPosition = new Map<Position, DraftPlayer[]>();
  for (const player of remaining(players, drafted)) {
    const group = byPosition.get(player.positionCode) ?? [];
    group.push(player);
    byPosition.set(player.positionCode, group);
  }

  const result = new Map<number, TierInfo>();

  for (const [position, group] of byPosition) {
    const sorted = [...group].sort((a, b) => b.projected_total - a.projected_total);
    const gaps = sorted
      .slice(1)
      .map((player, i) => sorted[i].projected_total - player.projected_total);

    // The median is taken over the startable region only, so a long tail of
    // marginal players cannot drag the typical gap down and manufacture cliffs
    // at the top of the board.
    const startable = Math.min(ranks[position] ?? sorted.length, sorted.length);
    const threshold =
      sorted.length < MIN_FOR_TIERING
        ? Infinity
        : median(gaps.slice(0, Math.max(1, startable - 1))) * TIER_GAP_MULTIPLIER;

    let tier = 1;
    const members: number[][] = [[]];
    sorted.forEach((player, i) => {
      if (i > 0 && gaps[i - 1] > threshold) {
        tier += 1;
        members.push([]);
      }
      members[tier - 1].push(player.id);
    });

    members.forEach((ids, index) => {
      for (const id of ids) {
        result.set(id, { tier: index + 1, remainingInTier: ids.length });
      }
    });
  }

  return result;
}
