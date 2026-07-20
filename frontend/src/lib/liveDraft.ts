import type { DraftPlayer, Position } from '@/types/player';

/**
 * Live draft-day VORP.
 *
 * The exported `vorp` on each player is computed against the preseason pool
 * with every keeper removed. On draft day that goes stale the moment picks start
 * coming off the board: once the top 20 centers are gone, the replacement-level
 * center is a much worse player, and everyone still available at the position is
 * worth more than their static number says.
 *
 * These helpers recompute the same quantity against whoever is still available.
 *
 * Semantics mirror src/keeper.py::replacement_levels exactly -- replacement
 * level at a position is the Nth-best projected_total still on the board, and
 * VORP is projected_total minus that. Keep the two in step; a divergence would
 * mean the draft-day number and the keeper number quietly disagree about what
 * "value" means.
 *
 * N itself is not fixed: keeper.replacement_ranks() shrinks each rank by the
 * keepers already filling that position, because the league does not draft slots
 * its keepers occupy. Pass the exported `draft_replacement_ranks` through, or
 * these helpers fall back to the no-keeper base below and disagree with the
 * exported column.
 */

/** Mirrors keeper.REPLACEMENT_RANKS -- the NO-KEEPER base ranks. */
export const REPLACEMENT_RANKS: Record<Position, number> = {
  C: 24,
  L: 24,
  R: 24,
  D: 48,
  G: 20,
};

export type ReplacementLevels = Partial<Record<Position, number>>;

/** Players still available, in board order. */
export function remaining(players: DraftPlayer[], drafted: ReadonlySet<number>): DraftPlayer[] {
  return players.filter((p) => !drafted.has(p.id));
}

/**
 * Replacement-level projected_total per position among the given players.
 *
 * A position with fewer players left than its rank has no level: late in a
 * draft the 24th-best center simply does not exist. Those positions are left
 * out rather than defaulted to zero, which would make every remaining player at
 * a thin position look absurdly valuable.
 */
export function replacementLevels(
  players: DraftPlayer[],
  ranks: Record<Position, number> = REPLACEMENT_RANKS,
): ReplacementLevels {
  const byPosition = new Map<Position, number[]>();
  for (const player of players) {
    const totals = byPosition.get(player.positionCode) ?? [];
    totals.push(player.projected_total);
    byPosition.set(player.positionCode, totals);
  }

  const levels: ReplacementLevels = {};
  for (const [position, totals] of byPosition) {
    const rank = ranks[position];
    if (rank === undefined || totals.length < rank) continue;
    totals.sort((a, b) => b - a);
    levels[position] = totals[rank - 1];
  }
  return levels;
}

/**
 * Each player's VORP against the remaining pool.
 *
 * Returns null where the position has no replacement level, matching the
 * board's existing "—" rendering for players whose vorp was never exported.
 */
export function liveVorp(
  players: DraftPlayer[],
  drafted: ReadonlySet<number>,
  ranks: Record<Position, number> = REPLACEMENT_RANKS,
): Map<number, number | null> {
  const levels = replacementLevels(remaining(players, drafted), ranks);
  const result = new Map<number, number | null>();
  for (const player of players) {
    const level = levels[player.positionCode];
    result.set(player.id, level === undefined ? null : player.projected_total - level);
  }
  return result;
}

/** A player list with `vorp` replaced by its live value. */
export function withLiveVorp(
  players: DraftPlayer[],
  drafted: ReadonlySet<number>,
  ranks: Record<Position, number> = REPLACEMENT_RANKS,
): DraftPlayer[] {
  const live = liveVorp(players, drafted, ranks);
  return players.map((p) => ({ ...p, vorp: live.get(p.id) ?? null }));
}

export interface PositionalRun {
  position: Position;
  taken: number;
  total: number;
  /** Share of the position's top tier already drafted, 0-1. */
  depleted: number;
}

/**
 * How picked-over each position's top tier is.
 *
 * This is the signal a draft board cannot give you from static numbers: when
 * seven of the top ten centers go in two rounds, the run is happening now and
 * the last good one is about to disappear. Measured against the position's
 * replacement rank, so "top tier" means the players who are actually startable
 * rather than an arbitrary cutoff.
 */
export function positionalRuns(
  players: DraftPlayer[],
  drafted: ReadonlySet<number>,
  ranks: Record<Position, number> = REPLACEMENT_RANKS,
): PositionalRun[] {
  const byPosition = new Map<Position, DraftPlayer[]>();
  for (const player of players) {
    const group = byPosition.get(player.positionCode) ?? [];
    group.push(player);
    byPosition.set(player.positionCode, group);
  }

  const runs: PositionalRun[] = [];
  for (const [position, group] of byPosition) {
    const tierSize = Math.min(ranks[position] ?? group.length, group.length);
    const tier = [...group]
      .sort((a, b) => b.projected_total - a.projected_total)
      .slice(0, tierSize);
    const taken = tier.filter((p) => drafted.has(p.id)).length;
    runs.push({
      position,
      taken,
      total: tierSize,
      depleted: tierSize === 0 ? 0 : taken / tierSize,
    });
  }
  return runs.sort((a, b) => b.depleted - a.depleted);
}

const STORAGE_KEY = 'fht.draftedIds.v1';

/**
 * Drafted ids persisted across reloads.
 *
 * A draft runs for hours in one tab; an accidental refresh losing every pick
 * would make the tool worse than paper. Storage failures (private mode, quota)
 * are swallowed -- losing persistence is survivable, crashing mid-draft is not.
 */
export function loadDrafted(storage?: Storage): Set<number> {
  try {
    const store = storage ?? globalThis.localStorage;
    const raw = store?.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((id): id is number => typeof id === 'number'));
  } catch {
    return new Set();
  }
}

export function saveDrafted(drafted: ReadonlySet<number>, storage?: Storage): void {
  try {
    const store = storage ?? globalThis.localStorage;
    store?.setItem(STORAGE_KEY, JSON.stringify([...drafted]));
  } catch {
    // Persistence is a convenience; never let it break the board.
  }
}
