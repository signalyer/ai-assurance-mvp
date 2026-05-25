// Surface: Reports (CSM-4)
// V1 ancestor: static/reports.html
// Endpoints:
//   GET /api/reports/catalog          — list report types (ReportCatalogResponse)
//   GET /api/reports/systems          — AI system selector (ReportSystemsResponse)
//   GET /api/reports/{type}           — report data JSON
//   GET /api/reports/{type}/export.pdf  — print-ready HTML (open in new tab)
//   GET /api/reports/{type}/export.json — JSON download
//   GET /api/reports/{type}/export.csv  — CSV download

export interface ReportCatalogItem {
  type: string;
  title: string;
  scope: string;
  requires_system: boolean;
  audience: string[];
  description: string;
}

export interface ReportCatalogResponse {
  reports: ReportCatalogItem[];
}

export interface ReportSystemItem {
  id: string;
  name: string;
  domain: string;
  runtime_status: string;
  release_decision: string;
}

export interface ReportSystemsResponse {
  systems: ReportSystemItem[];
}

export interface ReportStatus {
  type: string;
  state: 'idle' | 'generating' | 'done' | 'error';
  lastGeneratedAt: string | null;
  error: string | null;
}
