// Display helpers for the multi-year keeper valuation.
//
// The math lives in Python (src/keeperHorizon.py) and arrives pre-computed in
// frontend_data.json -- this file only decides how to SAY it. It lives in
// src/lib rather than in the keeper page because the test runner is bare
// `node --test` with no DOM, so src/lib is the only testable surface.
//
// The one rule everything here serves: a horizon number must never be
// mistaken for a season total. It is a five-year discounted sum, and it
// already nets out the annual pick cost.

import type { HorizonYear, KeeperRecommendation } from '@/types/player';

export const HORIZON_YEARS = 5;
export const HORIZON_LABEL = `${HORIZON_YEARS}-yr keep value`;

export interface HorizonSummary {
  value: number;
  multiplier: number | null;
  /** e.g. "worth 2.27 seasons of him, after the picks it costs" */
  caption: string;
  years: HorizonYear[];
}

/**
 * Null unless the board actually carries a horizon value. A board built
 * without season history exports nulls, and the card must fall back to the
 * single-season number rather than rendering "NaN" or a fabricated zero.
 */
export function horizonSummary(
  player: Pick<
    KeeperRecommendation,
    'horizon_keeper_value' | 'horizon_multiplier' | 'horizon_breakdown'
  >,
): HorizonSummary | null {
  const value = player.horizon_keeper_value;
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return null;
  }
  const multiplier = Number.isFinite(player.horizon_multiplier as number)
    ? (player.horizon_multiplier as number)
    : null;

  return {
    value,
    multiplier,
    caption:
      multiplier === null
        ? `Discounted over ${HORIZON_YEARS} seasons, after the picks it costs`
        : `Worth ${multiplier.toFixed(2)} seasons of him, after the picks it costs`,
    years: player.horizon_breakdown ?? [],
  };
}

/** Signed, one decimal: horizon value can go negative for an old keeper. */
export function formatHorizonValue(value: number): string {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(1)}`;
}

/**
 * Per-year bar heights, as a fraction of the largest contribution. Year 1 is
 * usually the peak, but not always -- an age curve above 1.0 can make year 2
 * larger -- so this scales to the actual maximum rather than assuming.
 * Negative years scale to 0 so the bar simply disappears.
 */
export function yearWeights(years: HorizonYear[]): number[] {
  const peak = Math.max(...years.map((entry) => entry.value), 0);
  if (peak <= 0) return years.map(() => 0);
  return years.map((entry) => Math.max(0, entry.value) / peak);
}

/**
 * The sentence under the breakdown. Names the year a keeper stops paying for
 * himself, which is the thing an owner actually wants out of five numbers:
 * for a 34-year-old that lands around year 3, for a 23-year-old not at all.
 */
export function fadeSummary(years: HorizonYear[]): string {
  if (years.length === 0) return '';
  const first = years[0]?.value ?? 0;
  if (first <= 0) return 'Below replacement from the first season.';

  const faded = years.find((entry) => entry.value < first * 0.25);
  return faded
    ? `Contributes little past year ${faded.year - 1}.`
    : `Still contributing in year ${years[years.length - 1].year}.`;
}
