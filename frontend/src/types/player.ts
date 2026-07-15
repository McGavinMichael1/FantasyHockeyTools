export type Position = 'C' | 'L' | 'R' | 'D';

export interface Player {
  id: number;
  full_name: string;
  positionCode: Position;
  headshot: string;
  sweaterNumber: number;

  // Season stats
  gamesPlayed: number;
  goals: number;
  assists: number;
  points: number;
  plusMinus: number;
  powerPlayPoints: number;
  shorthandedPoints: number;
  shots: number;
  avgToi: string;

  // Fantasy
  fantasyPoints: number;
  season_ppg: number;

  // Last 5 games
  last5_goals: number;
  last5_assists: number;
  last5_points: number;
  last5_fantasyPoints: number;

  // Scores
  weighted_score: number;
  ml_score: number;
  final_score: number;
  cooling_score: number;

  // Status
  rostered: boolean;
}

// Season-level draft projection row (from main.py draft -> api_export.py).
// Distinct shape from Player: no live/last-5 stats, projection fields instead.
export interface DraftPlayer {
  id: number;
  full_name: string;
  positionCode: Position;
  headshot: string;
  age: number | null;
  gamesPlayed: number;
  last_fpPerGame: number;
  projected_fpPerGame: number;
  projected_total: number;
  delta_vs_last: number;
}

export interface PickupRecommendation extends Player {
  rank: number;
}

export interface CoolingCandidate extends Player {
  rank: number;
}
