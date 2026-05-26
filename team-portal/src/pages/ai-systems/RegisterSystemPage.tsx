// Register AI System — 5-step intake wizard (S48).
// Preact port of static/ai-systems-new.html (V1 451-line vanilla wizard).
// Calls POST /api/v1/grc/intake/preview (debounced) + POST /api/v1/grc/intake/submit.
import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiPost } from '../../shared/api/client';

type IntakeState = {
  name: string; description: string; business_owner: string; technical_owner: string;
  domain: string; use_case: string;
  user_population: string; customer_impact: string;
  cloud_provider: string;
  aws_services: string[]; model_provider: string; models_used: string[];
  rag_enabled: boolean; rag_sources: string[]; vector_store: string;
  tools_used: string[]; external_integrations: string[];
  data_classes: string[];
  data_in_prompts: boolean; data_in_rag: boolean;
  tools_return_sensitive_data: boolean; logs_contain_sensitive_data: boolean;
  autonomy_level: string;
  can_call_tools: boolean; can_write_data: boolean;
  can_trigger_customer_communication: boolean; can_influence_fs_workflow: boolean;
  human_approval_required: boolean;
  architecture_diagram_url: string; iac_url: string; iam_policy_url: string;
  bedrock_config_url: string; rag_pipeline_config_url: string;
  eval_report_url: string; logging_config_url: string; security_review_url: string;
};

type RequiredControl = {
  control_id: string; title: string; domain: string; priority: string;
  frameworks: Record<string, string[]>; recommended_owner: string;
};
type PreviewResponse = {
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  rules_fired: string[];
  rationale: string[];
  signals: Record<string, unknown>;
  controls: {
    applicable_total: number; required_total: number;
    by_priority: Record<string, number>; by_domain: Record<string, number>;
    required: RequiredControl[];
  };
  regulatory_exposure: string[];
};
type SubmitResponse = {
  ai_system_id: string; assessment_id: string; gate_count: number;
  inherent_risk: string; rules_fired: string[]; redirect_to: string;
};

const initial: IntakeState = {
  name: '', description: '', business_owner: '', technical_owner: '',
  domain: '', use_case: '',
  user_population: 'internal', customer_impact: '',
  cloud_provider: 'AWS',
  aws_services: [], model_provider: '', models_used: [],
  rag_enabled: false, rag_sources: [], vector_store: '',
  tools_used: [], external_integrations: [],
  data_classes: [],
  data_in_prompts: false, data_in_rag: false,
  tools_return_sensitive_data: false, logs_contain_sensitive_data: false,
  autonomy_level: 'answer_only',
  can_call_tools: false, can_write_data: false,
  can_trigger_customer_communication: false, can_influence_fs_workflow: false,
  human_approval_required: true,
  architecture_diagram_url: '', iac_url: '', iam_policy_url: '',
  bedrock_config_url: '', rag_pipeline_config_url: '',
  eval_report_url: '', logging_config_url: '', security_review_url: '',
};

// Module-level signals — survive component remounts within the wizard.
const state = signal<IntakeState>({ ...initial });
const currentStep = signal<number>(1);
const preview = signal<PreviewResponse | null>(null);
const submitting = signal<boolean>(false);
const submitError = signal<string | null>(null);

const STEPS = [
  { id: 1, label: 'Business Context' },
  { id: 2, label: 'Architecture' },
  { id: 3, label: 'Data Classification' },
  { id: 4, label: 'Agent Autonomy' },
  { id: 5, label: 'Evidence Upload' },
] as const;

function setField<K extends keyof IntakeState>(key: K, value: IntakeState[K]): void {
  state.value = { ...state.value, [key]: value };
  schedulePreview();
}

function toggleChip(key: keyof IntakeState, value: string): void {
  const cur = state.value[key];
  if (!Array.isArray(cur)) return;
  const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
  state.value = { ...state.value, [key]: next as IntakeState[typeof key] };
  schedulePreview();
}

function toggleSwitch(key: keyof IntakeState): void {
  const cur = state.value[key];
  if (typeof cur !== 'boolean') return;
  state.value = { ...state.value, [key]: !cur as IntakeState[typeof key] };
  schedulePreview();
}

let previewTimer: number | null = null;
function schedulePreview(): void {
  if (previewTimer !== null) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(runPreview, 250);
}

async function runPreview(): Promise<void> {
  const r = await apiPost<PreviewResponse>('/grc/intake/preview', state.value);
  if (r.ok) preview.value = r.data;
  // Preview failures are silent — V1 parity.
}

async function submitIntake(): Promise<void> {
  const s = state.value;
  if (!s.name || !s.business_owner || !s.technical_owner || !s.domain) {
    submitError.value = 'Step 1 required fields missing — system name, business owner, technical owner, and domain are required.';
    currentStep.value = 1;
    return;
  }
  submitting.value = true;
  submitError.value = null;
  const r = await apiPost<SubmitResponse>('/grc/intake/submit', s);
  if (!r.ok) {
    submitError.value = `Intake failed: ${r.detail}`;
    submitting.value = false;
    return;
  }
  // Reset local state so a second registration starts fresh.
  state.value = { ...initial };
  currentStep.value = 1;
  preview.value = null;
  // S53: drop the operator into the SDK onboarding wizard instead of the
  // bare AI Systems list. The engine's `redirect_to` is ignored on purpose
  // — onboarding is the canonical next step regardless of intake outcome.
  const newSystemId = r.data.ai_system_id;
  if (newSystemId) {
    window.location.href = `/onboarding/${encodeURIComponent(newSystemId)}`;
  } else {
    window.location.href = r.data.redirect_to || '/ai-systems';
  }
}

// ---------- Reusable field components ----------

function InputField(props: {
  label: string; field: keyof IntakeState; required?: boolean; span2?: boolean;
  placeholder?: string; help?: string; type?: string;
}) {
  const val = state.value[props.field];
  return (
    <div class={`form-field${props.span2 ? ' span-2' : ''}`}>
      <label class="form-label">
        {props.label}{props.required && <span class="req">*</span>}
      </label>
      <input
        class="form-input"
        type={props.type ?? 'text'}
        value={typeof val === 'string' ? val : ''}
        placeholder={props.placeholder ?? ''}
        onInput={(e) => setField(props.field, (e.currentTarget as HTMLInputElement).value as IntakeState[typeof props.field])}
      />
      {props.help && <div class="form-help">{props.help}</div>}
    </div>
  );
}

function TextareaField(props: { label: string; field: keyof IntakeState; required?: boolean; placeholder?: string }) {
  const val = state.value[props.field];
  return (
    <div class="form-field span-2">
      <label class="form-label">
        {props.label}{props.required && <span class="req">*</span>}
      </label>
      <textarea
        class="form-textarea"
        value={typeof val === 'string' ? val : ''}
        placeholder={props.placeholder ?? ''}
        onInput={(e) => setField(props.field, (e.currentTarget as HTMLTextAreaElement).value as IntakeState[typeof props.field])}
      />
    </div>
  );
}

type SelectOption = string | { value: string; label: string };
function SelectField(props: { label: string; field: keyof IntakeState; options: SelectOption[]; required?: boolean; span2?: boolean }) {
  const val = state.value[props.field];
  return (
    <div class={`form-field${props.span2 ? ' span-2' : ''}`}>
      <label class="form-label">
        {props.label}{props.required && <span class="req">*</span>}
      </label>
      <select
        class="form-select"
        value={typeof val === 'string' ? val : ''}
        onChange={(e) => setField(props.field, (e.currentTarget as HTMLSelectElement).value as IntakeState[typeof props.field])}
      >
        <option value="">Select…</option>
        {props.options.map((o) => {
          const v = typeof o === 'string' ? o : o.value;
          const l = typeof o === 'string' ? o : o.label;
          return <option key={v} value={v}>{l}</option>;
        })}
      </select>
    </div>
  );
}

type ChipOption = string | { value: string; label: string };
function ChipsField(props: { label: string; field: keyof IntakeState; options: ChipOption[]; dangerValues?: string[]; help?: string }) {
  const cur = state.value[props.field];
  const selected: string[] = Array.isArray(cur) ? cur : [];
  return (
    <div class="form-field span-2">
      <label class="form-label">{props.label}</label>
      <div class="chip-group">
        {props.options.map((o) => {
          const v = typeof o === 'string' ? o : o.value;
          const l = typeof o === 'string' ? o : o.label;
          const on = selected.includes(v);
          const danger = props.dangerValues?.includes(v) ?? false;
          const cls = ['chip'];
          if (on) cls.push('selected');
          if (danger) cls.push('critical');
          return (
            <span
              key={v}
              class={cls.join(' ')}
              onClick={() => toggleChip(props.field, v)}
            >{l}</span>
          );
        })}
      </div>
      {props.help && <div class="form-help">{props.help}</div>}
    </div>
  );
}

function SwitchField(props: { label: string; field: keyof IntakeState; help?: string }) {
  const on = state.value[props.field] === true;
  return (
    <div class="switch-row" style={{ gridColumn: 'span 2' }}>
      <div>
        <div class="switch-label">{props.label}</div>
        {props.help && <div class="switch-help">{props.help}</div>}
      </div>
      <div
        class={`switch${on ? ' on' : ''}`}
        onClick={() => toggleSwitch(props.field)}
        role="switch"
        aria-checked={on}
      />
    </div>
  );
}

// ---------- Step bodies ----------

function Step1() {
  return (
    <>
      <div class="card-header"><div>
        <div class="card-title">Step 1 — Business Context</div>
        <div class="card-subtitle">Who owns it, what it does, who it impacts</div>
      </div></div>
      <div class="form-grid">
        <InputField label="AI System Name" field="name" required span2 placeholder="e.g. Payments Exception Review Agent" />
        <TextareaField label="Description" field="description" required placeholder="What does this system do, in business terms?" />
        <InputField label="Business Owner" field="business_owner" required placeholder="Name, Title (e.g. Sarah Chen, VP Payments Ops)" />
        <InputField label="Technical Owner" field="technical_owner" required placeholder="Name, Title" />
        <SelectField label="Domain" field="domain" required options={['Payments','AML','KYC','Credit','Customer Service','Wealth','Treasury']} />
        <SelectField label="User Population" field="user_population" required options={[
          { value: 'internal', label: 'Internal users only' },
          { value: 'customer-facing', label: 'Customer-facing' },
          { value: 'third-party', label: 'Third-party / partner' },
          { value: 'regulator-facing', label: 'Regulator-facing' },
        ]} />
        <SelectField label="Customer Impact" field="customer_impact" required options={[
          { value: 'none', label: 'None' },
          { value: 'indirect', label: 'Indirect (informs human decisions)' },
          { value: 'direct', label: 'Direct (acts on customer accounts)' },
          { value: 'material', label: 'Material financial impact' },
        ]} />
        <TextareaField label="Use Case" field="use_case" placeholder="Business outcome, KPI, expected efficiency gain…" />
      </div>
    </>
  );
}

// S55 F-002 patch: cloud-conditional chip catalog. Backend field `aws_services`
// kept as-is (rename to `cloud_services` tracked as F-003); accepts any list[str].
const CLOUD_SERVICE_CATALOG: Record<string, string[]> = {
  AWS: [
    'Bedrock','Lambda','ECS','EKS','S3','OpenSearch','Aurora','DynamoDB',
    'API Gateway','Step Functions','CloudWatch','CloudTrail','KMS','IAM','VPC Endpoints',
  ],
  AZURE: [
    'Azure OpenAI','AI Foundry','Functions','App Service','Container Apps','AKS',
    'Blob Storage','Cosmos DB','AI Search','API Management','Logic Apps',
    'Monitor','Key Vault','Entra ID','Private Endpoints',
  ],
  GCP: [
    'Vertex AI','Cloud Functions','Cloud Run','GKE','Cloud Storage','BigQuery',
    'Firestore','API Gateway','Cloud Logging','Cloud KMS','IAM','VPC Service Controls',
  ],
  ON_PREM: [],
  MULTI: [],
};

function Step2() {
  const cloud = state.value.cloud_provider || 'AWS';
  const serviceOptions = CLOUD_SERVICE_CATALOG[cloud] ?? [];
  const servicesLabel = cloud === 'AWS' ? 'AWS Services Used'
                      : cloud === 'AZURE' ? 'Azure Services Used'
                      : cloud === 'GCP' ? 'GCP Services Used'
                      : 'Cloud Services Used';
  return (
    <>
      <div class="card-header"><div>
        <div class="card-title">Step 2 — Architecture</div>
        <div class="card-subtitle">Cloud, model, RAG, tools, external integrations</div>
      </div></div>
      <div class="form-grid">
        <SelectField label="Cloud Provider" field="cloud_provider" required options={[
          { value: 'AWS', label: 'AWS' },
          { value: 'AZURE', label: 'Azure' },
          { value: 'GCP', label: 'GCP' },
          { value: 'ON_PREM', label: 'On-prem' },
          { value: 'MULTI', label: 'Multi-cloud' },
        ]} />
        <InputField label="Model Provider" field="model_provider" placeholder="e.g. Anthropic direct, AWS Bedrock, Azure OpenAI, Vertex AI" />
        {serviceOptions.length > 0
          ? <ChipsField label={servicesLabel} field="aws_services" options={serviceOptions} />
          : <InputField label={servicesLabel} field="model_provider" placeholder="No catalog for this cloud — describe services in free text via Model Provider field above" />
        }
        <ChipsField label="Models Used" field="models_used" options={[
          'claude-opus-4-7','claude-sonnet-4-6','claude-haiku-4-5',
          'gpt-4o','gpt-4-turbo','amazon.titan-text-express','amazon.nova-pro',
          'gemini-1.5-pro','internal-fine-tune',
        ]} />
        <SwitchField label="RAG enabled" field="rag_enabled" help="Does this system retrieve from a knowledge base before answering?" />
        <InputField label="Vector Store" field="vector_store" span2 placeholder="e.g. OpenSearch Serverless, Aurora pgvector — leave blank if no RAG" />
        <ChipsField label="RAG Sources" field="rag_sources" options={[
          'Internal Procedures','FAQ Corpus','Regulatory Guidance',
          'Case History (de-identified)','Product Documentation',
          'FinCEN Advisories','Underwriting Standards',
        ]} />
        <ChipsField label="Tools / APIs Used" field="tools_used" options={[
          'lookup_transaction','hold_payment','release_payment','search_sanctions',
          'extract_id_document','get_account_balance','transfer_funds','open_case_note',
          'send_customer_message','credit_decision','escalate_to_analyst',
        ]} />
        <ChipsField label="External Integrations" field="external_integrations" options={[
          'Core Banking','Payments Platform','AML Platform','OFAC / SDN',
          'CRM','Email / SMS Gateway','Document Store',
        ]} />
      </div>
    </>
  );
}

function Step3() {
  return (
    <>
      <div class="card-header"><div>
        <div class="card-title">Step 3 — Data Classification</div>
        <div class="card-subtitle">What kinds of data flow through this system, and where</div>
      </div></div>
      <div class="form-grid">
        <ChipsField
          label="Data Classes" field="data_classes"
          options={[
            { value: 'public', label: 'Public' },
            { value: 'internal', label: 'Internal' },
            { value: 'confidential', label: 'Confidential' },
            { value: 'pii', label: 'PII' },
            { value: 'npi', label: 'NPI (GLBA)' },
            { value: 'pci', label: 'PCI (cardholder data)' },
            { value: 'payment_data', label: 'Payment Data' },
            { value: 'aml_kyc_data', label: 'AML / KYC Data' },
            { value: 'credit_data', label: 'Credit Data' },
          ]}
          dangerValues={['pii','npi','pci','payment_data','aml_kyc_data','credit_data']}
          help="Sensitive classes drive a stricter control set."
        />
        <SwitchField label="Data enters prompts" field="data_in_prompts" help="Customer data is passed into model context at inference time." />
        <SwitchField label="Data enters RAG" field="data_in_rag" help="Customer or internal-sensitive data is indexed in the RAG corpus." />
        <SwitchField label="Tools return sensitive data" field="tools_return_sensitive_data" help="Any tool response carries PII/NPI/PCI back to the agent." />
        <SwitchField label="Logs may contain sensitive data" field="logs_contain_sensitive_data" help="Inference logs, traces, or audit trails capture sensitive fields." />
      </div>
    </>
  );
}

function Step4() {
  return (
    <>
      <div class="card-header"><div>
        <div class="card-title">Step 4 — Agent Autonomy</div>
        <div class="card-subtitle">What the agent can decide, what it can do, where humans must intervene</div>
      </div></div>
      <div class="form-grid">
        <SelectField label="Autonomy Level" field="autonomy_level" required span2 options={[
          { value: 'answer_only', label: 'Answer only — read-only Q&A' },
          { value: 'recommend', label: 'Recommend — surfaces options, no action' },
          { value: 'draft', label: 'Draft — produces documents for human review' },
          { value: 'execute_with_approval', label: 'Execute with approval — tools gated by human' },
          { value: 'execute_autonomously', label: 'Execute autonomously — no human gate' },
        ]} />
        <SwitchField label="Can call tools / APIs" field="can_call_tools" help="Agent invokes deterministic tools beyond pure text generation." />
        <SwitchField label="Can write data" field="can_write_data" help="Agent mutates a system of record (create/update/delete)." />
        <SwitchField label="Can trigger customer communication" field="can_trigger_customer_communication" help="Agent can send email, SMS, in-app messages, or chat responses." />
        <SwitchField label="Can influence Payments / Credit / AML / KYC" field="can_influence_fs_workflow" help="Agent action can move money, approve credit, file SARs, or open accounts." />
        <SwitchField label="Human approval required for high-risk actions" field="human_approval_required" help="Money movement > $10K, customer-impacting decisions, sanctions hits." />
      </div>
    </>
  );
}

function Step5() {
  return (
    <>
      <div class="card-header"><div>
        <div class="card-title">Step 5 — Evidence Upload</div>
        <div class="card-subtitle">Link the artifacts that will be evaluated. Links only — files stay in their systems of record.</div>
      </div></div>
      <div class="form-grid">
        <InputField label="Architecture Diagram" field="architecture_diagram_url" span2 placeholder="Confluence / Lucid URL" />
        <InputField label="Terraform / CloudFormation" field="iac_url" placeholder="Git repo or commit URL" />
        <InputField label="IAM Policy" field="iam_policy_url" placeholder="Policy ARN or document link" />
        <InputField label="Bedrock Configuration" field="bedrock_config_url" placeholder="ModelInvocationLoggingConfiguration export" />
        <InputField label="RAG Pipeline Config" field="rag_pipeline_config_url" placeholder="Pipeline manifest URL" />
        <InputField label="Eval Report" field="eval_report_url" placeholder="Latest eval run report" />
        <InputField label="Logging Config" field="logging_config_url" placeholder="CloudWatch / Macie config" />
        <InputField label="Security Review" field="security_review_url" placeholder="AppSec review document" />
      </div>
      <div class="form-help" style={{ marginTop: '1rem' }}>
        On submit: an AI System record will be created, inherent risk classified, required P0/P1 controls bound as release gates, and an initial assessment opened. You'll be redirected to the system detail page.
      </div>
    </>
  );
}

const stepBody = computed(() => {
  switch (currentStep.value) {
    case 1: return <Step1 />;
    case 2: return <Step2 />;
    case 3: return <Step3 />;
    case 4: return <Step4 />;
    case 5: return <Step5 />;
    default: return <Step1 />;
  }
});

// ---------- Risk panel ----------

function RiskPanel() {
  const p = preview.value;
  const risk = p?.risk_level ?? 'MEDIUM';
  return (
    <div class="card risk-panel">
      <div class="card-header"><div>
        <div class="card-title">Preliminary Risk Classification</div>
        <div class="card-subtitle">Live — updates as you complete the intake</div>
      </div></div>
      <div style={{ textAlign: 'center', padding: '0.75rem 0' }}>
        <div class={`risk-pill ${risk}`}>{risk}</div>
      </div>
      <div style={{ marginTop: '0.5rem' }}>
        {!p || p.rationale.length === 0
          ? <div class="text-xs text-tertiary">No rule fired yet — complete more fields.</div>
          : p.rationale.map((r, i) => (
              <div class="rule-row" key={i}>
                <span class="rule-tag">{p.rules_fired[i] ?? '·'}</span>
                <span>{r}</span>
              </div>
            ))
        }
      </div>
      <div class="drawer-section">
        <div class="drawer-section-title">Required Controls</div>
        {p ? (
          <>
            <div><span class="font-bold">{p.controls.required_total}</span> P0/P1 required · {p.controls.applicable_total} total applicable</div>
            <div class="text-xs text-tertiary" style={{ marginTop: '0.25rem' }}>
              P0: {p.controls.by_priority.P0 ?? 0} · P1: {p.controls.by_priority.P1 ?? 0} · P2: {p.controls.by_priority.P2 ?? 0}
            </div>
            {p.controls.required.slice(0, 6).map((rc) => (
              <div class="text-xs" style={{ marginTop: '0.25rem' }} key={rc.control_id}>
                <span style={{ fontFamily: 'ui-monospace, monospace' }}>{rc.control_id}</span>
                <span class={`badge ${rc.priority === 'P0' ? 'badge-critical' : 'badge-high'}`} style={{ marginLeft: '4px' }}>{rc.priority}</span>
                {' '}{rc.title}
              </div>
            ))}
            {p.controls.required.length > 6 && (
              <div class="text-xs text-tertiary" style={{ marginTop: '0.25rem' }}>+ {p.controls.required.length - 6} more…</div>
            )}
          </>
        ) : <div class="text-sm text-secondary">—</div>}
      </div>
      <div class="drawer-section">
        <div class="drawer-section-title">Regulatory Exposure</div>
        <div class="flex gap-1" style={{ flexWrap: 'wrap' }}>
          {p && p.regulatory_exposure.length > 0
            ? p.regulatory_exposure.map((e) => <span class="badge" key={e}>{e}</span>)
            : <span class="text-xs text-tertiary">None inferred from domain yet.</span>
          }
        </div>
      </div>
    </div>
  );
}

// ---------- Top-level page ----------

export function RegisterSystemPage() {
  useEffect(() => {
    void runPreview();
  }, []);

  const step = currentStep.value;
  const isLast = step === STEPS.length;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">Register AI System</div>
          <div class="page-subtitle">Intake workflow — classifies inherent risk and applies required controls before any release activity</div>
        </div>
        <div class="page-actions">
          <a class="btn btn-sm" href="/ai-systems">Cancel</a>
        </div>
      </div>

      <div class="step-rail">
        {STEPS.map((s) => {
          const cls = s.id === step ? 'active' : s.id < step ? 'done' : '';
          return (
            <div class={`step-rail-item ${cls}`} key={s.id} onClick={() => { currentStep.value = s.id; }}>
              <span class="step-num">{s.id < step ? '✓' : s.id}</span>
              <span>{s.label}</span>
            </div>
          );
        })}
      </div>

      {submitError.value && <div class="error-banner">{submitError.value}</div>}

      <div class="wizard-layout">
        <div class="card">
          {stepBody.value}
          <div class="wizard-footer">
            <div class="left">
              <button
                class="btn btn-sm"
                disabled={step === 1}
                onClick={() => { if (currentStep.value > 1) currentStep.value -= 1; }}
              >Back</button>
            </div>
            <div class="right">
              {!isLast && (
                <button
                  class="btn btn-sm"
                  onClick={() => { if (currentStep.value < STEPS.length) currentStep.value += 1; }}
                >Next</button>
              )}
              {isLast && (
                <button
                  class="btn btn-sm btn-primary"
                  disabled={submitting.value}
                  onClick={() => void submitIntake()}
                >{submitting.value ? 'Submitting…' : 'Submit Intake'}</button>
              )}
            </div>
          </div>
        </div>

        <RiskPanel />
      </div>
    </div>
  );
}
