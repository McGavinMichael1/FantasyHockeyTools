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

export interface PickupRecommendation extends Player {
  rank: number;
}

export interface CoolingCandidate extends Player {
  rank: number;
}
