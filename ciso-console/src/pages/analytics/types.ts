// Analytics — type definitions (CSM-3)
// Mirrors engine response shapes from api/analytics.py router:
//   GET /api/analytics          — full rollup
//   GET /api/analytics/by-domain
//   GET /api/analytics/trends

export interface TrendPoint {
  date: string;
  runs: number;
  pass: number;
  fail: number;
  pass_rate: number;
}

export interface AnalyticsRollup {
  total_runs: number;
  by_domain: Record<string, number>;
  by_model: Record<string, number>;
  by_risk: Record<string, number>;
  trends: TrendPoint[];
  failure_types: Record<string, number>;
  average_latency_ms: number;
  total_tokens: number;
  period_days?: number | null;
  pass_rate?: number | null;
}

export interface AnalyticsByDomainResponse {
  period_days: number;
  by_domain: Record<string, number>;
  total_runs: number;
}

export interface AnalyticsTrendsResponse {
  period_days: number;
  trends: TrendPoint[];
  pass_rate: number;
}
