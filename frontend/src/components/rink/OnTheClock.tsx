'use client';

import type { DraftPlayer } from '@/types/player';
import type { Candidate } from '@/lib/bestAvailable';
import { Headshot, PositionChip } from './bits';
import styles from './OnTheClock.module.css';

/**
 * Who the board would take right now, and why.
 *
 * The ranked table answers "who is the best player left". This answers "who
 * should I take", which differs whenever a positional cap or an unfilled
 * starting slot is binding. The reason line is not decoration -- a
 * recommendation that disagrees with the top of the table is only trustworthy
 * if it says what made it disagree.
 *
 * This is the same rule the mock-draft backtest runs on, and that backtest came
 * out INCONCLUSIVE against hand-drafting (-1.75% over 14 picks, 2025). Treat it
 * as a second opinion, not an instruction.
 */
export default function OnTheClock({
  candidates,
  playersById,
  onPick,
}: {
  candidates: Candidate[];
  playersById: Map<number, DraftPlayer>;
  onPick: (id: number) => void;
}) {
  if (candidates.length === 0) return null;

  return (
    <section className={styles.clock} aria-label="Recommended picks">
      <span className={styles.label}>On the clock</span>
      <div className={styles.cards}>
        {candidates.map(({ player, reason }, i) => {
          const full = playersById.get(player.id);
          if (!full) return null;
          return (
            <div key={player.id} className={`${styles.card} ${i === 0 ? styles.cardTop : ''}`}>
              <Headshot src={full.headshot} name={full.full_name} size={30} />
              <span className={styles.body}>
                <span className={styles.name}>
                  {full.full_name}
                  <PositionChip position={full.positionCode} />
                </span>
                <span className={styles.reason}>{reason}</span>
              </span>
              <span className={styles.vorp} title="Value over replacement, against who is left">
                {player.vorp === null ? '—' : player.vorp.toFixed(1)}
              </span>
              <button
                className={styles.take}
                onClick={() => onPick(player.id)}
                aria-label={`Draft ${full.full_name} to my roster`}
              >
                Take
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
