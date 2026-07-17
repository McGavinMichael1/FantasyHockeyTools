import type {
  AdvisorObjective,
  AdvisorStance,
  KeeperAdvisorResponse,
} from '../../types/keeperAdvisor';
import styles from './KeeperAdvisor.module.css';


const STANCE_LABELS: Record<AdvisorStance, string> = {
  agrees: 'Model agrees',
  diverges: 'Diverges from model',
  conditional: 'Conditional',
};

const OBJECTIVE_LABELS: Record<AdvisorObjective, string> = {
  next_season: 'Next season',
  multi_year: 'Multi-year',
  balanced: 'Balanced',
};


function playerLabel(
  id: number | null,
  playerNames: Record<number, string>,
): string {
  if (id === null) return 'Not applicable';
  return playerNames[id] ?? `Player ${id}`;
}


function formatDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  });
}


function researchStatus(research: KeeperAdvisorResponse['research']): string {
  if (!research.used) return 'No live research needed';
  if (research.current_information_verified) return 'Current information verified';
  return 'Current information could not be verified';
}


export function KeeperAdvisorMessage({
  reply,
  playerNames,
}: {
  reply: KeeperAdvisorResponse;
  playerNames: Record<number, string>;
}) {
  const research = reply.research;
  return (
    <div className={styles.reply}>
      <div className={styles.badges}>
        <span className={`${styles.stanceBadge} ${styles[`stance_${reply.stance}`]}`}>
          {STANCE_LABELS[reply.stance]}
        </span>
        <span className={styles.objectiveBadge}>
          {OBJECTIVE_LABELS[reply.objective]}
        </span>
      </div>

      <p className={styles.answer}>{reply.answer}</p>

      <div className={styles.detail}>
        <h4>Model view</h4>
        <p>{reply.model_view}</p>
      </div>
      <div className={styles.detail}>
        <h4>Recommendation</h4>
        <p>{reply.recommendation}</p>
      </div>

      {reply.stance === 'diverges' && (
        <p className={styles.tradeoff}>
          Model tradeoff: {playerLabel(reply.tradeoff.out_player_id, playerNames)} &rarr;{' '}
          {playerLabel(reply.tradeoff.in_player_id, playerNames)},{' '}
          {reply.tradeoff.projected_keeper_value_cost === null
            ? 'Not applicable'
            : `${reply.tradeoff.projected_keeper_value_cost.toFixed(3)} keeper-value points`}
        </p>
      )}

      {reply.qualitative_factors.length > 0 && (
        <div className={styles.detail}>
          <h4>Qualitative factors</h4>
          <ul>
            {reply.qualitative_factors.map((factor, index) => (
              <li key={index}>{factor}</li>
            ))}
          </ul>
        </div>
      )}

      {reply.uncertainty.length > 0 && (
        <div className={styles.detail}>
          <h4>Uncertainty</h4>
          <ul>
            {reply.uncertainty.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.research}>
        <span className={styles.researchStatus}>{researchStatus(research)}</span>
        {research.sources.length > 0 && (
          <ul className={styles.sources}>
            {research.sources.map((source, index) => (
              <li key={index}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title}
                </a>
                <small>
                  {formatDate(source.published_at) ?? 'Undated'} &middot; retrieved{' '}
                  {formatDate(source.retrieved_at)}
                </small>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
