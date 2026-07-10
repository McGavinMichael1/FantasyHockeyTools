'use client';

import type { Player } from '@/types/player';
import {
  Headshot,
  POSITION_NAMES,
  ScoreMeter,
  last5Pace,
  type Tone,
} from './bits';
import styles from './ThreeStars.module.css';

const STAR_LABELS = ['First star', 'Second star', 'Third star'];
const FREEZE_LABELS = ['Coldest', 'Second', 'Third'];

function StarCard({
  player,
  index,
  tone,
}: {
  player: Player;
  index: number;
  tone: Tone;
}) {
  const score = tone === 'hot' ? player.final_score : player.cooling_score;
  const label = tone === 'hot' ? STAR_LABELS[index] : FREEZE_LABELS[index];

  return (
    <article
      className={`${styles.card} ${index === 0 ? styles.cardFirst : ''}`}
      style={{ animationDelay: `${index * 90}ms` }}
    >
      <header className={styles.cardTop}>
        <span
          className={`${styles.starLabel} ${tone === 'cold' ? styles.starLabelCold : ''}`}
        >
          {tone === 'hot' ? '★' : '❄'} {label}
        </span>
        <span className={styles.sweater}>#{player.sweaterNumber}</span>
      </header>

      <div className={styles.identity}>
        <Headshot
          src={player.headshot}
          name={player.full_name}
          size={index === 0 ? 72 : 56}
        />
        <div>
          <h3 className={styles.name}>{player.full_name}</h3>
          <p className={styles.meta}>
            {POSITION_NAMES[player.positionCode]} · {player.gamesPlayed} GP ·{' '}
            {player.avgToi} TOI
          </p>
        </div>
      </div>

      <dl className={styles.stats}>
        <div className={styles.stat}>
          <dt>Last 5 pace</dt>
          <dd>{last5Pace(player).toFixed(1)}</dd>
        </div>
        <div className={styles.stat}>
          <dt>Season pace</dt>
          <dd>{player.season_ppg.toFixed(1)}</dd>
        </div>
        <div className={styles.stat}>
          <dt>Points</dt>
          <dd>
            {player.goals}–{player.assists}–{player.points}
          </dd>
        </div>
      </dl>

      <footer className={styles.cardFoot}>
        <span className={styles.scoreLabel}>
          {tone === 'hot' ? 'Heat' : 'Chill'}
        </span>
        <ScoreMeter value={score} tone={tone} />
      </footer>
    </article>
  );
}

export default function ThreeStars({
  players,
  tone,
}: {
  players: Player[];
  tone: Tone;
}) {
  const stars = players.slice(0, 3);
  if (stars.length === 0) return null;

  return (
    <section
      className={styles.hero}
      aria-label={tone === 'hot' ? "Tonight's three stars" : 'Cold front'}
    >
      {/* Faceoff circle, drawn behind the cards */}
      <svg
        className={styles.circle}
        viewBox="0 0 600 600"
        aria-hidden="true"
        focusable="false"
      >
        <circle
          cx="300"
          cy="300"
          r="280"
          fill="none"
          stroke={tone === 'hot' ? 'var(--hot)' : 'var(--cold)'}
          strokeWidth="10"
          opacity="0.1"
        />
        <circle
          cx="300"
          cy="300"
          r="16"
          fill={tone === 'hot' ? 'var(--hot)' : 'var(--cold)'}
          opacity="0.12"
        />
      </svg>

      <div className={styles.heading}>
        <p className={styles.eyebrow}>
          {tone === 'hot' ? 'Waiver wire' : 'Drop watch'}
        </p>
        <h2 className={styles.title}>
          {tone === 'hot' ? "Tonight's three stars" : 'Cold front'}
        </h2>
        <p className={styles.subtitle}>
          {tone === 'hot'
            ? 'The three strongest unrostered adds by blended model score.'
            : 'Rostered players running furthest below their season pace.'}
        </p>
      </div>

      <div className={styles.cards}>
        {stars.map((p, i) => (
          <StarCard key={p.id} player={p} index={i} tone={tone} />
        ))}
      </div>
    </section>
  );
}
