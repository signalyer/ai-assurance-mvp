// SDK Quickstart — Team Workspace surface #2.
// Pure display surface: system picker + parameterized copy-paste snippet.
// Zero new engine endpoints; system list reuses /grc/ai-systems.
// Snippet template mirrors sdk/README.md so it stays in sync if the SDK changes.

import { signal, computed } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet } from '../../shared/api/client';
import type { AiSystemSummary } from '../ai-systems/types';

interface AiSystemsListResponse { systems: AiSystemSummary[] }

const systems = signal<AiSystemSummary[]>([]);
const selectedId = signal<string>('');
const loading = signal<boolean>(true);
const loadError = signal<string | null>(null);
const copied = signal<'install' | 'snippet' | 'env' | null>(null);

const selected = computed<AiSystemSummary | null>(() => {
  const id = selectedId.value;
  if (!id) return systems.value[0] ?? null;
  return systems.value.find((s) => s.id === id) ?? null;
});

async function loadSystems(): Promise<void> {
  loading.value = true;
  loadError.value = null;
  const r = await apiGet<AiSystemsListResponse>('/grc/ai-systems');
  if (r.ok) systems.value = r.data.systems ?? [];
  else loadError.value = r.detail;
  loading.value = false;
}

function copyToClipboard(text: string, key: 'install' | 'snippet' | 'env'): void {
  void navigator.clipboard.writeText(text).then(() => {
    copied.value = key;
    window.setTimeout(() => { if (copied.value === key) copied.value = null; }, 1500);
  }).catch(() => {});
}

function workloadIdFor(s: AiSystemSummary | null): string {
  if (!s) return 'my-agent';
  return s.id.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

function snippetFor(s: AiSystemSummary | null): string {
  const wid = workloadIdFor(s);
  const scope = s?.domain || 'default';
  return `import os
import asyncio
import signallayer

# 1. Initialise once at startup (SL_API_KEY + SL_API_BASE_URL from env)
signallayer.init(
    api_key=os.environ["SL_API_KEY"],
    base_url=os.environ["SL_API_BASE_URL"],
)

# 2. Decorate your LLM-calling function with the platform chain.
#    Order is MANDATORY: policy_gate → scrub_pii → guardrails → trace → evaluate
@signallayer.policy_gate(action="llm_call")
@signallayer.scrub_pii(scope="${scope}")
@signallayer.guardrails()
async def call_llm(prompt: str, workload_id: str = "${wid}") -> str:
    # Your LLM call here (Anthropic, OpenAI, etc.)
    return f"Response to: {prompt}"

# 3. Assert the chain is in the correct order at import time.
#    Raises DecoratorOrderError on wrong order, ChainBrokenError on missing.
signallayer.guard(call_llm)

# 4. Call it
result = asyncio.run(call_llm(prompt="What is the balance?"))
print(result)
`;
}

function envFor(s: AiSystemSummary | null): string {
  const wid = workloadIdFor(s);
  return `# .env (local dev — never commit)
SL_API_KEY=dev:replace-with-your-key
SL_API_BASE_URL=http://localhost:8000
SL_WORKLOAD_ID=${wid}
`;
}

const INSTALL_CMD = 'pip install -e ./sdk';

interface CodeBlockProps {
  label: string;
  text: string;
  copyKey: 'install' | 'snippet' | 'env';
  language?: string;
}

function CodeBlock({ label, text, copyKey, language }: CodeBlockProps) {
  const isCopied = copied.value === copyKey;
  return (
    <div style={{ marginBottom: '0.75rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 600 }}>
          {label}{language ? <span style={{ marginLeft: '0.5rem', opacity: 0.6 }}>· {language}</span> : null}
        </span>
        <button class="btn btn-sm" onClick={() => copyToClipboard(text, copyKey)}>
          {isCopied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre style={{
        background: 'var(--bg-input)', border: '1px solid var(--border-strong)',
        borderRadius: '6px', padding: '0.875rem 1rem',
        fontFamily: 'Monaco, Menlo, Consolas, monospace', fontSize: '12px',
        whiteSpace: 'pre', overflowX: 'auto', lineHeight: 1.55,
        color: 'var(--text-primary)', margin: 0,
      }}>{text}</pre>
    </div>
  );
}

export function SdkQuickstartPage() {
  useEffect(() => { void loadSystems(); }, []);

  const s = selected.value;

  return (
    <div>
      <div class="page-header">
        <div>
          <div class="page-title">SDK Quickstart</div>
          <div class="page-subtitle">
            Copy-paste a working decorator stack pre-wired for your AI system. The chain order is enforced at import time via <code>signallayer.guard()</code>.
          </div>
        </div>
        <div class="page-actions">
          <select
            class="filter-select"
            value={s?.id ?? ''}
            onChange={(e) => { selectedId.value = (e.target as HTMLSelectElement).value; }}
            disabled={loading.value || systems.value.length === 0}
          >
            {systems.value.length === 0 && <option value="">No systems registered</option>}
            {systems.value.map((sys) => (
              <option key={sys.id} value={sys.id}>{sys.name}</option>
            ))}
          </select>
        </div>
      </div>

      {loadError.value && <div class="error-banner">Failed to load AI systems: {loadError.value}</div>}
      {loading.value && <div class="loading">Loading AI systems…</div>}

      {!loading.value && !loadError.value && (
        <>
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">What this snippet does</div>
                <div class="card-subtitle">
                  The 5-layer decorator chain wraps your LLM call in enforced governance — policy gating, PII scrubbing, guardrails (injection / topic / safety), tracing to Langfuse, and evaluation. Each layer fails closed; the order is mandatory.
                </div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1rem' }}>
              <ol style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '13px', lineHeight: 1.7 }}>
                <li><strong>@policy_gate</strong> — OPA check; DENY blocks the call before any data leaves your process.</li>
                <li><strong>@scrub_pii</strong> — Presidio NER scrubs prompt + response; raw values vaulted with Fernet, TTL-bound.</li>
                <li><strong>@guardrails</strong> — injection detection, topic enforcement (NeMo), and content safety (Llama Guard 3).</li>
                <li><strong>@trace</strong> — sends the <em>scrubbed</em> prompt to Langfuse. Raw never traced. Hard invariant.</li>
                <li><strong>@evaluate</strong> — DeepEval 6-metric suite (hallucination, relevancy, faithfulness, toxicity, PII leakage, scrub score).</li>
              </ol>
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">1 · Install the SDK</div>
                <div class="card-subtitle">Editable install from the monorepo. Internal-only until publish to Azure Artifacts.</div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1rem' }}>
              <CodeBlock label="Shell" text={INSTALL_CMD} copyKey="install" language="bash" />
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">2 · Environment</div>
                <div class="card-subtitle">Local dev only — production secrets via Key Vault / managed identity.</div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1rem' }}>
              <CodeBlock label="Env file" text={envFor(s)} copyKey="env" language=".env" />
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">3 · Decorator stack {s ? <span style={{ opacity: 0.6, fontWeight: 400 }}>· pre-wired for <strong>{s.name}</strong></span> : null}</div>
                <div class="card-subtitle">
                  <code>workload_id</code> and <code>scope</code> are populated from the selected system. <code>signallayer.guard()</code> rejects wrong-order chains at import time — never at runtime.
                </div>
              </div>
            </div>
            <div style={{ padding: '0.875rem 1rem' }}>
              <CodeBlock label="Python" text={snippetFor(s)} copyKey="snippet" language="python" />
            </div>
          </div>

          {s && (
            <div class="card">
              <div class="card-header">
                <div>
                  <div class="card-title">Selected system context</div>
                  <div class="card-subtitle">Values baked into the snippet above</div>
                </div>
              </div>
              <div style={{ padding: '0.875rem 1rem', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', fontSize: '12px' }}>
                <div><div style={{ color: 'var(--text-secondary)', fontSize: '10px', textTransform: 'uppercase' }}>System ID</div><div class="mono">{s.id}</div></div>
                <div><div style={{ color: 'var(--text-secondary)', fontSize: '10px', textTransform: 'uppercase' }}>Domain → Scope</div><div class="mono">{s.domain}</div></div>
                <div><div style={{ color: 'var(--text-secondary)', fontSize: '10px', textTransform: 'uppercase' }}>Risk Level</div><div>{s.risk_level}</div></div>
                <div><div style={{ color: 'var(--text-secondary)', fontSize: '10px', textTransform: 'uppercase' }}>Autonomy</div><div>{s.autonomy_level}</div></div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
