export type AdvisorStance = 'agrees' | 'diverges' | 'conditional';
export type AdvisorObjective = 'next_season' | 'multi_year' | 'balanced';

export interface AdvisorTextMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface KeeperAdvisorRequest {
  context_id: string;
  messages: AdvisorTextMessage[];
  conversation_summary: string | null;
}

export interface ResearchSource {
  title: string;
  url: string;
  published_at: string | null;
  retrieved_at: string;
}

export interface AdvisorTradeoff {
  out_player_id: number | null;
  in_player_id: number | null;
  projected_keeper_value_cost: number | null;
}

export interface AdvisorResearch {
  used: boolean;
  current_information_verified: boolean | null;
  as_of: string | null;
  sources: ResearchSource[];
}

export interface KeeperAdvisorResponse {
  stance: AdvisorStance;
  objective: AdvisorObjective;
  answer: string;
  model_view: string;
  recommendation: string;
  tradeoff: AdvisorTradeoff;
  qualitative_factors: string[];
  uncertainty: string[];
  research: AdvisorResearch;
}

export interface ProviderAnswerDraft extends KeeperAdvisorResponse {
  recommended_player_ids: number[];
}

export interface TurnClassification {
  objective: AdvisorObjective;
  needs_current_research: boolean;
  referenced_player_ids: number[];
  locked_player_ids: number[];
  excluded_player_ids: number[];
  conversation_summary: string;
}

export interface KeeperAdvisorApiSuccess {
  reply: KeeperAdvisorResponse;
  conversation_summary: string;
}

export interface KeeperAdvisorApiError {
  error: {
    code: 'invalid_request' | 'missing_context' | 'stale_context' |
      'missing_configuration' | 'provider_error' | 'invalid_provider_response';
    message: string;
    current_context_id?: string;
  };
}

export interface KeeperAdvisorRosterPlayer {
  player_id: number | null;
  name: string;
}

export interface AdvisorContextPlayer {
  player_id: number | null;
  yahoo_player_id: string;
  yahoo_name: string;
  full_name: string | null;
  position: string | null;
  match_status: string;
  excluded_reason: string | null;
  is_recommended: boolean;
  keeper_rank: number | null;
  raw_keeper_value: number | null;
  projected_total: number | null;
  age: number | null;
  [key: string]: unknown;
}

export interface ScenarioPlayer {
  player_id: number;
  assigned_round: number;
  pick_cost: number;
  raw_keeper_value: number;
  net_keeper_value: number;
}

export interface ScenarioSet {
  player_ids: number[];
  players: ScenarioPlayer[];
  total_model_value: number;
  total_net_keeper_value: number;
}

export interface AdvisorContext {
  schema_version: 1;
  context_id: string;
  generated_at: string;
  season: string;
  league: Record<string, unknown>;
  official_top_four: number[];
  roster: AdvisorContextPlayer[];
  scenario_data: { sets: ScenarioSet[] };
}

export interface StoredAdvisorTurn {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reply?: KeeperAdvisorResponse;
  created_at: string;
  failed?: boolean;
}

export interface StoredAdvisorConversation {
  schema_version: 1;
  context_id: string;
  season: string;
  updated_at: string;
  conversation_summary: string | null;
  turns: StoredAdvisorTurn[];
}
