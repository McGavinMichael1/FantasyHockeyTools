'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import type { Player, DraftPlayer, KeeperSection, Position } from '@/types/player';
import ThreeStars from '@/components/rink/ThreeStars';
import RinkTable from '@/components/rink/RinkTable';
import DraftBoard from '@/components/rink/DraftBoard';
import styles from './page.module.css';

interface ApiResponse {
  pickups: Player[];
  cooling: Player[];
  draft: DraftPlayer[];
  // The ranks the exported vorp was computed with. Absent in snapshots taken
  // before demand-aware ranks existed; DraftBoard falls back to the base ranks.
  draft_replacement_ranks?: Record<Position, number>;
  keeper?: KeeperSection | null;
  dataAge?: string;
  error?: string;
}

type Tab = 'pickups' | 'cooling' | 'draft';

/** "130.6h ago" from the API → "5d old"; unparseable strings pass through. */
function formatAge(age?: string): string | undefined {
  if (!age) return undefined;
  const hours = parseFloat(age);
  if (Number.isNaN(hours)) return age;
  if (hours < 1) return 'fresh';
  if (hours < 48) return `${Math.round(hours)}h old`;
  return `${Math.round(hours / 24)}d old`;
}

export default function RinkPage() {
  const [tab, setTab] = useState<Tab>('pickups');
  const [data, setData] = useState<ApiResponse>({ pickups: [], cooling: [], draft: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get('view');
    if (view === 'cold' || view === 'cooling') setTab('cooling');
    if (view === 'draft') setTab('draft');
  }, []);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/players');
        const json: ApiResponse = await res.json();
        if (json.error && json.pickups.length === 0) {
          setError(json.error);
        } else {
          // exports written before the draft section shipped lack `draft`
          setData({ ...json, draft: json.draft ?? [] });
          setError(null);
        }
      } catch {
        setError('Could not reach the data endpoint.');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  const tone = tab === 'pickups' ? 'hot' : 'cold';

  const players = useMemo(() => {
    if (tab === 'draft') return [];
    const list = tab === 'pickups' ? data.pickups : data.cooling;
    const key = tab === 'pickups' ? 'final_score' : 'cooling_score';
    return [...list].sort((a, b) => b[key] - a[key]);
  }, [data, tab]);

  return (
    <div className={styles.page}>
      <div className={styles.redline} aria-hidden="true" />

      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <span className={styles.brand}>
            <span className={styles.puck} aria-hidden="true" />
            The Rink
          </span>

          <nav className={styles.tabs} aria-label="View">
            <button
              className={`${styles.tab} ${tab === 'pickups' ? styles.tabActive : ''}`}
              onClick={() => setTab('pickups')}
              aria-pressed={tab === 'pickups'}
            >
              Waiver wire
            </button>
            <button
              className={`${styles.tab} ${tab === 'cooling' ? styles.tabActiveCold : ''}`}
              onClick={() => setTab('cooling')}
              aria-pressed={tab === 'cooling'}
            >
              Cold streaks
            </button>
            <button
              className={`${styles.tab} ${tab === 'draft' ? styles.tabActive : ''}`}
              onClick={() => setTab('draft')}
              aria-pressed={tab === 'draft'}
            >
              Draft board
            </button>
            <Link className={styles.tab} href="/keeper">
              Keeper board
            </Link>
          </nav>

          <div className={styles.meta}>
            {data.dataAge && (
              <span className={styles.dataAge}>Data {formatAge(data.dataAge)}</span>
            )}
          </div>
        </div>
      </header>

      <main>
        {loading ? (
          <div className={styles.state}>
            <div className={styles.zamboni} aria-hidden="true" />
            <p>Cutting fresh ice…</p>
          </div>
        ) : error ? (
          <div className={styles.state}>
            <p className={styles.stateTitle}>No player data yet</p>
            <p>{error}</p>
            <p>
              Generate it from the project root, then reload:
              <code className={styles.code}>python api_export.py</code>
            </p>
          </div>
        ) : tab === 'draft' ? (
          data.draft.length === 0 ? (
            <div className={styles.state}>
              <p className={styles.stateTitle}>No draft rankings yet</p>
              <p>
                Build them from the project root, then reload:
                <code className={styles.code}>python main.py draft</code>
                <code className={styles.code}>python api_export.py</code>
              </p>
            </div>
          ) : (
            <DraftBoard players={data.draft} replacementRanks={data.draft_replacement_ranks} />
          )
        ) : (
          <>
            <ThreeStars players={players} tone={tone} />
            <RinkTable players={players} tone={tone} />
          </>
        )}
      </main>
    </div>
  );
}
