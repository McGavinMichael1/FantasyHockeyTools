'use client';

import { useEffect, useMemo, useState } from 'react';
import type { Player } from '@/types/player';
import ThreeStars from '@/components/rink/ThreeStars';
import RinkTable from '@/components/rink/RinkTable';
import styles from './page.module.css';

interface ApiResponse {
  pickups: Player[];
  cooling: Player[];
  dataAge?: string;
  error?: string;
}

type Tab = 'pickups' | 'cooling';

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
  const [data, setData] = useState<ApiResponse>({ pickups: [], cooling: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const view = new URLSearchParams(window.location.search).get('view');
    if (view === 'cold' || view === 'cooling') setTab('cooling');
  }, []);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/players');
        const json: ApiResponse = await res.json();
        if (json.error && json.pickups.length === 0) {
          setError(json.error);
        } else {
          setData(json);
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
