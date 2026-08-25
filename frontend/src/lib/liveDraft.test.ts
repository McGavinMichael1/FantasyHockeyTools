import assert from 'node:assert/strict';
import test from 'node:test';
import type { DraftPlayer, Position } from '@/types/player';
import {
  REPLACEMENT_RANKS,
  addPick,
  draftedIds,
  liveVorp,
  loadDrafted,
  loadPicks,
  myPicks,
  positionCounts,
  positionalRuns,
  remaining,
  removePick,
  replacementLevels,
  saveDrafted,
  savePicks,
  setMine,
  undoLast,
  withLiveVorp,
} from './liveDraft';

function player(id: number, positionCode: Position, projected_total: number): DraftPlayer {
  return {
    id,
    full_name: `Player ${id}`,
    positionCode,
    headshot: '',
    age: 25,
    gamesPlayed: 82,
    last_fpPerGame: 1,
    projected_fpPerGame: 1,
    projected_total,
    delta_vs_last: 0,
    vorp: null,
    projected_gp: 78,
    confidence: null,
    factors: [],
    stats: [],
    summary: null,
  };
}

/** `count` players at one position, projected_total descending from `top`. */
function pool(positionCode: Position, count: number, top = 1000, idBase = 0): DraftPlayer[] {
  return Array.from({ length: count }, (_, i) =>
    player(idBase + i + 1, positionCode, top - i),
  );
}

// --- replacement levels ---------------------------------------------------

test('replacement level is the Nth-best projected total at the position', () => {
  const players = pool('C', REPLACEMENT_RANKS.C);
  // 24 centers from 1000 down to 977; the 24th is 977.
  assert.equal(replacementLevels(players).C, 1000 - (REPLACEMENT_RANKS.C - 1));
});

test('a position thinner than its replacement rank has no level', () => {
  // Late in a draft the 24th-best center does not exist. Defaulting to zero
  // would make everyone left at a thin position look absurdly valuable.
  const levels = replacementLevels(pool('C', REPLACEMENT_RANKS.C - 1));
  assert.equal(levels.C, undefined);
});

test('each position uses its own rank', () => {
  const players = [...pool('C', 30, 1000, 0), ...pool('D', 50, 500, 100)];
  const levels = replacementLevels(players);
  assert.equal(levels.C, 1000 - (REPLACEMENT_RANKS.C - 1));
  assert.equal(levels.D, 500 - (REPLACEMENT_RANKS.D - 1));
});

test('keeper-adjusted ranks from the export override the base ranks', () => {
  // main.py draft shrinks each rank by the keepers already at that position. If
  // the board ignored them it would recompute a different number from the one
  // in the column it is replacing.
  const players = pool('C', 30);
  const ranks = { ...REPLACEMENT_RANKS, C: 9 };

  assert.equal(replacementLevels(players, ranks).C, 1000 - 8);
  assert.equal(liveVorp(players, new Set(), ranks).get(1), 8);
  assert.equal(withLiveVorp(players, new Set(), ranks)[0].vorp, 8);
  assert.equal(positionalRuns(players, new Set([1, 2]), ranks)[0].total, 9);
});

// --- live VORP ------------------------------------------------------------

test('drafting nobody reproduces the static replacement level', () => {
  const players = pool('C', 30);
  const vorp = liveVorp(players, new Set());
  assert.equal(vorp.get(1), 1000 - (1000 - (REPLACEMENT_RANKS.C - 1)));
});

test('VORP rises for the survivors as the position gets picked over', () => {
  const players = pool('C', 30);
  const before = liveVorp(players, new Set()).get(30)!;
  // Remove the top 5 centers: replacement level drops, so everyone left is
  // worth more relative to it. This is the whole point of the live board.
  const after = liveVorp(players, new Set([1, 2, 3, 4, 5])).get(30)!;
  assert.ok(after > before, `expected ${after} > ${before}`);
});

test('a drafted player is excluded from the remaining pool', () => {
  const players = pool('C', 5);
  assert.deepEqual(
    remaining(players, new Set([2, 4])).map((p) => p.id),
    [1, 3, 5],
  );
});

test('VORP is null when the position can no longer field a replacement', () => {
  const players = pool('C', REPLACEMENT_RANKS.C);
  const drafted = new Set([1]);
  assert.equal(liveVorp(players, drafted).get(2), null);
});

test('withLiveVorp overwrites the stale exported value', () => {
  const players = pool('C', 30).map((p) => ({ ...p, vorp: -999 }));
  const updated = withLiveVorp(players, new Set());
  assert.notEqual(updated[0].vorp, -999);
  // and does not mutate the input
  assert.equal(players[0].vorp, -999);
});

// --- positional runs ------------------------------------------------------

test('a positional run is measured against the position top tier', () => {
  const players = pool('C', 30);
  const runs = positionalRuns(players, new Set([1, 2, 3]));
  const centers = runs.find((r) => r.position === 'C')!;
  assert.equal(centers.taken, 3);
  assert.equal(centers.total, REPLACEMENT_RANKS.C);
});

test('only top-tier picks count toward a run', () => {
  // Draft the three WORST centers: no run is happening.
  const players = pool('C', 30);
  const runs = positionalRuns(players, new Set([28, 29, 30]));
  assert.equal(runs.find((r) => r.position === 'C')!.taken, 0);
});

test('the most depleted position sorts first', () => {
  const players = [...pool('C', 30, 1000, 0), ...pool('D', 60, 500, 100)];
  const runs = positionalRuns(players, new Set([1, 2, 3, 4, 5]));
  assert.equal(runs[0].position, 'C');
});

// --- persistence ----------------------------------------------------------

function storageWith(entries: Record<string, string> = {}): Storage {
  const map = new Map<string, string>(Object.entries(entries));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;
}

function fakeStorage(initial?: string): Storage {
  return storageWith(initial === undefined ? {} : { 'fht.draftedIds.v1': initial });
}

test('drafted ids survive a round trip', () => {
  const storage = fakeStorage();
  saveDrafted(new Set([3, 1, 2]), storage);
  assert.deepEqual([...loadDrafted(storage)].sort(), [1, 2, 3]);
});

test('corrupt stored state yields an empty set rather than throwing', () => {
  // Crashing the board mid-draft is far worse than losing the picks.
  assert.equal(loadDrafted(fakeStorage('not json')).size, 0);
  assert.equal(loadDrafted(fakeStorage('{"not":"an array"}')).size, 0);
});

test('a storage that throws does not take the board down', () => {
  const hostile = {
    getItem: () => {
      throw new Error('private mode');
    },
    setItem: () => {
      throw new Error('quota exceeded');
    },
  } as unknown as Storage;

  assert.equal(loadDrafted(hostile).size, 0);
  assert.doesNotThrow(() => saveDrafted(new Set([1]), hostile));
});

// --- pick log -------------------------------------------------------------

test('picks are numbered in the order they were made', () => {
  const log = addPick(addPick(addPick([], 7, false), 3, true), 9, false);
  assert.deepEqual(
    log.map((p) => [p.id, p.pick, p.mine]),
    [
      [7, 1, false],
      [3, 2, true],
      [9, 3, false],
    ],
  );
});

test('a player already in the log is not picked twice', () => {
  // Double-tapping the same row mid-draft must not invent a second pick and
  // shift every later pick number by one.
  const log = addPick(addPick([], 7, false), 7, true);
  assert.equal(log.length, 1);
  assert.equal(log[0].mine, false);
});

test('draftedIds returns every pick regardless of who made it', () => {
  const log = addPick(addPick([], 7, false), 3, true);
  assert.deepEqual([...draftedIds(log)].sort(), [3, 7]);
});

test('myPicks returns only the picks marked mine', () => {
  const log = addPick(addPick(addPick([], 7, false), 3, true), 9, true);
  assert.deepEqual(myPicks(log).map((p) => p.id), [3, 9]);
});

test('undoLast removes the most recent pick', () => {
  const log = addPick(addPick([], 7, false), 3, true);
  assert.deepEqual(undoLast(log).map((p) => p.id), [7]);
});

test('undoing an empty log is a no-op rather than an error', () => {
  assert.deepEqual(undoLast([]), []);
});

test('removing a pick renumbers the ones after it', () => {
  // Pick numbers are what the roster panel and the picks-left math count, so a
  // gap would quietly overstate how far into the draft you are.
  let log = addPick(addPick(addPick([], 7, false), 3, true), 9, false);
  log = removePick(log, 3);
  assert.deepEqual(
    log.map((p) => [p.id, p.pick]),
    [
      [7, 1],
      [9, 2],
    ],
  );
});

test('setMine flips ownership without disturbing the order', () => {
  // "I marked him taken, then realised that was my pick" -- the common
  // mid-draft correction.
  const log = setMine(addPick(addPick([], 7, false), 3, false), 7, true);
  assert.deepEqual(
    log.map((p) => [p.id, p.pick, p.mine]),
    [
      [7, 1, true],
      [3, 2, false],
    ],
  );
});

test('positionCounts counts the picks it is given, by position', () => {
  const players = [...pool('C', 2, 1000, 0), ...pool('D', 2, 500, 100)];
  const log = addPick(addPick(addPick([], 1, true), 2, true), 101, true);
  const counts = positionCounts(log, players);
  assert.equal(counts.C, 2);
  assert.equal(counts.D, 1);
  assert.equal(counts.G, 0, 'every position is present so the panel can render a zero');
});

test('positionCounts ignores picks with no matching board row', () => {
  // The board applies games-played display floors, so a real pick can be a
  // player the board never listed.
  const counts = positionCounts(addPick([], 999, true), pool('C', 2));
  assert.equal(counts.C, 0);
});

// --- pick log persistence -------------------------------------------------

test('a pick log survives a round trip', () => {
  const storage = storageWith();
  const log = addPick(addPick([], 7, false), 3, true);
  savePicks(log, storage);
  assert.deepEqual(loadPicks(storage), log);
});

test('a v1 drafted-id list migrates to picks nobody claims', () => {
  // Everyone stored under v1 was marked with the old owner-less toggle, so the
  // only honest reading is "taken by someone".
  const storage = storageWith({ 'fht.draftedIds.v1': JSON.stringify([7, 3, 9]) });
  assert.deepEqual(
    loadPicks(storage).map((p) => [p.id, p.pick, p.mine]),
    [
      [7, 1, false],
      [3, 2, false],
      [9, 3, false],
    ],
  );
});

test('an existing v2 log wins over a stale v1 list', () => {
  const storage = storageWith({
    'fht.draftedIds.v1': JSON.stringify([7, 3, 9]),
    'fht.draftLog.v2': JSON.stringify([{ id: 42, pick: 1, mine: true }]),
  });
  assert.deepEqual(loadPicks(storage).map((p) => p.id), [42]);
});

test('clearing every pick does not resurrect the migrated v1 list', () => {
  // v1 is left in place as insurance, so "log exists but is empty" has to be
  // distinguishable from "log was never written" -- otherwise Clear would undo
  // itself on the next reload, mid-draft.
  const storage = storageWith({ 'fht.draftedIds.v1': JSON.stringify([7, 3]) });
  savePicks([], storage);
  assert.deepEqual(loadPicks(storage), []);
});

test('a corrupt pick log yields an empty log rather than throwing', () => {
  assert.deepEqual(loadPicks(storageWith({ 'fht.draftLog.v2': 'not json' })), []);
  assert.deepEqual(loadPicks(storageWith({ 'fht.draftLog.v2': '{"not":"an array"}' })), []);
});

test('malformed entries are dropped and the survivors renumbered', () => {
  const storage = storageWith({
    'fht.draftLog.v2': JSON.stringify([
      { id: 7, pick: 1, mine: false },
      { id: 'nope', pick: 2, mine: false },
      { id: 9, pick: 3, mine: true },
    ]),
  });
  assert.deepEqual(
    loadPicks(storage).map((p) => [p.id, p.pick]),
    [
      [7, 1],
      [9, 2],
    ],
  );
});

test('a stored log out of pick order is restored in order', () => {
  const storage = storageWith({
    'fht.draftLog.v2': JSON.stringify([
      { id: 9, pick: 2, mine: true },
      { id: 7, pick: 1, mine: false },
    ]),
  });
  assert.deepEqual(loadPicks(storage).map((p) => p.id), [7, 9]);
});

test('a hostile storage does not take the pick log down', () => {
  const hostile = {
    getItem: () => {
      throw new Error('private mode');
    },
    setItem: () => {
      throw new Error('quota exceeded');
    },
  } as unknown as Storage;

  assert.deepEqual(loadPicks(hostile), []);
  assert.doesNotThrow(() => savePicks(addPick([], 1, true), hostile));
});
