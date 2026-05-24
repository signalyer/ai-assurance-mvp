// Agent Library wire types — mirror /api/v1/agents responses.

export type OwnerType = 'REUSABLE' | 'CUSTOM' | string;
export type Risk = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string;

export interface AgentSummary {
  id: string;
  name: string;
  description?: string;
  team?: string;
  owner_type?: OwnerType;
  inherent_risk?: Risk;
  latest_semver?: string;
  latest_version?: string;
  subscriber_count?: number;
  last_published_at?: string | null;
  status?: string;
}

export interface AgentVersion {
  semver?: string;
  version?: string;
  status?: 'PUBLISHED' | 'DRAFT' | string;
  published_at?: string | null;
  changelog?: string | null;
}

export interface AgentSubscriber {
  system_id?: string;
  system_name?: string;
  pinned_version?: string;
  version_id?: string;
  pinned?: boolean;
  upgrade_available_version_id?: string | null;
}

export interface AgentDetail extends AgentSummary {
  versions?: AgentVersion[];
  subscribers?: AgentSubscriber[];
}
