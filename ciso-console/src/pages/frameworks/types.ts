// Framework Coverage Matrix — type definitions.
// Mirrors engine response shapes from:
//   GET /api/frameworks/matrix  (frameworks.py MatrixOut)
//   GET /api/frameworks/{slug}/system/{id}  (DrillDownOut)
//   POST /api/frameworks/{slug}/export  (PDF response — no typed body, triggers download)

export interface MatrixCell {
  framework_slug: string;
  coverage_pct: number;
}

export interface MatrixRow {
  system_id: string;
  system_name: string;
  cells: Record<string, number>;
}

export interface FrameworkMeta {
  slug: string;
  display_name: string;
}

export interface MatrixResponse {
  frameworks: FrameworkMeta[];
  rows: MatrixRow[];
}

export interface ControlRollup {
  control_id: string;
  title: string;
  priority: string;
  domain: string;
  status: string;
  open_findings: number;
}

export interface FindingSummary {
  id: string;
  system_id: string;
  title: string;
  severity: string;
  status: string;
  control_id: string | null;
}

export interface EvidenceSummary {
  id: string;
  summary: string;
  evidence_hash: string;
  collected_at: string;
  source: string;
  evidence_type: string;
}

export interface DrillDownItem {
  id: string;
  display_name: string;
  coverage_pct: number;
  controls: ControlRollup[];
  findings: FindingSummary[];
  evidence: EvidenceSummary[];
}

export interface DrillDownResponse {
  framework: string;
  display_name: string;
  system_id: string;
  items: DrillDownItem[];
}
