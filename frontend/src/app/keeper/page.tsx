'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import type { KeeperRecommendation, KeeperSection } from '@/types/player';
import { Headshot, PositionChip, ScoreMeter } from '@/components/rink/bits';
import styles from './page.module.css';

interface ApiResponse {
  keeper?: KeeperSection | null;
  error?: string;
}

function formatDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function KeeperCard({ player }: { player: KeeperRecommendation }) {
  return (
    <article className={styles.card}>
      <div className={styles.cardTopline}>
        <span className={styles.rank}>Keep {player.keeper_rank}</span>
        <span className={styles.round}>Round {player.assigned_round}</span>
      </div>

      <div className={styles.playerHeading}>
        <Headshot src={player.headshot ?? ''} name={player.full_name} size={54} />
        <div>
          <div className={styles.nameRow}>
            <h2>{player.full_name}</h2>
            <PositionChip position={player.positionCode} />
          </div>
          <p>Protect for a round-{player.assigned_round} pick</p>
        </div>
      </div>

      <div className={styles.valueBlock}>
        <span>Net keeper value</span>
        <strong>+{player.net_keeper_value.toFixed(1)}</strong>
        <small>{player.raw_keeper_value.toFixed(1)} above replacement &minus; {player.pick_cost.toFixed(1)} pick cost</small>
      </div>

      <dl className={styles.stats}>
        <div>
          <dt>Last FP/G</dt>
          <dd>{player.last_fpPerGame.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Projected FP/G</dt>
          <dd>{player.projected_fpPerGame.toFixed(2)}</dd>
        </div>
        <div>
          <dt>78-game proj.</dt>
          <dd>{player.projected_total.toFixed(0)}</dd>
        </div>
        <div>
          <dt>GP</dt>
          <dd>{player.gamesPlayed}</dd>
        </div>
      </dl>

      <div className={styles.confidence}>
        <span>Model confidence</span>
        {player.confidence === null ? (
          <em>&mdash;</em>
        ) : (
          <ScoreMeter value={player.confidence / 100} tone="neutral" />
        )}
      </div>
    </article>
  );
}

export default function KeeperPage() {
  const [keeper, setKeeper] = useState<KeeperSection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadKeeperBoard() {
      try {
        const response = await fetch('/api/players');
        const payload: ApiResponse = await response.json();
        if (payload.error && !payload.keeper) {
          setError(payload.error);
        } else {
          setKeeper(payload.keeper ?? null);
        }
      } catch {
        setError('Could not reach the data endpoint.');
      } finally {
        setLoading(false);
      }
    }
    loadKeeperBoard();
  }, []);

  const summaryDate = formatDate(keeper?.summary_generated_at ?? null);

  return (
    <div className={styles.page}>
      <div className={styles.redline} aria-hidden="true" />
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <Link className={styles.brand} href="/">
            <span className={styles.puck} aria-hidden="true" />
            The Rink
          </Link>
          <span className={styles.sectionName}>Keeper board</span>
          <Link className={styles.backLink} href="/">
            Back to tools <span aria-hidden="true">&rarr;</span>
          </Link>
        </div>
      </header>

      <main className={styles.main}>
        {loading ? (
          <div className={styles.state}>
            <div className={styles.zamboni} aria-hidden="true" />
            <p>Setting the keeper board&hellip;</p>
          </div>
        ) : error ? (
          <div className={styles.state}>
            <p className={styles.stateTitle}>Keeper data is unavailable</p>
            <p>{error}</p>
          </div>
        ) : !keeper || keeper.recommendations.length === 0 ? (
          <div className={styles.state}>
            <p className={styles.stateTitle}>No keeper board yet</p>
            <p>Build your roster analysis, then export its cached result for this page.</p>
            <code className={styles.code}>{'.\\.venv\\Scripts\\python.exe main.py keeper'}</code>
            <code className={styles.code}>{'.\\.venv\\Scripts\\python.exe scripts\\build_keeper_summary.py'}</code>
            <code className={styles.code}>{'.\\.venv\\Scripts\\python.exe api_export.py --keeper-only'}</code>
          </div>
        ) : (
          <>
            <section className={styles.hero}>
              <div>
                <p className={styles.kicker}>{keeper.season} &middot; Four skaters</p>
                <h1>Spend your last picks where they become an advantage.</h1>
                <p className={styles.intro}>
                  Each recommendation measures a player&apos;s projected edge over position
                  replacement against the pick you give up to keep him.
                </p>
              </div>
              <div className={styles.heroStamp}>
                <span>Keeper format</span>
                <strong>4</strong>
                <small>skaters only</small>
              </div>
            </section>

            <section className={styles.pickStrip} aria-label="Assigned keeper costs">
              <div className={styles.pickStripLabel}>
                <span>The price</span>
                <strong>Your last four picks</strong>
              </div>
              <div className={styles.pickSlots}>
                {[18, 17, 16, 15].map((round) => {
                  const player = keeper.recommendations.find(
                    (candidate) => candidate.assigned_round === round,
                  );
                  return (
                    <div className={styles.pickSlot} key={round}>
                      <span>Round {round}</span>
                      <strong>{player?.full_name ?? 'Open'}</strong>
                      <small>{player ? `${player.pick_cost.toFixed(0)} FP cost` : 'No keeper'}</small>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className={styles.summary} aria-label="Cached keeper explanation">
              <div className={styles.summaryMark}>K</div>
              <div>
                <div className={styles.summaryHeading}>
                  <span>Cached manager note</span>
                  {summaryDate && <small>Generated {summaryDate}</small>}
                </div>
                {keeper.summary ? (
                  <p>{keeper.summary}</p>
                ) : (
                  <>
                    <p className={styles.summaryEmpty}>
                      The rankings are ready. Generate the one-time explanation when you&apos;re
                      ready; it will be reused for the rest of this season.
                    </p>
                    <code className={styles.code}>{'.\\.venv\\Scripts\\python.exe scripts\\build_keeper_summary.py'}</code>
                  </>
                )}
              </div>
            </section>

            <section className={styles.cards} aria-label="Recommended keeper cards">
              {keeper.recommendations.map((player) => (
                <KeeperCard key={player.id ?? player.full_name} player={player} />
              ))}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
