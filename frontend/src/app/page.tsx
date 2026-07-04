'use client';

import { useState, useEffect } from 'react';
import Header from '@/components/Header';
import PlayerGrid from '@/components/PlayerGrid';
import type { Player } from '@/types/player';
import styles from './page.module.css';

interface ApiResponse {
  pickups: Player[];
  cooling: Player[];
  dataAge?: string;
  error?: string;
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<'pickups' | 'cooling'>('pickups');
  const [data, setData] = useState<ApiResponse>({ pickups: [], cooling: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch('/api/players');
        const json = await res.json();

        if (json.error && json.pickups.length === 0) {
          setError(json.error);
        } else {
          setData(json);
          setError(null);
        }
      } catch (err) {
        setError('Failed to load data');
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  const players = activeTab === 'pickups' ? data.pickups : data.cooling;

  return (
    <div className={styles.app}>
      <Header
        activeTab={activeTab}
        onTabChange={setActiveTab}
        dataAge={data.dataAge}
      />

      <main className={styles.main}>
        {loading ? (
          <div className={styles.loading}>
            <div className={styles.spinner} />
            <span>Loading player data...</span>
          </div>
        ) : error ? (
          <div className={styles.error}>
            <div className={styles.errorIcon}>!</div>
            <p>{error}</p>
            <code>python api_export.py</code>
          </div>
        ) : (
          <PlayerGrid players={players} mode={activeTab} />
        )}
      </main>
    </div>
  );
}
