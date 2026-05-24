// Mirrors api/memory.py response models (Session 04 endpoints).
// Workload-picker source is /api/domains/ which is shared with V1.

export interface MemoryStats {
  total_episodes?: number;
  expired_count?: number;
  episodes_by_workload?: Record<string, number>;
  by_workload?: Record<string, number>;
  [k: string]: unknown;
}

export interface RagStats {
  doc_count?: number;
  index_name?: string;
  [k: string]: unknown;
}

export interface StatsResponse {
  memory: MemoryStats;
  rag: RagStats;
}

export interface EpisodeItem {
  episode_id: string;
  workload_id: string;
  timestamp: string;
  outcome: string;
  prompt_preview: string;
  response_preview: string;
  trace_id: string | null;
  metadata: Record<string, unknown>;
}

export interface EpisodesResponse {
  workload_id: string;
  episodes: EpisodeItem[];
  total: number;
}

export interface RecallItem {
  episode_id: string;
  workload_id: string;
  timestamp: string;
  prompt_preview: string;
  response_preview: string;
  outcome: string;
  relevance_score: number;
  metadata: Record<string, unknown>;
}

export interface RecallResponse {
  workload_id: string;
  query: string;
  results: RecallItem[];
}

export interface ContextResponse {
  workload_id: string;
  context: string;
  lookback_days: number;
}

export interface DomainSummary {
  id: string;
  name?: string;
}

export interface DomainsResponse {
  domains: DomainSummary[];
  count: number;
}
