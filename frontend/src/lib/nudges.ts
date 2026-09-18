/**
 * Manual projection nudges.
 *
 * The draft model is retrained offline and the board runs static on draft day,
 * so a mid-week line-up change the model never saw -- a player bumped to the top
 * power-play unit, say -- has no way in. A nudge is the human override: a
 * per-player multiplier on the projection. The board then re-ranks off the
 * nudged number, because VORP, tiers, best-available and the roster panel are
 * all derived from `projected_total` (see lib/liveDraft, lib/tiers).
 *
 * Draft-board only: nudges live in localStorage, never touch the model, the
 * exported JSON, or the keeper board.
 */

import type { DraftPlayer } from '@/types/player';

/** playerId -> multiplier. A player absent from the map is unnudged (factor 1). */
export type NudgeMap = Record<number, number>;

const STORAGE_KEY = 'fht.nudges.v1';

/**
 * The band a nudge may span. A fat-fingered 10x would silently wreck the board;
 * ±50% covers a realistic TOI swing (a 4th-liner to a 1st-line role and back).
 */
export const MIN_FACTOR = 0.5;
export const MAX_FACTOR = 2.0;

/** A factor is "no change" when it rounds to 1 -- such entries are not stored. */
function isNeutral(factor: number): boolean {
  return Math.abs(factor - 1) < 1e-9;
}

function clamp(factor: number): number {
  if (!Number.isFinite(factor)) return 1;
  return Math.min(MAX_FACTOR, Math.max(MIN_FACTOR, factor));
}

/** Set (or clear, when neutral) one player's nudge. Immutable. */
export function setNudge(map: NudgeMap, id: number, factor: number): NudgeMap {
  const clamped = clamp(factor);
  const next = { ...map };
  if (isNeutral(clamped)) delete next[id];
  else next[id] = clamped;
  return next;
}

/** Remove one player's nudge. Immutable. */
export function clearNudge(map: NudgeMap, id: number): NudgeMap {
  if (!(id in map)) return map;
  const next = { ...map };
  delete next[id];
  return next;
}

/**
 * Apply the nudges to a player list.
 *
 * Scales `projected_fpPerGame` and `projected_total`, then re-derives the static
 * `vorp`. VORP is value over a fixed replacement level, so it is NOT a multiple
 * of the projection: replacement is recovered as `projected_total - vorp` (it
 * does not move when one player is nudged) and the nudged vorp is
 * `nudged_total - replacement`. In draft mode liveDraft.withLiveVorp recomputes
 * vorp against the remaining pool anyway; this keeps the preseason column honest
 * for the same reason.
 *
 * Untouched players pass through by reference; a null vorp stays null.
 */
export function applyNudges(players: DraftPlayer[], map: NudgeMap): DraftPlayer[] {
  if (Object.keys(map).length === 0) return players;
  return players.map((p) => {
    const factor = map[p.id];
    if (factor === undefined || isNeutral(factor)) return p;
    const projected_total = p.projected_total * factor;
    return {
      ...p,
      projected_fpPerGame: p.projected_fpPerGame * factor,
      projected_total,
      vorp: p.vorp === null ? null : projected_total - (p.projected_total - p.vorp),
    };
  });
}

/** Load persisted nudges. Never throws -- a lost map is survivable mid-draft. */
export function loadNudges(storage?: Storage): NudgeMap {
  try {
    const store = storage ?? globalThis.localStorage;
    const raw = store?.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};
    const out: NudgeMap = {};
    for (const [key, value] of Object.entries(parsed)) {
      const id = Number(key);
      if (Number.isInteger(id) && typeof value === 'number' && !isNeutral(value)) {
        out[id] = clamp(value);
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function saveNudges(map: NudgeMap, storage?: Storage): void {
  try {
    const store = storage ?? globalThis.localStorage;
    store?.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Persistence is a convenience; never let it break the board.
  }
}
