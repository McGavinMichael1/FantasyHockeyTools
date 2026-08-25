import type { Position } from '@/types/player';

/**
 * Roster-aware "who should I pick now".
 *
 * A straight VORP sort answers "who is the best player left", which is not the
 * question on the clock. This adds the two roster constraints that make an
 * answer legal: a cap per position (nine centers is a fake win -- FP does not
 * care about slots) and a floor (the tail of the draft is reserved for starting
 * slots you have not filled).
 *
 * The floor is the important one. Without it a VORP-greedy board took 60 D, 40
 * L, 20 G, 20 R and ZERO centers across 140 picks in the 2025 all-teams sweep,
 * because D replacement is drawn at rank 48 against forwards' 24 and so always
 * shows the fatter surplus. Caps alone cannot stop that -- they set a ceiling,
 * and the problem is the floor.
 *
 * ## This is a port, and the port is pinned
 *
 * `src/mockDraft.py::best_available` is the same rule. It exists twice because
 * the live board has to work on draft day with no Python running behind it.
 * Both are tested against `tests/fixtures/best_available_cases.json` -- change
 * the rule here and the Python test fails, and vice versa. Do not "fix" one
 * side alone.
 */

/** The minimum a legally fieldable roster needs. Mirrors keeper.STARTING_SLOTS. */
export const STARTING_SLOTS: Record<Position, number> = {
  C: 2,
  L: 2,
  R: 2,
  D: 4,
  G: 2,
};

/** How many of each position is worth rostering. Mirrors mockDraft.MAX_BY_POSITION. */
export const MAX_BY_POSITION: Record<Position, number> = {
  C: 4,
  L: 4,
  R: 4,
  D: 6,
  G: 2,
};

/** The slot rules, as `api_export.py` ships them in `draft_roster_rules`. */
export interface RosterRules {
  starting_slots: Record<Position, number>;
  max_by_position: Record<Position, number>;
}

export const DEFAULT_ROSTER_RULES: RosterRules = {
  starting_slots: STARTING_SLOTS,
  max_by_position: MAX_BY_POSITION,
};

/** Positions may be absent, so callers can pass a partial tally. */
export type PositionCounts = Readonly<Record<string, number>>;

/** The minimum a player needs for this rule. `DraftPlayer` satisfies it. */
export interface RankedPlayer {
  id: number;
  positionCode: Position;
  vorp: number | null;
}

const POSITIONS = Object.keys(STARTING_SLOTS) as Position[];

/**
 * Starting slots still unfilled, counting your keepers as already filling theirs.
 *
 * Never negative: a position you overfilled is not a need, it is a surplus.
 */
export function unmetNeeds(
  counts: PositionCounts,
  keptCounts?: PositionCounts | null,
  startingSlots: Record<Position, number> = STARTING_SLOTS,
): Record<Position, number> {
  const kept = keptCounts ?? {};
  return Object.fromEntries(
    POSITIONS.map((position) => [
      position,
      Math.max(
        0,
        (startingSlots[position] ?? 0) - (counts[position] ?? 0) - (kept[position] ?? 0),
      ),
    ]),
  ) as Record<Position, number>;
}

/**
 * Caps with your own keepers already counted against them.
 *
 * A team that kept a goalie can start only one more, so drafting two wastes a
 * pick -- the third goalie can never leave the bench, since UTIL takes skaters
 * only.
 */
export function positionCaps(
  keptCounts?: PositionCounts | null,
  maxByPosition: Record<Position, number> = MAX_BY_POSITION,
): Record<Position, number> {
  const kept = keptCounts ?? {};
  return Object.fromEntries(
    POSITIONS.map((position) => [
      position,
      Math.max(0, (maxByPosition[position] ?? 0) - (kept[position] ?? 0)),
    ]),
  ) as Record<Position, number>;
}

/**
 * Board order: best VORP first, players without one last.
 *
 * Python is always handed a pre-sorted board; the live board is sorted by
 * whatever column was last clicked, so this side sorts defensively. Treating a
 * null VORP as zero would float old-snapshot players above genuinely
 * negative-value ones.
 */
function byVorpDesc(board: readonly RankedPlayer[]): RankedPlayer[] {
  return [...board].sort((a, b) => {
    if (a.vorp === null) return b.vorp === null ? 0 : 1;
    if (b.vorp === null) return -1;
    return b.vorp - a.vorp;
  });
}

/**
 * The highest-VORP player left who does not blow a positional cap.
 *
 * Once there are only as many picks left as unfilled starting slots, the pick is
 * reserved for a position that still needs one. If nothing at a needed position
 * remains it falls back to best-available rather than forfeiting the pick.
 *
 * `picksLeft = null` disables the reservation entirely.
 */
export function bestAvailable(
  board: readonly RankedPlayer[],
  taken: ReadonlySet<number>,
  counts: PositionCounts,
  keptCounts?: PositionCounts | null,
  picksLeft?: number | null,
  rules: RosterRules = DEFAULT_ROSTER_RULES,
): RankedPlayer | null {
  let needed: Set<Position> | null = null;
  if (picksLeft != null) {
    const needs = unmetNeeds(counts, keptCounts, rules.starting_slots);
    const total = POSITIONS.reduce((sum, position) => sum + needs[position], 0);
    if (total >= picksLeft) {
      needed = new Set(POSITIONS.filter((position) => needs[position] > 0));
    }
  }

  // Caps only shrink for a team whose keepers we know, matching the Python
  // opponent path that passes none.
  const caps =
    keptCounts == null
      ? rules.max_by_position
      : positionCaps(keptCounts, rules.max_by_position);

  let fallback: RankedPlayer | null = null;
  for (const player of byVorpDesc(board)) {
    if (taken.has(player.id)) continue;
    const position = player.positionCode;
    if ((counts[position] ?? 0) >= (caps[position] ?? 99)) continue;
    if (needed !== null && !needed.has(position)) {
      fallback ??= player;
      continue;
    }
    return player;
  }
  return fallback;
}

/** One board recommendation, with the reason it is being recommended. */
export interface Candidate {
  player: RankedPlayer;
  reason: string;
}

/**
 * The top `limit` picks, each answering "why him".
 *
 * Built by asking `bestAvailable` repeatedly with each previous answer marked
 * taken, so entries 2 and 3 respect the same caps and floors as entry 1 rather
 * than being a raw VORP slice.
 */
export function shortlist(
  board: readonly RankedPlayer[],
  taken: ReadonlySet<number>,
  counts: PositionCounts,
  keptCounts?: PositionCounts | null,
  picksLeft?: number | null,
  limit = 3,
  rules: RosterRules = DEFAULT_ROSTER_RULES,
): Candidate[] {
  const needs = unmetNeeds(counts, keptCounts, rules.starting_slots);
  const gone = new Set(taken);
  const picked: Candidate[] = [];

  for (let i = 0; i < limit; i++) {
    const player = bestAvailable(board, gone, counts, keptCounts, picksLeft, rules);
    if (player === null) break;
    gone.add(player.id);

    const open = needs[player.positionCode] ?? 0;
    picked.push({
      player,
      reason:
        open > 0
          ? `fills ${player.positionCode} — ${open} starting slot${open === 1 ? '' : 's'} open`
          : 'best available',
    });
  }
  return picked;
}
