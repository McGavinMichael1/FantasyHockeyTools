'use client';

import { useState } from 'react';
import type { Player, Position } from '@/types/player';
import styles from './bits.module.css';

export type Tone = 'hot' | 'cold';

/** Full-name form of a position code, for tooltips and screen readers. */
export const POSITION_NAMES: Record<Position, string> = {
  C: 'Center',
  L: 'Left wing',
  R: 'Right wing',
  D: 'Defense',
  G: 'Goalie',
};

export function PositionChip({ position }: { position: Position }) {
  return (
    <span className={styles.positionChip} title={POSITION_NAMES[position]}>
      {position}
    </span>
  );
}

/** Thin 0–100 meter for model scores; red for heat, blue for cool, grey for
 *  neutral quantities like draft confidence that aren't hot or cold. */
export function ScoreMeter({
  value,
  tone,
}: {
  value: number;
  tone: Tone | 'neutral';
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  const fillClass =
    tone === 'hot'
      ? styles.meterHot
      : tone === 'cold'
        ? styles.meterCold
        : styles.meterNeutral;
  return (
    <div className={styles.meter}>
      <div
        className={styles.meterTrack}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div className={`${styles.meterFill} ${fillClass}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={styles.meterValue}>{pct}</span>
    </div>
  );
}

/** Fantasy points per game over the last 5 games. */
export function last5Pace(p: Player): number {
  return p.last5_fantasyPoints / 5;
}

/** Last-5 pace minus season pace, in fantasy points per game. */
export function paceDelta(p: Player): number {
  return last5Pace(p) - p.season_ppg;
}

/** Signed pace-change chip: red when running above season pace, blue below. */
export function PaceDeltaChip({ player }: { player: Player }) {
  const delta = paceDelta(player);
  const label = `${delta > 0 ? '+' : delta < 0 ? '−' : ''}${Math.abs(delta).toFixed(1)}`;
  const cls =
    delta >= 0.2
      ? styles.deltaHot
      : delta <= -0.2
        ? styles.deltaCold
        : styles.deltaFlat;
  return (
    <span
      className={`${styles.delta} ${cls}`}
      title="Last-5 fantasy pace vs. season pace (FP per game)"
    >
      {label}
    </span>
  );
}

export function Headshot({
  src,
  name,
  size = 40,
}: {
  src: string;
  name: string;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const initials = name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .slice(0, 2);

  return (
    <span className={styles.headshot} style={{ width: size, height: size }}>
      {failed || !src ? (
        <span className={styles.headshotInitials}>{initials}</span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
