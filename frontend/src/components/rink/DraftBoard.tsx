'use client';

import { useMemo, useState } from 'react';
import type { DraftPlayer, Position } from '@/types/player';
import { Headshot, PositionChip } from './bits';
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
    title: 'Projected season total (FP per game × 78 games)',
    numeric: true,
    sortValue: (p) => p.projected_total,
    render: (p) => p.projected_total.toFixed(0),
  },
  {
    key: 'delta_vs_last',
    label: 'Δ',
    title: 'Projected minus last-season FP per game',
    numeric: true,
    sortValue: (p) => p.delta_vs_last,
    render: (p) => <ProjectionDeltaChip value={p.delta_vs_last} />,
  },
];

export default function DraftBoard({ players }: { players: DraftPlayer[] }) {
  const [sortKey, setSortKey] = useState('projected_fpPerGame');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [position, setPosition] = useState<Position | 'ALL'>('ALL');
  const [query, setQuery] = useState('');

  const rows = useMemo(() => {
    let data = players;
    if (position !== 'ALL') data = data.filter((p) => p.positionCode === position);
    if (query) {
      const q = query.toLowerCase();
      data = data.filter((p) => p.full_name.toLowerCase().includes(q));
    }
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (col?.sortValue) {
      const dir = sortDir === 'asc' ? 1 : -1;
      data = [...data].sort((a, b) => {
        const av = col.sortValue!(a);
        const bv = col.sortValue!(b);
        if (typeof av === 'string' || typeof bv === 'string') {
          return String(av).localeCompare(String(bv)) * dir;
        }
        return (av - (bv as number)) * dir;
      });
    }
    return data;
  }, [players, position, query, sortKey, sortDir]);

  function toggleSort(col: Column) {
    if (!col.sortValue) return;
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(col.key);
      setSortDir(col.key === 'full_name' ? 'asc' : 'desc');
    }
  }

  const positions: (Position | 'ALL')[] = ['ALL', 'C', 'L', 'R', 'D'];

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
        <span className={styles.count}>
          {rows.length} skater{rows.length === 1 ? '' : 's'}
        </span>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.thRank} scope="col">
                No.
              </th>
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
                <td colSpan={COLUMNS.length + 1} className={styles.empty}>
                  No players match. Clear the search or position filter to see the
                  full list.
                </td>
              </tr>
            )}
            {rows.map((p, i) => (
              <tr key={p.id} className={styles.row}>
                <td className={styles.rank}>{i + 1}</td>
                {COLUMNS.map((col) => (
                  <td
                    key={col.key}
                    className={col.numeric ? styles.tdNumeric : undefined}
                  >
                    {col.render(p)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
