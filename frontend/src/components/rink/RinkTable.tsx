'use client';

import { Fragment, useMemo, useState } from 'react';
import type { Player, Position } from '@/types/player';
import {
  Headshot,
  PaceDeltaChip,
  PositionChip,
  ScoreMeter,
  last5Pace,
  paceDelta,
  type Tone,
} from './bits';
import styles from './RinkTable.module.css';

type SortDir = 'asc' | 'desc';

interface Column {
  key: string;
  label: string;
  title?: string;
  numeric?: boolean;
  sortValue?: (p: Player) => number | string;
  render: (p: Player) => React.ReactNode;
}

function buildColumns(tone: Tone): Column[] {
  const scoreKey = tone === 'hot' ? 'final_score' : 'cooling_score';
  return [
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
    { key: 'gamesPlayed', label: 'GP', title: 'Games played', numeric: true, sortValue: (p) => p.gamesPlayed, render: (p) => p.gamesPlayed },
    { key: 'goals', label: 'G', title: 'Goals', numeric: true, sortValue: (p) => p.goals, render: (p) => p.goals },
    { key: 'assists', label: 'A', title: 'Assists', numeric: true, sortValue: (p) => p.assists, render: (p) => p.assists },
    { key: 'points', label: 'PTS', title: 'Points', numeric: true, sortValue: (p) => p.points, render: (p) => p.points },
    {
      key: 'plusMinus',
      label: '+/−',
      title: 'Plus-minus',
      numeric: true,
      sortValue: (p) => p.plusMinus,
      render: (p) => (p.plusMinus > 0 ? `+${p.plusMinus}` : p.plusMinus),
    },
    { key: 'powerPlayPoints', label: 'PPP', title: 'Power-play points', numeric: true, sortValue: (p) => p.powerPlayPoints, render: (p) => p.powerPlayPoints },
    { key: 'shots', label: 'SOG', title: 'Shots on goal', numeric: true, sortValue: (p) => p.shots, render: (p) => p.shots },
    {
      key: 'fantasyPoints',
      label: 'FP',
      title: 'Season fantasy points',
      numeric: true,
      sortValue: (p) => p.fantasyPoints,
      render: (p) => p.fantasyPoints.toFixed(1),
    },
    {
      key: 'season_ppg',
      label: 'FP/G',
      title: 'Fantasy points per game, season',
      numeric: true,
      sortValue: (p) => p.season_ppg,
      render: (p) => p.season_ppg.toFixed(2),
    },
    {
      key: 'last5',
      label: 'L5 FP/G',
      title: 'Fantasy points per game, last 5',
      numeric: true,
      sortValue: last5Pace,
      render: (p) => last5Pace(p).toFixed(2),
    },
    {
      key: 'pace',
      label: 'Pace Δ',
      title: 'Last-5 pace minus season pace',
      numeric: true,
      sortValue: paceDelta,
      render: (p) => <PaceDeltaChip player={p} />,
    },
    {
      key: scoreKey,
      label: tone === 'hot' ? 'Heat' : 'Chill',
      title:
        tone === 'hot'
          ? 'Blended pickup score (model + recent pace)'
          : 'Cooling score — higher means a steeper decline',
      numeric: true,
      sortValue: (p) => (tone === 'hot' ? p.final_score : p.cooling_score),
      render: (p) => (
        <ScoreMeter
          value={tone === 'hot' ? p.final_score : p.cooling_score}
          tone={tone}
        />
      ),
    },
  ];
}

function ExpandedDetail({ player, tone }: { player: Player; tone: Tone }) {
  const season = player.season_ppg;
  const recent = last5Pace(player);
  const max = Math.max(season, recent, 0.001);

  return (
    <div className={styles.detail}>
      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Pace, FP per game</h4>
        <div className={styles.paceRow}>
          <span className={styles.paceLabel}>Season</span>
          <span className={styles.paceTrack}>
            <span
              className={styles.paceBarNeutral}
              style={{ width: `${(season / max) * 100}%` }}
            />
          </span>
          <span className={styles.paceValue}>{season.toFixed(2)}</span>
        </div>
        <div className={styles.paceRow}>
          <span className={styles.paceLabel}>Last 5</span>
          <span className={styles.paceTrack}>
            <span
              className={tone === 'hot' ? styles.paceBarHot : styles.paceBarCold}
              style={{ width: `${(recent / max) * 100}%` }}
            />
          </span>
          <span className={styles.paceValue}>{recent.toFixed(2)}</span>
        </div>
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Last 5 games</h4>
        <dl className={styles.detailStats}>
          <div><dt>Goals</dt><dd>{player.last5_goals}</dd></div>
          <div><dt>Assists</dt><dd>{player.last5_assists}</dd></div>
          <div><dt>Points</dt><dd>{player.last5_points}</dd></div>
          <div><dt>Fantasy</dt><dd>{player.last5_fantasyPoints.toFixed(1)}</dd></div>
        </dl>
      </div>

      <div className={styles.detailBlock}>
        <h4 className={styles.detailHeading}>Model scores</h4>
        <dl className={styles.detailStats}>
          <div><dt>ML heat</dt><dd>{Math.round(player.ml_score * 100)}</dd></div>
          <div><dt>Blend</dt><dd>{Math.round(player.final_score * 100)}</dd></div>
          <div><dt>Cooling</dt><dd>{Math.round(player.cooling_score * 100)}</dd></div>
          <div><dt>Avg TOI</dt><dd>{player.avgToi}</dd></div>
        </dl>
        {player.rostered && <span className={styles.rosteredChip}>On a roster</span>}
      </div>
    </div>
  );
}

export default function RinkTable({
  players,
  tone,
}: {
  players: Player[];
  tone: Tone;
}) {
  const columns = useMemo(() => buildColumns(tone), [tone]);
  const defaultSort = tone === 'hot' ? 'final_score' : 'cooling_score';

  const [sortKey, setSortKey] = useState(defaultSort);
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [position, setPosition] = useState<Position | 'ALL'>('ALL');
  const [query, setQuery] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const rows = useMemo(() => {
    let data = players;
    if (position !== 'ALL') data = data.filter((p) => p.positionCode === position);
    if (query) {
      const q = query.toLowerCase();
      data = data.filter((p) => p.full_name.toLowerCase().includes(q));
    }
    const col = columns.find((c) => c.key === sortKey);
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
  }, [players, position, query, sortKey, sortDir, columns]);

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
    <section className={styles.section} aria-label="All players">
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
              {columns.map((col) => (
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
                <td colSpan={columns.length + 1} className={styles.empty}>
                  No players match. Clear the search or position filter to see the
                  full list.
                </td>
              </tr>
            )}
            {rows.map((p, i) => (
              <Fragment key={p.id}>
                <tr
                  className={`${styles.row} ${expandedId === p.id ? styles.rowOpen : ''}`}
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
                  {columns.map((col) => (
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
                    <td colSpan={columns.length + 1}>
                      <ExpandedDetail player={p} tone={tone} />
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
