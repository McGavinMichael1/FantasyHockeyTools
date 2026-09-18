import assert from 'node:assert/strict';
import test from 'node:test';
import type { DraftPlayer } from '@/types/player';
import {
  MAX_FACTOR,
  MIN_FACTOR,
  applyNudges,
  clearNudge,
  loadNudges,
  saveNudges,
  setNudge,
  type NudgeMap,
} from './nudges';

function player(id: number, projected_total: number, vorp: number | null): DraftPlayer {
  return {
    id,
    full_name: `Player ${id}`,
    positionCode: 'C',
    headshot: '',
    age: 25,
    gamesPlayed: 82,
    last_fpPerGame: 1,
    projected_fpPerGame: projected_total / 80,
    projected_total,
    delta_vs_last: 0,
    vorp,
    projected_gp: 80,
    confidence: null,
    factors: [],
    stats: [],
    summary: null,
  };
}

/** A minimal in-memory Storage for the persistence round-trip. */
function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
    clear: () => data.clear(),
    key: (i) => [...data.keys()][i] ?? null,
    get length() {
      return data.size;
    },
  };
}

test('nudge scales projection and re-derives vorp against fixed replacement', () => {
  // projected_total 100, vorp 40 => replacement level is 60. A +20% nudge lifts
  // the projection to 120, so vorp must become 120 - 60 = 60, NOT 40 * 1.2 = 48.
  const [p] = applyNudges([player(1, 100, 40)], { 1: 1.2 });
  assert.equal(p.projected_total, 120);
  assert.equal(p.vorp, 60);
  assert.ok(Math.abs(p.projected_fpPerGame - (100 / 80) * 1.2) < 1e-9);
});

test('a downward nudge lowers projection and vorp', () => {
  const [p] = applyNudges([player(1, 100, 40)], { 1: 0.9 });
  assert.equal(p.projected_total, 90);
  assert.equal(p.vorp, 30); // 90 - 60
});

test('a null vorp stays null through a nudge', () => {
  const [p] = applyNudges([player(1, 100, null)], { 1: 1.5 });
  assert.equal(p.projected_total, 150);
  assert.equal(p.vorp, null);
});

test('unnudged players pass through untouched', () => {
  const board = [player(1, 100, 40), player(2, 90, 30)];
  const out = applyNudges(board, { 1: 1.2 });
  assert.equal(out[1], board[1], 'player 2 is returned by reference');
});

test('empty map returns the original array', () => {
  const board = [player(1, 100, 40)];
  assert.equal(applyNudges(board, {}), board);
});

test('setNudge clamps to the allowed band', () => {
  assert.equal(setNudge({}, 1, 99)[1], MAX_FACTOR);
  assert.equal(setNudge({}, 1, 0.01)[1], MIN_FACTOR);
});

test('setNudge drops an entry that lands back on neutral', () => {
  const map: NudgeMap = { 1: 1.2 };
  assert.deepEqual(setNudge(map, 1, 1.0), {});
});

test('clearNudge removes one entry immutably', () => {
  const map: NudgeMap = { 1: 1.2, 2: 0.8 };
  assert.deepEqual(clearNudge(map, 1), { 2: 0.8 });
  assert.deepEqual(map, { 1: 1.2, 2: 0.8 }, 'input not mutated');
});

test('persistence round-trips and drops junk', () => {
  const store = memoryStorage();
  saveNudges({ 1: 1.2, 2: 0.75 }, store);
  assert.deepEqual(loadNudges(store), { 1: 1.2, 2: 0.75 });

  store.setItem('fht.nudges.v1', '{"1":"nope","3":1.0,"4":1.3}');
  assert.deepEqual(loadNudges(store), { 4: 1.3 }, 'non-number and neutral dropped');
});
