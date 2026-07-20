'use client';

import { Fragment, useEffect, useMemo, useState } from 'react';
import type { DraftPlayer, Position } from '@/types/player';
import {
  loadDrafted,
  positionalRuns,
  saveDrafted,
  withLiveVorp,
} from '@/lib/liveDraft';
import { Headshot, PositionChip, ScoreMeter } from './bits';
import styles from './RinkTable.module.css';
import bitStyles from './bits.module.css';

type SortDir = 'asc' | 'desc';

interface Column {
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
    <span
      className={`${bitStyles.delta} ${cls}`}
      title="Projected FP per game vs. last season"
    >
      {label}
    </span>
  );
}

const COLUMNS: Column[] = [
  {
    key: 'full_name',
    label: 'Player',
    sortValue: (p) => p.full_name,
    render: (p) => (
      <span className={styles.playerCell}>
        <Headshot src={p.headshot} name={p.full_name} size={32} />
        <span className={styles.playerName}>{p.full_name}</span>
        <PositionChip position={p.positionCode} />
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
    title: 'Projected season total (FP/game × projected games: 78 for skaters; weighted recent starts for goalies)',
    numeric: true,
    sortValue: (p) => p.projected_total,
    render: (p) => p.projected_total.toFixed(0),
  },
  {
    key: 'vorp',
    label: 'VORP',
    title: 'Value over replacement player (projected FP above a replacement-level pick at the position)',
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
      p.confidence === null ? (
        '—'
      ) : (
        <ScoreMeter value={p.confidence / 100} tone="neutral" />
      ),
  },
];

function ExpandedDraftDetail({ player }: { player: DraftPlayer }) {
  return (
    <div className={styles.detail}>
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

export default function DraftBoard({ players }: { players: DraftPlayer[] }) {
  const [sortKey, setSortKey] = useState('vorp');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [position, setPosition] = useState<Position | 'ALL'>('ALL');
  const [query, setQuery] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [draftMode, setDraftMode] = useState(false);
  const [drafted, setDrafted] = useState<Set<number>>(() => new Set());

  // Hydrate after mount, not during render: localStorage does not exist on the
  // server, and seeding state from it directly would mismatch the SSR output.
  useEffect(() => {
    const stored = loadDrafted();
    if (stored.size > 0) {
      setDrafted(stored);
      setDraftMode(true);
    }
  }, []);

  function toggleDrafted(id: number) {
    setDrafted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveDrafted(next);
      return next;
    });
  }

  function resetDraft() {
    const empty = new Set<number>();
    saveDrafted(empty);
    setDrafted(empty);
  }

  // VORP is recomputed against whoever is left, so the ranking re-sorts itself
  // as the pool thins. Outside draft mode the exported preseason value stands.
  const board = useMemo(
    () => (draftMode ? withLiveVorp(players, drafted) : players),
    [players, drafted, draftMode],
  );

  const runs = useMemo(
    () => (draftMode ? positionalRuns(players, drafted) : []),
    [players, drafted, draftMode],
  );

  const rows = useMemo(() => {
    let data = board;
    if (position !== 'ALL') data = data.filter((p) => p.positionCode === position);
    if (query) {
      const q = query.toLowerCase();
      data = data.filter((p) => p.full_name.toLowerCase().includes(q));
    }
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (col?.sortValue) {
      const dir = sortDir === 'asc' ? 1 : -1;
      data = [...data].sort((a, b) => {
        // In draft mode the top row must be the best player still AVAILABLE --
        // that is the question being asked on the clock. Drafted players stay
        // listed (seeing who is gone is part of reading the room) but sink.
        if (draftMode) {
          const aGone = drafted.has(a.id) ? 1 : 0;
          const bGone = drafted.has(b.id) ? 1 : 0;
          if (aGone !== bGone) return aGone - bGone;
        }
        const av = col.sortValue!(a);
        const bv = col.sortValue!(b);
        if (typeof av === 'string' || typeof bv === 'string') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return (av - (bv as number)) * dir;
      });
    }
    return data;
  }, [board, position, query, sortKey, sortDir, draftMode, drafted]);

  function toggleSort(col: Column) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(col.key);
      setSortDir(col.key === 'full_name' ? 'asc' : 'desc');
    }
  }

  const positions: (Position | 'ALL')[] = ['ALL', 'C', 'L', 'R', 'D', 'G'];

  return (
    <section className={styles.section} aria-label="Draft board">
      <div className={styles.controls}>
        <input
          type="search"
          className={styles.search}
          placeholder="Search players"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search players by name"
        />
        <div className={styles.positions} role="group" aria-label="Filter by position">
          {positions.map((pos) => (
            <button
              key={pos}
              className={`${styles.posButton} ${position === pos ? styles.posActive : ''}`}
              onClick={() => setPosition(pos)}
              aria-pressed={position === pos}
            >
              {pos}
            </button>
          ))}
        </div>
        <button
          className={`${styles.draftToggle} ${draftMode ? styles.draftToggleOn : ''}`}
          onClick={() => setDraftMode((on) => !on)}
          aria-pressed={draftMode}
          title="Mark players as drafted and recompute VORP against who is left"
        >
          Draft mode
        </button>
        {draftMode && drafted.size > 0 && (
          <button className={styles.resetButton} onClick={resetDraft}>
            Clear {drafted.size}
          </button>
        )}
        <span className={styles.count}>
          {rows.length} player{rows.length === 1 ? '' : 's'}
        </span>
      </div>

      {draftMode && (
        <div className={styles.runs} aria-label="Positional runs">
          {runs.map((run) => (
            <span
              key={run.position}
              className={styles.run}
              title={`${run.taken} of the top ${run.total} ${run.position} drafted`}
            >
              <PositionChip position={run.position} />
              <span className={styles.runTrack}>
                <span
                  className={`${styles.runBar} ${run.depleted >= 0.5 ? styles.runBarHot : ''}`}
                  style={{ width: `${Math.round(run.depleted * 100)}%` }}
                />
              </span>
              <span>
                {run.taken}/{run.total}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.thRank} scope="col">
                No.
              </th>
              {draftMode && (
                <th className={styles.draftCell} scope="col" title="Mark as drafted">
                  ✓
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
                  <button className={styles.thButton} onClick={() => toggleSort(col)}>
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
                <td colSpan={COLUMNS.length + (draftMode ? 2 : 1)} className={styles.empty}>
                  No players match. Clear the search or position filter to see the
                  full list.
                </td>
              </tr>
            )}
            {rows.map((p, i) => (
              <Fragment key={p.id}>
                <tr
                  className={`${styles.row} ${expandedId === p.id ? styles.rowOpen : ''} ${
                    draftMode && drafted.has(p.id) ? styles.rowDrafted : ''
                  }`}
                  onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setExpandedId(expandedId === p.id ? null : p.id);
                    }
                  }}
                  aria-expanded={expandedId === p.id}
                >
                  <td className={styles.rank}>{i + 1}</td>
                  {draftMode && (
                    <td className={styles.draftCell}>
                      <button
                        className={`${styles.draftButton} ${
                          drafted.has(p.id) ? styles.draftButtonOn : ''
                        }`}
                        // The row itself expands on click; without this the
                        // toggle would also open the detail panel every time.
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleDrafted(p.id);
                        }}
                        aria-pressed={drafted.has(p.id)}
                        aria-label={`Mark ${p.full_name} as drafted`}
                      >
                        ✓
                      </button>
                    </td>
                  )}
                  {COLUMNS.map((col) => (
                    <td
                      key={col.key}
                      className={col.numeric ? styles.tdNumeric : undefined}
                    >
                      {col.render(p)}
                    </td>
                  ))}
                </tr>
                {expandedId === p.id && (
                  <tr className={styles.detailRow}>
                    <td colSpan={COLUMNS.length + (draftMode ? 2 : 1)}>
                      <ExpandedDraftDetail player={p} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
