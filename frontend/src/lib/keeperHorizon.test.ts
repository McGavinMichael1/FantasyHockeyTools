import assert from 'node:assert/strict';
import test from 'node:test';
import type { HorizonYear } from '@/types/player';
import {
  HORIZON_LABEL,
  fadeSummary,
  formatHorizonValue,
  horizonSummary,
  yearWeights,
} from './keeperHorizon';

function years(values: number[]): HorizonYear[] {
  return values.map((value, index) => ({
    year: index + 1,
    discount: 0.88 ** (index + 1),
    survival: 0.85 ** (index + 1),
    aging: 1,
    value,
  }));
}

test('the label never lets a horizon number read as a season total', () => {
  assert.equal(HORIZON_LABEL, '5-yr keep value');
});

test('horizonSummary is null when the board carries no horizon value', () => {
  // A fresh clone has no player_seasons.csv, so runKeeper writes NA and the
  // export emits null. The card must fall back, not render NaN.
  assert.equal(
    horizonSummary({
      horizon_keeper_value: null,
      horizon_multiplier: null,
      horizon_breakdown: null,
    }),
    null,
  );
});

test('horizonSummary states the multiplier in seasons-of-him', () => {
  const summary = horizonSummary({
    horizon_keeper_value: 118.5,
    horizon_multiplier: 2.27,
    horizon_breakdown: years([40, 30, 22, 16, 10]),
  });

  assert.ok(summary);
  assert.equal(summary.value, 118.5);
  assert.equal(summary.caption, 'Worth 2.27 seasons of him, after the picks it costs');
  assert.equal(summary.years.length, 5);
});

test('a missing multiplier still produces a caption', () => {
  const summary = horizonSummary({
    horizon_keeper_value: 40,
    horizon_multiplier: null,
    horizon_breakdown: null,
  });

  assert.ok(summary);
  assert.equal(summary.caption, 'Discounted over 5 seasons, after the picks it costs');
  assert.deepEqual(summary.years, []);
});

test('formatHorizonValue signs the number both ways', () => {
  // An old keeper past his survival cliff can genuinely score negative.
  assert.equal(formatHorizonValue(118.47), '+118.5');
  assert.equal(formatHorizonValue(-12.4), '−12.4');
});

test('yearWeights scale to the actual peak, not to year 1', () => {
  // An age curve above 1.0 (a 21-year-old) can make year 2 the largest, so
  // assuming year 1 is the peak would push a bar past 100%.
  assert.deepEqual(yearWeights(years([10, 20, 10, 5, 0])), [0.5, 1, 0.5, 0.25, 0]);
});

test('yearWeights clamp negative years to zero rather than inverting a bar', () => {
  assert.deepEqual(yearWeights(years([20, 10, -5, -8, -9])), [1, 0.5, 0, 0, 0]);
});

test('yearWeights survive an all-negative breakdown', () => {
  assert.deepEqual(yearWeights(years([-1, -2])), [0, 0]);
});

test('fadeSummary names the year a keeper stops paying for himself', () => {
  // 40 -> 8 crosses the quarter mark at year 4, so the useful life is 3.
  assert.equal(fadeSummary(years([40, 30, 20, 8, 4])), 'Contributes little past year 3.');
});

test('fadeSummary says so when a keeper holds up across the horizon', () => {
  assert.equal(fadeSummary(years([40, 38, 35, 33, 30])), 'Still contributing in year 5.');
});

test('fadeSummary handles a keeper who is under water immediately', () => {
  assert.equal(fadeSummary(years([-2, -3])), 'Below replacement from the first season.');
});

test('fadeSummary is empty with no breakdown', () => {
  assert.equal(fadeSummary([]), '');
});
