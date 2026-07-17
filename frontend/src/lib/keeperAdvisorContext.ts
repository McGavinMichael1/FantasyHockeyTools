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
  if (!isRecord(value)) return false;
  const context = value;
  return context.schema_version === 1 && typeof context.context_id === 'string' &&
    typeof context.generated_at === 'string' && typeof context.season === 'string' &&
    isRecord(context.league) &&
    isTopFour(context.official_top_four) &&
    Array.isArray(context.roster) && context.roster.every(isAdvisorContextPlayer) &&
    isScenarioData(context.scenario_data);
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}


function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}


function isInteger(value: unknown): value is number {
  return Number.isInteger(value);
}


function isNullableString(value: unknown): value is string | null {
  return typeof value === 'string' || value === null;
}


function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}


function isNullableInteger(value: unknown): value is number | null {
  return value === null || isInteger(value);
}


function isTopFour(value: unknown): value is number[] {
  return isFourDistinctIntegerIds(value);
}


function isFourDistinctIntegerIds(value: unknown): value is number[] {
  return Array.isArray(value) && value.length === 4 && value.every(isInteger) &&
    new Set(value).size === 4;
}


function isAdvisorContextPlayer(value: unknown): value is AdvisorContextPlayer {
  return isRecord(value) &&
    isNullableInteger(value.player_id) &&
    typeof value.yahoo_player_id === 'string' &&
    typeof value.yahoo_name === 'string' &&
    isNullableString(value.full_name) &&
    isNullableString(value.position) &&
    typeof value.match_status === 'string' &&
    isNullableString(value.excluded_reason) &&
    typeof value.is_recommended === 'boolean' &&
    isNullableFiniteNumber(value.keeper_rank) &&
    isNullableFiniteNumber(value.raw_keeper_value) &&
    isNullableFiniteNumber(value.projected_total) &&
    isNullableFiniteNumber(value.age);
}


function isScenarioPlayer(value: unknown): value is ScenarioSet['players'][number] {
  return isRecord(value) && isInteger(value.player_id) &&
    isInteger(value.assigned_round) && isFiniteNumber(value.pick_cost) &&
    isFiniteNumber(value.raw_keeper_value) && isFiniteNumber(value.net_keeper_value);
}


function isScenarioSet(value: unknown): value is ScenarioSet {
  if (!isRecord(value) || !isFourDistinctIntegerIds(value.player_ids) ||
    !Array.isArray(value.players) || value.players.length !== 4 ||
    !value.players.every(isScenarioPlayer) || !isFiniteNumber(value.total_model_value) ||
    !isFiniteNumber(value.total_net_keeper_value)) {
    return false;
  }
  const playerIds = [...value.player_ids].sort((left, right) => left - right);
  const scenarioPlayerIds = value.players
    .map((player) => player.player_id)
    .sort((left, right) => left - right);
  return playerIds.every((playerId, index) => playerId === scenarioPlayerIds[index]);
}


function isScenarioData(value: unknown): value is AdvisorContext['scenario_data'] {
  return isRecord(value) && Array.isArray(value.sets) && value.sets.every(isScenarioSet);
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
