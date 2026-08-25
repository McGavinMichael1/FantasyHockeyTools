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

/**
 * The pick log.
 *
 * A flat set of drafted ids can say who is gone but not who took them, so it
 * cannot describe YOUR roster -- and "what does my roster still need?" is the
 * question actually being asked on the clock. Every pick therefore carries its
 * overall number and whether it was yours.
 */
export interface Pick {
  /** playerId, matching DraftPlayer.id. */
  id: number;
  /** 1-based overall pick number; renumbered whenever a pick is removed. */
  pick: number;
  /** True for your own picks, false for the other managers'. */
  mine: boolean;
}

const PICKS_STORAGE_KEY = 'fht.draftLog.v2';

/** The positions the board ranks, in a stable order. */
const POSITIONS = Object.keys(REPLACEMENT_RANKS) as Position[];

/** Pick numbers are always 1..n with no gaps -- picks-left math counts them. */
function renumber(picks: readonly Pick[]): Pick[] {
  return picks.map((pick, i) => ({ ...pick, pick: i + 1 }));
}

/** Every drafted id, whoever took them -- the input the VORP helpers want. */
export function draftedIds(picks: readonly Pick[]): Set<number> {
  return new Set(picks.map((p) => p.id));
}

export function myPicks(picks: readonly Pick[]): Pick[] {
  return picks.filter((p) => p.mine);
}

/**
 * Append a pick, unless that player is already logged.
 *
 * Double-tapping a row mid-draft must not invent a second pick and shift every
 * later number by one.
 */
export function addPick(picks: readonly Pick[], id: number, mine: boolean): Pick[] {
  if (picks.some((p) => p.id === id)) return [...picks];
  return [...picks, { id, pick: picks.length + 1, mine }];
}

export function undoLast(picks: readonly Pick[]): Pick[] {
  return picks.slice(0, -1);
}

export function removePick(picks: readonly Pick[], id: number): Pick[] {
  return renumber(picks.filter((p) => p.id !== id));
}

/** Reassign a pick's owner -- the "that one was mine" correction. */
export function setMine(picks: readonly Pick[], id: number, mine: boolean): Pick[] {
  return picks.map((p) => (p.id === id ? { ...p, mine } : p));
}

/**
 * How many of each position the given picks cover.
 *
 * Every position is present, zero included, so the roster panel can render an
 * unfilled slot without the caller filling in the gaps. Picks with no board row
 * are skipped: the board applies games-played display floors, so a real pick can
 * be someone it never listed.
 */
export function positionCounts(
  picks: readonly Pick[],
  players: DraftPlayer[],
): Record<Position, number> {
  const positionById = new Map(players.map((p) => [p.id, p.positionCode]));
  const counts = Object.fromEntries(
    POSITIONS.map((position) => [position, 0]),
  ) as Record<Position, number>;

  for (const pick of picks) {
    const position = positionById.get(pick.id);
    if (position !== undefined) counts[position] += 1;
  }
  return counts;
}

/** Drop malformed entries and restore pick order. */
function parsePicks(raw: unknown): Pick[] {
  if (!Array.isArray(raw)) return [];
  const valid = raw.filter(
    (entry): entry is Pick =>
      typeof entry === 'object' &&
      entry !== null &&
      typeof (entry as Pick).id === 'number' &&
      typeof (entry as Pick).pick === 'number' &&
      typeof (entry as Pick).mine === 'boolean',
  );
  return renumber([...valid].sort((a, b) => a.pick - b.pick));
}

/**
 * The pick log, migrating a v1 drafted-id list on first read.
 *
 * v1 had no notion of ownership, so everything it holds becomes a pick nobody
 * claims -- the only honest reading. The v1 key is left in place as insurance,
 * which is why an EXISTING v2 key short-circuits the migration even when it is
 * empty: otherwise clearing the board would undo itself on the next reload.
 */
export function loadPicks(storage?: Storage): Pick[] {
  try {
    const store = storage ?? globalThis.localStorage;
    const raw = store?.getItem(PICKS_STORAGE_KEY);
    if (raw != null) return parsePicks(JSON.parse(raw) as unknown);
  } catch {
    return [];
  }
  return [...loadDrafted(storage)].map((id, i) => ({ id, pick: i + 1, mine: false }));
}

export function savePicks(picks: readonly Pick[], storage?: Storage): void {
  try {
    const store = storage ?? globalThis.localStorage;
    store?.setItem(PICKS_STORAGE_KEY, JSON.stringify(picks));
  } catch {
    // Persistence is a convenience; never let it break the board.
  }
}
