// Evidence Bundles — type definitions (CSM-3)
// Mirrors engine response shapes from api/evidence.py router:
//   GET /api/grc/evidence/v2/sectioned?scope=ALL|<id>
//   GET /api/grc/evidence/v2/completeness?axis=ai_system|framework|control_domain|release_gate
//   GET /api/grc/evidence/v2/sections
//   GET /api/grc/evidence/v2/{evidence_id}

export interface EvidenceRow {
  id: string;
  ai_system_id: string;
  ai_system_name: string;
  assessment_id?: string | null;
  evidence_type: string;
  evidence_type_pretty: string;
  section_id: string;
  section_name: string;
  source: string;
  collected_at: string;
  hash?: string | null;
  immutable: boolean;
  summary: string;
  uri?: string | null;
  linked_control_ids: string[];
  linked_finding_ids: string[];
  linked_frameworks: string[];
}

export interface SectionedSection {
  section_id: string;
  section_name: string;
  type_filter: string[];
  count: number;
  items: EvidenceRow[];
}

export interface SectionedResponse {
  scope: string;
  sections: SectionedSection[];
}

export interface CompletenessRow {
  label: string;
  present: number;
  required: number;
  pct: number;
  missing: string[];
}

export interface CompletenessResponse {
  axis: string;
  scope: string;
  rows: CompletenessRow[];
}

export interface SectionCatalogItem {
  id: string;
  name: string;
  types: string[];
}

export interface SectionsResponse {
  sections: SectionCatalogItem[];
}

export interface EvidenceDetailResponse {
  id: string;
  ai_system_id: string;
  ai_system_name: string;
  assessment_id?: string | null;
  evidence_type: string;
  source: string;
  uri?: string | null;
  hash?: string | null;
  collected_at: string;
  summary: string;
  immutable: boolean;
  linked_control_ids: string[];
  linked_finding_ids: string[];
  linked_frameworks: string[];
}

export type CompletenessAxis = 'ai_system' | 'framework' | 'control_domain' | 'release_gate';
