import assert from 'node:assert/strict';
import test from 'node:test';
import type { DraftPlayer, Position } from '@/types/player';
import { MIN_FOR_TIERING, TIER_GAP_MULTIPLIER, tiers } from './tiers';

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

/** Players at one position from the given projected totals, ids 1..n. */
function at(positionCode: Position, totals: number[], idBase = 0): DraftPlayer[] {
  return totals.map((total, i) => player(idBase + i + 1, positionCode, total));
}

test('a cliff in projected totals opens a new tier', () => {
  // Three clustered, then a 38-point drop: that drop is the whole point of a
  // tier board -- it is the difference between "wait a round" and "take him now".
  const board = at('C', [100, 99, 98, 60, 59]);
  const result = tiers(board, new Set());

  assert.equal(result.get(3)!.tier, 1, '98 is still in the top cluster');
  assert.equal(result.get(4)!.tier, 2, '60 is across the cliff');
});

test('players inside one cluster share a tier', () => {
  const result = tiers(at('C', [100, 99, 98, 60, 59]), new Set());
  assert.equal(result.get(1)!.tier, result.get(2)!.tier);
  assert.equal(result.get(4)!.tier, result.get(5)!.tier);
});

test('remainingInTier counts who is left in that tier', () => {
  const result = tiers(at('C', [100, 99, 98, 60, 59]), new Set());
  assert.equal(result.get(1)!.remainingInTier, 3);
  assert.equal(result.get(4)!.remainingInTier, 2);
});

test('drafting a player shrinks his tier', () => {
  // "Two left in this tier" is the number that decides whether you can wait,
  // so it has to fall as the tier empties.
  const board = at('C', [100, 99, 98, 60, 59]);
  const result = tiers(board, new Set([1]));
  assert.equal(result.get(2)!.remainingInTier, 2);
});

test('a drafted player has no tier at all', () => {
  const result = tiers(at('C', [100, 99, 98, 60, 59]), new Set([1]));
  assert.equal(result.get(1), undefined);
});

test('each position is tiered against its own scale', () => {
  // A defenceman's 60 and a centre's 60 are not the same player. Tiering the
  // pooled list would put them in the same bucket.
  const board = [...at('C', [100, 99, 98, 60], 0), ...at('D', [50, 49, 48, 20], 100)];
  const result = tiers(board, new Set());

  assert.equal(result.get(4)!.tier, 2, 'the C cliff');
  assert.equal(result.get(104)!.tier, 2, 'the D cliff, on its own scale');
  assert.equal(result.get(103)!.tier, 1);
});

test('evenly spaced players form a single tier', () => {
  // No gap stands out, so there is no cliff to report. Inventing one would be
  // worse than silence -- it would read as a cliff that is not there.
  const result = tiers(at('C', [100, 90, 80, 70, 60]), new Set());
  const distinct = new Set([1, 2, 3, 4, 5].map((id) => result.get(id)!.tier));
  assert.deepEqual([...distinct], [1]);
});

test('identical projections form one tier, not one each', () => {
  const result = tiers(at('C', [50, 50, 50, 50]), new Set());
  assert.equal(result.get(4)!.tier, 1);
  assert.equal(result.get(1)!.remainingInTier, 4);
});

test('a position too thin to estimate a gap is one tier', () => {
  // Two players left cannot support a median gap. Late in a draft tiers stop
  // mattering anyway; a confident-looking number off one gap would be noise.
  const board = at('C', [100, 20]);
  assert.ok(board.length < MIN_FOR_TIERING);

  const result = tiers(board, new Set());
  assert.equal(result.get(1)!.tier, 1);
  assert.equal(result.get(2)!.tier, 1);
});

test('a position with nobody left yields no entries', () => {
  const result = tiers(at('C', [100, 99, 98]), new Set([1, 2, 3]));
  assert.equal(result.size, 0);
});

test('the gap multiplier is what decides a cliff', () => {
  // Pins the knob the whole heuristic turns on: a gap just under the threshold
  // is not a cliff, and one just over it is.
  const median = 10;
  const justUnder = median * TIER_GAP_MULTIPLIER - 1;
  const justOver = median * TIER_GAP_MULTIPLIER + 1;

  const under = tiers(at('C', [200, 190, 180, 180 - justUnder, 170 - justUnder]), new Set());
  const over = tiers(at('C', [200, 190, 180, 180 - justOver, 170 - justOver]), new Set());

  assert.equal(under.get(4)!.tier, 1);
  assert.equal(over.get(4)!.tier, 2);
});
