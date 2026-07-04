'use client';

import { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
  SortingState,
  ColumnFiltersState,
} from '@tanstack/react-table';
import type { Player, Position } from '@/types/player';
import styles from './PlayerGrid.module.css';

const columnHelper = createColumnHelper<Player>();

function PlayerHeadshot({ src, name }: { src: string; name: string }) {
  const [error, setError] = useState(false);

  if (error || !src) {
    return (
      <div className={styles.headshotPlaceholder}>
        {name.split(' ').map(n => n[0]).join('').slice(0, 2)}
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={name}
      className={styles.headshot}
      onError={() => setError(true)}
      loading="lazy"
    />
  );
}

function ScoreCell({ value, type }: { value: number; type: 'heating' | 'cooling' | 'neutral' }) {
  const pct = Math.round(value * 100);
  const className =
    type === 'heating'
      ? styles.heating
      : type === 'cooling'
        ? styles.cooling
        : styles.neutral;

  return (
    <div className={`${styles.scoreCell} ${className}`}>
      <div className={styles.scoreBar} style={{ width: `${pct}%` }} />
      <span className={styles.scoreValue}>{pct}</span>
    </div>
  );
}

function PositionBadge({ position }: { position: Position }) {
  const colorMap: Record<Position, string> = {
    C: '#38bdf8',
    L: '#a78bfa',
    R: '#f472b6',
    D: '#fbbf24',
  };

  return (
    <span className={styles.positionBadge} style={{ borderColor: colorMap[position] }}>
      {position}
    </span>
  );
}

interface PlayerGridProps {
  players: Player[];
  mode: 'pickups' | 'cooling';
}

export default function PlayerGrid({ players, mode }: PlayerGridProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: mode === 'pickups' ? 'final_score' : 'cooling_score', desc: true },
  ]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [positionFilter, setPositionFilter] = useState<Position | 'ALL'>('ALL');
  const [nameFilter, setNameFilter] = useState('');

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'rank',
        header: '#',
        cell: (info) => (
          <span className={styles.rank}>{info.row.index + 1}</span>
        ),
        size: 40,
      }),
      columnHelper.accessor('headshot', {
        header: '',
        cell: (info) => (
          <div className={styles.headshotCell}>
            <PlayerHeadshot
              src={info.getValue()}
              name={info.row.original.full_name}
            />
          </div>
        ),
        size: 48,
        enableSorting: false,
      }),
      columnHelper.accessor('full_name', {
        header: 'Player',
        cell: (info) => (
          <div className={styles.playerName}>
            <span>{info.getValue()}</span>
            <span className={styles.sweaterNumber}>#{info.row.original.sweaterNumber}</span>
          </div>
        ),
        size: 180,
      }),
      columnHelper.accessor('positionCode', {
        header: 'Pos',
        cell: (info) => <PositionBadge position={info.getValue()} />,
        size: 50,
      }),
      columnHelper.accessor('gamesPlayed', {
        header: 'GP',
        size: 50,
      }),
      columnHelper.accessor('goals', {
        header: 'G',
        size: 45,
      }),
      columnHelper.accessor('assists', {
        header: 'A',
        size: 45,
      }),
      columnHelper.accessor('points', {
        header: 'PTS',
        size: 50,
      }),
      columnHelper.accessor('plusMinus', {
        header: '+/-',
        cell: (info) => {
          const val = info.getValue();
          return (
            <span className={val > 0 ? styles.positive : val < 0 ? styles.negative : ''}>
              {val > 0 ? `+${val}` : val}
            </span>
          );
        },
        size: 50,
      }),
      columnHelper.accessor('powerPlayPoints', {
        header: 'PPP',
        size: 50,
      }),
      columnHelper.accessor('shots', {
        header: 'SOG',
        size: 50,
      }),
      columnHelper.accessor('fantasyPoints', {
        header: 'FPTS',
        cell: (info) => info.getValue().toFixed(1),
        size: 60,
      }),
      columnHelper.accessor('season_ppg', {
        header: 'PPG',
        cell: (info) => info.getValue().toFixed(2),
        size: 55,
      }),
      columnHelper.accessor('last5_fantasyPoints', {
        header: 'L5',
        cell: (info) => info.getValue().toFixed(1),
        size: 55,
      }),
      ...(mode === 'pickups'
        ? [
            columnHelper.accessor('ml_score', {
              header: 'Heat',
              cell: (info) => <ScoreCell value={info.getValue()} type="heating" />,
              size: 70,
            }),
            columnHelper.accessor('final_score', {
              header: 'Score',
              cell: (info) => <ScoreCell value={info.getValue()} type="neutral" />,
              size: 70,
            }),
          ]
        : [
            columnHelper.accessor('cooling_score', {
              header: 'Cool',
              cell: (info) => <ScoreCell value={info.getValue()} type="cooling" />,
              size: 70,
            }),
          ]),
    ],
    [mode]
  );

  const filteredData = useMemo(() => {
    let data = players;
    if (positionFilter !== 'ALL') {
      data = data.filter((p) => p.positionCode === positionFilter);
    }
    if (nameFilter) {
      const query = nameFilter.toLowerCase();
      data = data.filter((p) => p.full_name.toLowerCase().includes(query));
    }
    return data;
  }, [players, positionFilter, nameFilter]);

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, columnFilters },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const positions: (Position | 'ALL')[] = ['ALL', 'C', 'L', 'R', 'D'];

  return (
    <div className={styles.container}>
      <div className={styles.filters}>
        <div className={styles.searchWrapper}>
          <input
            type="text"
            placeholder="Search players..."
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            className={styles.searchInput}
          />
        </div>
        <div className={styles.positionFilters}>
          {positions.map((pos) => (
            <button
              key={pos}
              className={`${styles.positionButton} ${positionFilter === pos ? styles.active : ''}`}
              onClick={() => setPositionFilter(pos)}
            >
              {pos}
            </button>
          ))}
        </div>
        <div className={styles.resultCount}>
          {filteredData.length} player{filteredData.length !== 1 ? 's' : ''}
        </div>
      </div>

      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className={header.column.getCanSort() ? styles.sortable : ''}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    <div className={styles.headerContent}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() && (
                        <span className={styles.sortIndicator}>
                          {header.column.getIsSorted() === 'asc' ? '▲' : '▼'}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} style={{ width: cell.column.getSize() }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
