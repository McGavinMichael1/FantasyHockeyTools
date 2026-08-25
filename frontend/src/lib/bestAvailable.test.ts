import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import type { Position } from '@/types/player';
import {
  MAX_BY_POSITION,
  STARTING_SLOTS,
  bestAvailable,
  positionCaps,
  shortlist,
  unmetNeeds,
  type RankedPlayer,
} from './bestAvailable';

/**
 * The TypeScript half of the cross-language best-available contract.
 *
 * The same fixture drives tests/test_best_available_fixture.py. The live board
 * cannot call Python -- it has to work on draft day with nothing running behind
 * it -- so the rule genuinely exists twice, and this file is what stops the two
 * copies drifting.
 *
 * The fixture speaks Python's column names (playerId/position); each side adapts
 * to its own shape. It pins the RULE, not the field names.
 */
interface FixtureCase {
  name: string;
  why?: string;
  board: { playerId: number; full_name: string; position: Position; vorp: number }[];
  taken: number[];
  counts: Record<string, number>;
  kept_counts: Record<string, number> | null;
  picks_left: number | null;
  expected_playerId: number | null;
}

const fixture = JSON.parse(
  readFileSync(
    // npm scripts run from frontend/, so the repo root is one level up.
    path.resolve(process.cwd(), '../tests/fixtures/best_available_cases.json'),
    'utf-8',
  ),
) as {
  rules: { starting_slots: Record<Position, number>; max_by_position: Record<Position, number> };
  cases: FixtureCase[];
};

function toRanked(row: FixtureCase['board'][number]): RankedPlayer {
  return { id: row.playerId, positionCode: row.position, vorp: row.vorp };
}

test('the fallback constants match the ones Python ships', () => {
  // Python asserts the same block against keeper.STARTING_SLOTS. Failing here
  // means the league rules moved and this file was not updated with them.
  assert.deepEqual(STARTING_SLOTS, fixture.rules.starting_slots);
  assert.deepEqual(MAX_BY_POSITION, fixture.rules.max_by_position);
});

for (const testCase of fixture.cases) {
  test(`shared fixture: ${testCase.name}`, () => {
    const choice = bestAvailable(
      testCase.board.map(toRanked),
      new Set(testCase.taken),
      testCase.counts,
      testCase.kept_counts,
      testCase.picks_left,
    );

    assert.equal(choice === null ? null : choice.id, testCase.expected_playerId, testCase.why);
  });
}

// --- behaviour the live board needs and the backtest does not --------------

test('an unsorted board still yields the highest-VORP pick', () => {
  // Python is always handed a pre-sorted board. The live board is sorted by
  // whatever column the user last clicked, so this side has to sort defensively.
  const board: RankedPlayer[] = [
    { id: 1, positionCode: 'C', vorp: 10 },
    { id: 2, positionCode: 'C', vorp: 90 },
    { id: 3, positionCode: 'C', vorp: 50 },
  ];
  assert.equal(bestAvailable(board, new Set(), {})!.id, 2);
});

test('players with no VORP rank below everyone who has one', () => {
  // Old export snapshots carry a null vorp; treating null as zero would float
  // them above genuinely negative-value players.
  const board: RankedPlayer[] = [
    { id: 1, positionCode: 'C', vorp: null },
    { id: 2, positionCode: 'C', vorp: -5 },
  ];
  assert.equal(bestAvailable(board, new Set(), {})!.id, 2);
});

test('unmetNeeds counts a keeper as filling its slot', () => {
  assert.equal(unmetNeeds({ G: 1 }, { G: 1 }).G, 0);
  assert.equal(unmetNeeds({ G: 1 }).G, 1);
});

test('unmetNeeds never goes negative when a position is overfilled', () => {
  assert.equal(unmetNeeds({ C: 9 }).C, 0);
});

test('positionCaps shrink by the keepers already at that position', () => {
  assert.equal(positionCaps({ G: 1 }).G, MAX_BY_POSITION.G - 1);
  assert.equal(positionCaps().G, MAX_BY_POSITION.G);
});

test('positionCaps never go negative', () => {
  assert.equal(positionCaps({ G: 99 }).G, 0);
});

// --- the shortlist the board actually renders ------------------------------

test('the shortlist is ranked and as long as the limit allows', () => {
  const board: RankedPlayer[] = [
    { id: 1, positionCode: 'C', vorp: 90 },
    { id: 2, positionCode: 'D', vorp: 80 },
    { id: 3, positionCode: 'L', vorp: 70 },
    { id: 4, positionCode: 'R', vorp: 60 },
  ];
  assert.deepEqual(
    shortlist(board, new Set(), {}, null, null, 3).map((c) => c.player.id),
    [1, 2, 3],
  );
});

test('a shortlist entry says why it is there', () => {
  const board: RankedPlayer[] = [
    { id: 1, positionCode: 'C', vorp: 99 },
    { id: 2, positionCode: 'G', vorp: 5 },
  ];
  const forced = shortlist(board, new Set(), { C: 2, L: 2, R: 2, D: 4, G: 1 }, null, 1, 1);

  assert.equal(forced[0].player.id, 2);
  assert.match(forced[0].reason, /G/, 'the reason should name the slot being filled');
});

test('the shortlist runs out rather than repeating a player', () => {
  const board: RankedPlayer[] = [{ id: 1, positionCode: 'C', vorp: 90 }];
  assert.equal(shortlist(board, new Set(), {}, null, null, 3).length, 1);
});
