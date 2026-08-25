'use client';

import type { DraftPlayer, KeeperRecommendation, Position } from '@/types/player';
import type { RosterRules } from '@/lib/bestAvailable';
import { DEFAULT_ROSTER_RULES, unmetNeeds } from '@/lib/bestAvailable';
import { PositionChip } from './bits';
import styles from './RosterPanel.module.css';

/**
 * What YOUR roster has and still needs.
 *
 * The board's other panels describe the pool; this one describes you. It is the
 * half of the draft-day question a VORP sort cannot answer, and it is why picks
 * carry an owner at all.
 */
export default function RosterPanel({
  players,
  counts,
  keptCounts,
  keepers,
  keeperIds,
  onToggleKeeper,
  picksMade,
  pickBudget,
  onPickBudgetChange,
  rules = DEFAULT_ROSTER_RULES,
}: {
  players: DraftPlayer[];
  counts: Record<Position, number>;
  keptCounts: Record<Position, number>;
  keepers: KeeperRecommendation[];
  keeperIds: Set<number>;
  onToggleKeeper: (id: number) => void;
  picksMade: number;
  pickBudget: number;
  onPickBudgetChange: (value: number) => void;
  rules?: RosterRules;
}) {
  const needs = unmetNeeds(counts, keptCounts, rules.starting_slots);
  const positions = Object.keys(rules.starting_slots) as Position[];
  const picksLeft = Math.max(0, pickBudget - picksMade);
  const totalNeed = positions.reduce((sum, position) => sum + needs[position], 0);

  // The same condition best_available uses to start reserving picks. Saying it
  // out loud is the point: it explains why the shortlist stops taking the best
  // player available.
  const reserving = totalNeed >= picksLeft && totalNeed > 0;

  const namesById = new Map(players.map((p) => [p.id, p.full_name]));

  return (
    <section className={styles.panel} aria-label="My roster">
      <div className={styles.slots}>
        {positions.map((position) => {
          const drafted = counts[position] ?? 0;
          const kept = keptCounts[position] ?? 0;
          const required = rules.starting_slots[position] ?? 0;
          const cap = rules.max_by_position[position] ?? 0;
          return (
            <div
              key={position}
              className={`${styles.slot} ${needs[position] > 0 ? styles.slotNeeded : ''}`}
              title={`${kept} kept + ${drafted} drafted · ${required} to start, ${cap} max`}
            >
              <PositionChip position={position} />
              <span className={styles.slotCount}>
                {kept + drafted}
                <span className={styles.slotOf}>/{required}</span>
              </span>
              {needs[position] > 0 && (
                <span className={styles.slotNeed}>need {needs[position]}</span>
              )}
            </div>
          );
        })}
      </div>

      <div className={styles.budget}>
        <label className={styles.budgetLabel}>
          My picks
          <input
            type="number"
            className={styles.budgetInput}
            min={0}
            max={30}
            value={pickBudget}
            onChange={(e) => onPickBudgetChange(Number(e.target.value))}
            aria-label="How many picks I hold this draft"
          />
        </label>
        <span className={styles.budgetState}>
          {picksMade} made · <strong>{picksLeft} left</strong>
        </span>
        {reserving && (
          <span className={styles.reserving} role="status">
            Reserving picks for unfilled slots
          </span>
        )}
      </div>

      {keepers.length > 0 && (
        <div className={styles.keepers}>
          <span className={styles.keepersLabel} title="From the keeper board's recommendation — a suggestion, not your committed list">
            Keeping
          </span>
          {keepers.map((k) => (
            <button
              key={k.id ?? k.full_name}
              className={`${styles.keeperChip} ${
                k.id !== null && keeperIds.has(k.id) ? styles.keeperChipOn : ''
              }`}
              onClick={() => k.id !== null && onToggleKeeper(k.id)}
              aria-pressed={k.id !== null && keeperIds.has(k.id)}
              disabled={k.id === null}
            >
              {namesById.get(k.id ?? -1) ?? k.full_name}
              <span className={styles.keeperPos}>{k.positionCode}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
