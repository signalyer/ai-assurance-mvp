// Runtime wire types — mirror /api/v1/grc/runtime/v2/* response shapes.

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' | string;
export type RuntimeAction =
  | 'blocked' | 'refused' | 'halted' | 'masked' | 'escalated'
  | 'queued' | 'logged' | 'ingested' | 'throttled' | 'flagged' | string;
export type MonitoringLevel = 'STANDARD' | 'HEIGHTENED' | 'INCIDENT' | string;

export interface RuntimeEvent {
  id: string;
  timestamp: string;
  source: string;
  event_type: string;
  details: string;
  ai_system_id: string;
  severity: Severity;
  action_taken: RuntimeAction;
  policy_triggered?: string | null;
  linked_framework?: string | null;
  evidence_id?: string | null;
}

export interface RuntimeApproval {
  id: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED' | string;
  action_description: string;
  ai_system_id: string;
  requested_by: string;
  expires_at: string;
  approver?: string | null;
  note?: string | null;
}

export interface RuntimeIncident {
  id: string;
  status: 'OPEN' | 'INVESTIGATING' | 'MITIGATED' | 'CLOSED' | string;
  summary: string;
  ai_system_id: string;
  owner: string;
  created_at: string;
  from_event_id?: string | null;
}

export interface RuntimeState {
  ai_system_id: string;
  ai_system_name: string;
  kill_switch_engaged: boolean;
  enabled: boolean;
  monitoring_level: MonitoringLevel;
}

export interface RuntimeConnector {
  source: string;
  implementation: string;
  event_count: number;
}

export interface EventsResponse     { events: RuntimeEvent[] }
export interface ApprovalsResponse  { approvals: RuntimeApproval[] }
export interface IncidentsResponse  { incidents: RuntimeIncident[] }
export interface StatesResponse     { states: RuntimeState[] }
export interface ConnectorsResponse { connectors: RuntimeConnector[] }
