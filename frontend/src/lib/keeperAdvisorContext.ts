import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import type {
  AdvisorContext,
  AdvisorContextPlayer,
  ScenarioSet,
  TurnClassification,
} from '../types/keeperAdvisor';


export const ADVISOR_CONTEXT_PATH = join(
  process.cwd(), '..', 'data', 'processed', 'keeper_advisor_context.json',
);


function isContext(value: unknown): value is AdvisorContext {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const context = value as Record<string, unknown>;
  return context.schema_version === 1 && typeof context.context_id === 'string' &&
    typeof context.generated_at === 'string' && typeof context.season === 'string' &&
    Array.isArray(context.official_top_four) && context.official_top_four.length === 4 &&
    Array.isArray(context.roster) &&
    typeof context.scenario_data === 'object' && context.scenario_data !== null &&
    Array.isArray((context.scenario_data as { sets?: unknown }).sets);
}


export function loadAdvisorContext(path = ADVISOR_CONTEXT_PATH): AdvisorContext {
  const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'));
  if (!isContext(parsed)) {
    throw new Error('keeper advisor context has an unsupported or malformed schema');
  }
  return parsed;
}


export function rosterIndex(context: AdvisorContext) {
  return context.roster.map((player) => ({
    player_id: player.player_id,
    name: player.full_name ?? player.yahoo_name,
    position: player.position,
    age: player.age,
    is_recommended: player.is_recommended,
    keeper_rank: player.keeper_rank,
    raw_keeper_value: player.raw_keeper_value,
    projected_total: player.projected_total,
    match_status: player.match_status,
  }));
}


export function selectPlayerDossiers(
  context: AdvisorContext,
  ids: number[],
): AdvisorContextPlayer[] {
  const requested = new Set(ids);
  return context.roster.filter(
    (player) => player.player_id !== null && requested.has(player.player_id),
  );
}


export function bestScenario(
  context: AdvisorContext,
  lockedIds: number[],
  excludedIds: number[],
): ScenarioSet | null {
  const locked = new Set(lockedIds);
  const excluded = new Set(excludedIds);
  const eligible = context.scenario_data.sets.filter((scenario) =>
    [...locked].every((id) => scenario.player_ids.includes(id)) &&
    scenario.player_ids.every((id) => !excluded.has(id)),
  );
  eligible.sort((left, right) =>
    right.total_model_value - left.total_model_value ||
    left.player_ids.join(',').localeCompare(right.player_ids.join(',')),
  );
  return eligible[0] ?? null;
}


export function findScenario(
  context: AdvisorContext,
  playerIds: number[],
): ScenarioSet | null {
  const key = [...playerIds].sort((a, b) => a - b).join(',');
  return context.scenario_data.sets.find(
    (scenario) => scenario.player_ids.join(',') === key,
  ) ?? null;
}


export function buildGroundingContext(
  context: AdvisorContext,
  classification: TurnClassification,
) {
  const referenced = new Set([
    ...classification.referenced_player_ids,
    ...classification.locked_player_ids,
    ...classification.excluded_player_ids,
    ...context.official_top_four,
  ]);
  return {
    context_id: context.context_id,
    generated_at: context.generated_at,
    season: context.season,
    league: context.league,
    official_top_four: context.official_top_four,
    roster_index: rosterIndex(context),
    player_dossiers: selectPlayerDossiers(context, [...referenced]),
    scenario: bestScenario(
      context,
      classification.locked_player_ids,
      classification.excluded_player_ids,
    ),
  };
}
