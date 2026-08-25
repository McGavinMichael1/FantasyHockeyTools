'use client';

import { Fragment } from 'react';
import type { DraftPlayer } from '@/types/player';
import type { Pick } from '@/lib/liveDraft';
import type { TierInfo } from '@/lib/tiers';
import { Headshot, PositionChip, ScoreMeter } from './bits';
import styles from './RinkTable.module.css';
import bitStyles from './bits.module.css';

/**
 * The ranked table itself.
 *
 * Split out of DraftBoard, which owns the draft-day state (picks, roster,
 * recommendations, keyboard) and grew to twice this file's job. This renders
 * rows and reports interactions upward; it holds no state of its own.
 */

export type SortDir = 'asc' | 'desc';

export interface Column {
  key: string;
  label: string;
  title?: string;
  numeric?: boolean;
  sortValue?: (p: DraftPlayer) => number | string;
  render: (p: DraftPlayer) => React.ReactNode;
}

/** Signed projection-change chip: red when projected above last season, blue below. */
function ProjectionDeltaChip({ value }: { value: number }) {
  const label = `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(2)}`;
  const cls =
    value >= 0.1
      ? bitStyles.deltaHot
      : value <= -0.1
        ? bitStyles.deltaCold
        : bitStyles.deltaFlat;
  return (
    <span className={`${bitStyles.delta} ${cls}`} title="Projected FP per game vs. last season">
      {label}
    </span>
  );
}

export const COLUMNS: Column[] = [
  {
    key: 'full_name',
    label: 'Player',
    sortValue: (p) => p.full_name,
    render: (p) => (
      <span className={styles.playerCell}>
        <Headshot src={p.headshot} name={p.full_name} size={32} />
        <span className={styles.playerName}>{p.full_name}</span>
        <PositionChip position={p.positionCode} />
        {/* Only ~50 of 734 players have a summary; without a marker you expand
            rows blindly hunting for the ones that do. */}
        {p.summary && (
          <span
            className={styles.summaryDot}
            title="Has a scouting summary"
            aria-label="Has a scouting summary"
          />
        )}
      </span>
    ),
  },
  {
    key: 'age',
    label: 'Age',
    title: 'Age at next season start',
    numeric: true,
    sortValue: (p) => p.age ?? 0,
    render: (p) => (p.age === null ? '—' : p.age.toFixed(1)),
  },
  {
    key: 'gamesPlayed',
    label: 'GP',
    title: 'Games played last season',
    numeric: true,
    sortValue: (p) => p.gamesPlayed,
    render: (p) => p.gamesPlayed,
  },
  {
    key: 'last_fpPerGame',
    label: 'FP/G',
    title: 'Fantasy points per game last season',
    numeric: true,
    sortValue: (p) => p.last_fpPerGame,
    render: (p) => p.last_fpPerGame.toFixed(2),
  },
  {
    key: 'projected_fpPerGame',
    label: 'Proj FP/G',
    title: 'Model-projected fantasy points per game next season',
    numeric: true,
    sortValue: (p) => p.projected_fpPerGame,
    render: (p) => <strong>{p.projected_fpPerGame.toFixed(2)}</strong>,
  },
  {
    key: 'projected_total',
    label: 'Proj FP',
    title:
      'Projected season total (FP/game × projected games: 78 for skaters; weighted recent starts for goalies)',
    numeric: true,
    sortValue: (p) => p.projected_total,
    render: (p) => (
      <>
        {p.projected_total.toFixed(0)}
        {/* For a skater projected_gp is a flat 78 and says nothing. For a goalie
            it is the workload estimate that drives the whole number. */}
        {p.positionCode === 'G' && p.projected_gp !== null && (
          <span className={styles.startsHint}> ×{p.projected_gp.toFixed(0)}</span>
        )}
      </>
    ),
  },
  {
    key: 'vorp',
    label: 'VORP',
    title:
      'Value over replacement player (projected FP above a replacement-level pick at the position)',
    numeric: true,
    // old frontend_data.json snapshots lack vorp -- sort them last, render a dash
    sortValue: (p) => p.vorp ?? Number.NEGATIVE_INFINITY,
    render: (p) => (p.vorp != null ? p.vorp.toFixed(1) : '—'),
  },
  {
    key: 'delta_vs_last',
    label: 'Δ',
    title: 'Projected minus last-season FP per game',
    numeric: true,
    sortValue: (p) => p.delta_vs_last,
    render: (p) => <ProjectionDeltaChip value={p.delta_vs_last} />,
  },
  {
    key: 'confidence',
    label: 'Conf',
    title:
      'Model confidence (seasons of history, games played, age band, and how far the projection sits from recent form), 0–100',
    numeric: true,
    // players without a confidence sort last rather than mixing in at zero
    sortValue: (p) => p.confidence ?? -1,
    render: (p) =>
      p.confidence === null ? '—' : <ScoreMeter value={p.confidence / 100} tone="neutral" />,
  },
];

function ExpandedDraftDetail({ player }: { player: DraftPlayer }) {
  // Snapshots exported before the stat line existed have no `stats` key at all.
  // Same degrade-never-crash rule vorp and confidence already follow -- an old
  // frontend_data.json must render, not throw.
  const stats = player.stats ?? [];
  return (
    <div className={styles.detail}>
      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Last season</h4>
        {stats.length === 0 ? (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        ) : (
          <dl className={styles.statLine}>
            {stats.map((s) => (
              <div key={s.label} className={styles.statPair}>
                <dt className={styles.statLabel}>{s.label}</dt>
                <dd className={styles.statValue}>{s.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {player.projected_gp !== null && (
          <p className={styles.projectedGp}>
            Projected {player.projected_gp.toFixed(0)}{' '}
            {player.positionCode === 'G'
              ? 'starts'
              : 'games (a flat assumption for every skater, not a projection)'}
          </p>
        )}
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Scouting summary</h4>
        {player.summary ? (
          <p className={styles.summaryText}>{player.summary}</p>
        ) : (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        )}
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Confidence</h4>
        {player.confidence === null ? (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        ) : (
          <ScoreMeter value={player.confidence / 100} tone="neutral" />
        )}
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>What moved the ranking</h4>
        {player.factors.length === 0 ? (
          <p className={`${styles.summaryText} ${styles.summaryEmpty}`}>—</p>
        ) : (
          <ul className={styles.factorList}>
            {player.factors.map((f) => (
              <li
                key={f.label}
                className={`${styles.factorItem} ${
                  f.value >= 0 ? styles.factorUp : styles.factorDown
                }`}
              >
                <span className={styles.factorLabel}>{f.label}</span>
                <span className={styles.factorValue}>
                  {f.value >= 0 ? '+' : '−'}
                  {Math.abs(f.value).toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function DraftTable({
  rows,
  draftMode,
  pickById,
  tierMap,
  expandedIds,
  activeRow,
  sortKey,
  sortDir,
  onToggleExpanded,
  onSetActiveRow,
  onToggleSort,
  onMarkTaken,
  onMarkMine,
}: {
  rows: DraftPlayer[];
  draftMode: boolean;
  pickById: Map<number, Pick>;
  tierMap: Map<number, TierInfo>;
  expandedIds: Set<number>;
  activeRow: number;
  sortKey: string;
  sortDir: SortDir;
  onToggleExpanded: (id: number) => void;
  onSetActiveRow: (index: number) => void;
  onToggleSort: (col: Column) => void;
  onMarkTaken: (id: number) => void;
  onMarkMine: (id: number) => void;
}) {
  const span = COLUMNS.length + (draftMode ? 3 : 2);

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.thRank} scope="col">
              No.
            </th>
            <th
              className={styles.thNumeric}
              scope="col"
              title="Tier within the position, and how many are left in it. A display grouping of the projections — not a model output."
            >
              Tier
            </th>
            {draftMode && (
              <th
                className={styles.draftCell}
                scope="col"
                title="✓ taken by the room · ME taken by you"
              >
                Pick
              </th>
            )}
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                scope="col"
                title={col.title}
                className={col.numeric ? styles.thNumeric : undefined}
                aria-sort={
                  sortKey === col.key
                    ? sortDir === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : undefined
                }
              >
                <button className={styles.thButton} onClick={() => onToggleSort(col)}>
                  {col.label}
                  <span className={styles.sortMark} aria-hidden="true">
                    {sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : ''}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={span} className={styles.empty}>
                No players match. Clear the search or position filter to see the full list.
              </td>
            </tr>
          )}
          {rows.map((p, i) => {
            const pick = draftMode ? pickById.get(p.id) : undefined;
            const tier = tierMap.get(p.id);
            // A rule between tiers only reads as a break when the rows either
            // side are the same position. In the cross-position view they
            // usually are not, and staying quiet there is correct.
            const previous = rows[i - 1];
            const tierBreak =
              previous !== undefined &&
              previous.positionCode === p.positionCode &&
              tierMap.get(previous.id)?.tier !== tier?.tier;

            return (
              <Fragment key={p.id}>
                <tr
                  className={`${styles.row} ${expandedIds.has(p.id) ? styles.rowOpen : ''} ${
                    pick ? styles.rowDrafted : ''
                  } ${pick?.mine ? styles.rowMine : ''} ${tierBreak ? styles.tierBreak : ''}`}
                  onClick={() => onToggleExpanded(p.id)}
                  // Roving tabindex: one stop for the whole table instead of one
                  // per row. 734 tab stops made the keyboard unusable.
                  tabIndex={i === activeRow ? 0 : -1}
                  onFocus={() => onSetActiveRow(i)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onToggleExpanded(p.id);
                    }
                  }}
                  aria-expanded={expandedIds.has(p.id)}
                >
                  {/* Once a player is gone his board position says nothing --
                      when he went says everything. */}
                  <td className={styles.rank}>{pick ? `#${pick.pick}` : i + 1}</td>
                  <td className={styles.tdNumeric}>
                    {tier ? (
                      <span
                        className={`${styles.tierChip} ${
                          tier.remainingInTier <= 2 ? styles.tierChipThin : ''
                        }`}
                        title={`Tier ${tier.tier} at ${p.positionCode} · ${tier.remainingInTier} left in it`}
                      >
                        T{tier.tier}
                        <span className={styles.tierLeft}>{tier.remainingInTier}</span>
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  {draftMode && (
                    <td className={styles.draftCell}>
                      <span className={styles.draftButtons}>
                        <button
                          className={`${styles.draftButton} ${pick ? styles.draftButtonOn : ''}`}
                          // The row itself expands on click; without this the
                          // toggle would also open the detail panel every time.
                          onClick={(e) => {
                            e.stopPropagation();
                            onMarkTaken(p.id);
                          }}
                          aria-pressed={!!pick}
                          aria-label={`Mark ${p.full_name} taken by another manager`}
                        >
                          ✓
                        </button>
                        <button
                          className={`${styles.draftButton} ${styles.mineButton} ${
                            pick?.mine ? styles.mineButtonOn : ''
                          }`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onMarkMine(p.id);
                          }}
                          aria-pressed={!!pick?.mine}
                          aria-label={`Mark ${p.full_name} as my pick`}
                        >
                          ME
                        </button>
                      </span>
                    </td>
                  )}
                  {COLUMNS.map((col) => (
                    <td key={col.key} className={col.numeric ? styles.tdNumeric : undefined}>
                      {col.render(p)}
                    </td>
                  ))}
                </tr>
                {expandedIds.has(p.id) && (
                  <tr className={styles.detailRow}>
                    <td colSpan={span}>
                      <ExpandedDraftDetail player={p} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
