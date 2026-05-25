// Surface: Policy Governance (CSM-4)
// V1 ancestor: static/policies.html
// Endpoints:
//   GET /api/grc/policies         — list (PoliciesOut)
//   GET /api/grc/policies/{id}    — detail (PolicyOut)

export interface PolicyItem {
  id: string;
  requirement: string;
  framework_mappings: string[];
  severity: string;
  evidence_required: string[];
  pass_criteria: string;
  owner: string;
  automation_status: string;
  compliant_systems: number;
  non_compliant_systems: number;
}

export interface PoliciesResponse {
  policies: PolicyItem[];
  total: number;
}
