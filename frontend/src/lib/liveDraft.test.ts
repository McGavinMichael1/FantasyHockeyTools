import assert from 'node:assert/strict';
import test from 'node:test';
import type { DraftPlayer, Position } from '@/types/player';
import {
  REPLACEMENT_RANKS,
  liveVorp,
  loadDrafted,
  positionalRuns,
  remaining,
  replacementLevels,
  saveDrafted,
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

function fakeStorage(initial?: string): Storage {
  const map = new Map<string, string>();
  if (initial !== undefined) map.set('fht.draftedIds.v1', initial);
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: () => null,
    length: 0,
  } as unknown as Storage;
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
