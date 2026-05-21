// AI Assurance Control Plane — Shared components

const NAV_ITEMS = [
    { path: "/", label: "Overview" },
    { path: "/framework-sop", label: "Framework SOP", badge: "SOP", badgeClass: "info" },
    { path: "/demo", label: "Guided Demo", badge: "FS", badgeClass: "info" },
    { path: "/demo-aws-analyzer", label: "AWS Analyzer Demo", badge: "AWS", badgeClass: "info" },
    { path: "/ai-systems", label: "AI Systems" },
    { path: "/governance", label: "Governance" },
    { path: "/security", label: "Security" },
    { path: "/runtime", label: "Runtime" },
    { path: "/evals", label: "Evals" },
    { path: "/findings", label: "Findings", badge: "24" },
    { path: "/release-gates", label: "Release Gates", badge: "6", badgeClass: "medium" },
    { path: "/evidence", label: "Evidence" },
    { path: "/policies", label: "Policies" },
    { path: "/reports", label: "Reports" },
    { path: "/assurance-providers", label: "Assurance Providers" },
];

const QUICK_ACTIONS = [
    { label: "Run Assessment",     href: "/assessment" },
    { label: "View Runtime Events", href: "/runtime" },
    { label: "Open Findings",       href: "/findings" },
    { label: "Upload Evidence",     href: "/evidence" },
    { label: "Executive Report",    href: "/reports" },
];

function renderSidebar(activePath) {
    const navHtml = NAV_ITEMS.map(item => {
        const isActive = item.path === activePath ? 'active' : '';
        const arrow = isActive ? '<span class="nav-arrow">›</span>' : '';
        const badge = item.badge
            ? `<span class="sidebar-nav-badge ${item.badgeClass || ''}">${item.badge}</span>`
            : '';
        return `<a href="${item.path}" class="${isActive}">${item.label}${badge}${arrow}</a>`;
    }).join('');

    const quickHtml = QUICK_ACTIONS.map(a =>
        `<a class="sidebar-quick-action" href="${a.href}">${a.label}</a>`
    ).join('');

    return `
        <aside class="sidebar">
            <div class="sidebar-brand">
                <div class="sidebar-brand-icon">⬢</div>
                <div>
                    <div class="sidebar-brand-text">AI ASSURANCE</div>
                    <div class="sidebar-brand-subtitle">Control Plane</div>
                </div>
            </div>
            <nav class="sidebar-nav">
                ${navHtml}
            </nav>
            <div class="sidebar-quick">
                <div class="sidebar-quick-label">Quick Actions</div>
                ${quickHtml}
            </div>
        </aside>
    `;
}

function renderTopbar() {
    return `
        <div class="topbar">
            <div class="search-bar">
                <input type="text" placeholder="Search systems, findings, policies...">
            </div>
            <div class="topbar-right">
                <a id="topbarAnalyticsLink" href="/analytics-usage" class="topbar-action" style="display:none;" title="Usage analytics (demo-ciso only)">
                    <span>📊</span><span class="topbar-action-label">Usage Analytics</span>
                </a>
                <button class="icon-btn" id="notifBellBtn" title="AI Risk Operations notifications">
                    <span>🔔</span>
                    <span class="badge-dot" id="notifUnreadDot" style="display:none;">0</span>
                </button>
                <button class="icon-btn guide-btn" id="guideBtn" title="AI Governance Assistant — page guide + framework glossary">
                    <span>📘</span>
                    <span class="guide-btn-label">Guide</span>
                </button>
                <div class="user-block">
                    <div class="user-avatar" id="topbarUserAvatar">··</div>
                    <div class="user-info">
                        <div class="user-name" id="topbarUserName">Signed in</div>
                        <div class="user-role" id="topbarUserRole">—</div>
                    </div>
                </div>
                <button id="topbarLogoutBtn" class="topbar-action topbar-logout" title="Sign out (auto after 10 min idle)">
                    <span>⎋</span><span class="topbar-action-label">Sign out</span>
                </button>
            </div>
        </div>
        ${renderNotificationPanel()}
        ${renderGuidePanel()}
    `;
}

// Topbar identity + logout + analytics gating ---------------------------------
async function wireTopbarIdentity() {
    const logoutBtn = document.getElementById('topbarLogoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
            } catch (e) { /* swallow — redirect anyway */ }
            window.location.href = '/login';
        });
    }

    try {
        const r = await fetch('/api/auth/whoami', { credentials: 'same-origin' });
        if (!r.ok) return;
        const j = await r.json();
        const user = j.user || '';
        const nameEl = document.getElementById('topbarUserName');
        const roleEl = document.getElementById('topbarUserRole');
        const avEl   = document.getElementById('topbarUserAvatar');
        if (user) {
            const role = user.replace(/^demo-/, '').toUpperCase();
            if (nameEl) nameEl.textContent = user;
            if (roleEl) roleEl.textContent = role;
            if (avEl)   avEl.textContent   = role.slice(0, 2);
        }
        if (j.is_ciso) {
            const link = document.getElementById('topbarAnalyticsLink');
            if (link) link.style.display = '';
        }
    } catch (e) { /* whoami unavailable — leave defaults */ }
}

function renderGuidePanel() {
    return `
        <div class="guide-overlay" id="guideOverlay"></div>
        <aside class="guide-panel" id="guidePanel" aria-hidden="true">
            <header class="guide-header">
                <div>
                    <div class="guide-title">AI Governance Assistant</div>
                    <div class="guide-subtitle">Embedded operating guide — context-aware page guidance, framework glossary, control + framework lookup</div>
                </div>
                <button class="notif-close" id="guideCloseBtn" aria-label="Close">×</button>
            </header>
            <div class="guide-search">
                <input id="guideSearchInput" type="text"
                       placeholder='Search controls, framework items, glossary — e.g. "LLM01", "AI-006", "HITL"'>
            </div>
            <div class="guide-tabs" id="guideTabs"></div>
            <div class="guide-body" id="guideBody">
                <div class="notif-empty">Loading…</div>
            </div>
            <footer class="notif-footer">
                <a href="/governance" class="notif-link">Open Governance dashboard ›</a>
            </footer>
        </aside>
    `;
}

// ============================================================================
// Governance Assistant — runtime
// ============================================================================

const GUIDE_TABS = [
    { key: 'page',       label: 'This Page' },
    { key: 'glossary',   label: 'Glossary' },
    { key: 'controls',   label: 'Controls' },
    { key: 'frameworks', label: 'Frameworks' },
];

const GUIDE_STATE = {
    tab: 'page',
    activePath: '/',
    pageGuide: null,
    glossary: null,
    controls: null,
    frameworks: null,
    searchResults: null,
    searchTerm: '',
};

function setGuideActivePath(path) { GUIDE_STATE.activePath = path; }

async function loadGuideTab(tab) {
    GUIDE_STATE.tab = tab;
    const body = document.getElementById('guideBody');
    if (!body) return;
    body.innerHTML = '<div class="notif-empty">Loading…</div>';
    try {
        if (tab === 'page') {
            if (!GUIDE_STATE.pageGuide || GUIDE_STATE.pageGuide.page !== GUIDE_STATE.activePath) {
                const r = await fetch(`/api/guide/page?path=${encodeURIComponent(GUIDE_STATE.activePath)}`);
                GUIDE_STATE.pageGuide = await r.json();
            }
            renderGuidePage();
        } else if (tab === 'glossary') {
            if (!GUIDE_STATE.glossary) {
                const r = await fetch('/api/guide/glossary');
                const d = await r.json();
                GUIDE_STATE.glossary = d.terms;
            }
            renderGuideGlossary();
        } else if (tab === 'controls') {
            if (!GUIDE_STATE.controls) {
                const r = await fetch('/api/guide/controls');
                const d = await r.json();
                GUIDE_STATE.controls = d.controls;
            }
            renderGuideControls();
        } else if (tab === 'frameworks') {
            if (!GUIDE_STATE.frameworks) {
                const r = await fetch('/api/guide/frameworks');
                const d = await r.json();
                GUIDE_STATE.frameworks = d.items;
            }
            renderGuideFrameworks();
        }
    } catch (e) {
        body.innerHTML = `<div class="notif-empty">Failed to load: ${escapeNotifHtml(String(e))}</div>`;
    }
    renderGuideTabs();
}

function renderGuideTabs() {
    const el = document.getElementById('guideTabs');
    if (!el) return;
    el.innerHTML = GUIDE_TABS.map(t => `
        <button class="notif-tab ${t.key === GUIDE_STATE.tab ? 'active' : ''}" data-tab="${t.key}">${t.label}</button>
    `).join('');
    el.querySelectorAll('.notif-tab').forEach(b => {
        b.addEventListener('click', () => loadGuideTab(b.dataset.tab));
    });
}

function renderGuidePage() {
    const g = GUIDE_STATE.pageGuide;
    if (!g) return;
    const list = (items) => items && items.length
        ? `<ul class="guide-list">${items.map(x => `<li>${escapeNotifHtml(x)}</li>`).join('')}</ul>`
        : '<div class="guide-empty">—</div>';
    const seeAlso = (g.see_also || []).length
        ? `<div class="guide-section"><h4>See also</h4>${g.see_also.map(s => `<a class="guide-chip" href="${escapeNotifAttr(s.href)}">${escapeNotifHtml(s.label)} ›</a>`).join('')}</div>`
        : '';
    document.getElementById('guideBody').innerHTML = `
        <div class="guide-hero">
            <div class="guide-hero-title">${escapeNotifHtml(g.title)}</div>
            <div class="guide-hero-q"><strong>Primary question:</strong> ${escapeNotifHtml(g.primary_question)}</div>
        </div>
        <div class="guide-section"><h4>What does this page mean?</h4><p>${escapeNotifHtml(g.what_it_means)}</p></div>
        <div class="guide-section"><h4>Which framework applies here?</h4>${list(g.frameworks)}</div>
        <div class="guide-section"><h4>What should I do next?</h4>${list(g.next_actions)}</div>
        <div class="guide-section"><h4>What blocks production release?</h4>${list(g.blocks_production)}</div>
        <div class="guide-section"><h4>Required evidence</h4>${list(g.required_evidence)}</div>
        <div class="guide-section"><h4>Recommended remediation</h4>${list(g.recommended_remediation)}</div>
        ${seeAlso}
    `;
}

function renderGuideGlossary() {
    const groups = {};
    (GUIDE_STATE.glossary || []).forEach(t => {
        (groups[t.category] = groups[t.category] || []).push(t);
    });
    const sections = Object.keys(groups).sort().map(cat => `
        <div class="guide-section">
            <h4>${escapeNotifHtml(cat)}</h4>
            <dl class="guide-dl">
                ${groups[cat].map(t => `
                    <dt>${escapeNotifHtml(t.term)}</dt>
                    <dd>${escapeNotifHtml(t.definition)}</dd>
                `).join('')}
            </dl>
        </div>
    `).join('');
    document.getElementById('guideBody').innerHTML = sections
        || '<div class="guide-empty">No glossary terms loaded.</div>';
}

function renderGuideControls() {
    const groups = {};
    (GUIDE_STATE.controls || []).forEach(c => {
        (groups[c.domain] = groups[c.domain] || []).push(c);
    });
    const html = Object.keys(groups).sort().map(dom => `
        <div class="guide-section">
            <h4>${escapeNotifHtml(dom.replace(/_/g, ' '))}</h4>
            <div class="guide-control-grid">
                ${groups[dom].map(c => `
                    <button class="guide-control-row" data-ctrl="${escapeNotifAttr(c.control_id)}">
                        <span class="notif-meta-pill">${escapeNotifHtml(c.priority)}</span>
                        <strong>${escapeNotifHtml(c.control_id)}</strong>
                        <span>${escapeNotifHtml(c.title)}</span>
                    </button>
                `).join('')}
            </div>
        </div>
    `).join('');
    document.getElementById('guideBody').innerHTML = html;
    document.querySelectorAll('.guide-control-row').forEach(b => {
        b.addEventListener('click', () => showControlDetail(b.dataset.ctrl));
    });
}

async function showControlDetail(cid) {
    const r = await fetch(`/api/guide/controls/${encodeURIComponent(cid)}`);
    if (!r.ok) return;
    const c = await r.json();
    document.getElementById('guideBody').innerHTML = `
        <button class="guide-back" id="guideBackBtn">‹ Back to Controls</button>
        <div class="guide-hero">
            <div class="guide-hero-title">${escapeNotifHtml(c.control_id)} — ${escapeNotifHtml(c.title)}</div>
            <div class="guide-hero-q">
                <span class="notif-meta-pill">${escapeNotifHtml(c.priority)}</span>
                <span class="notif-meta-pill">${escapeNotifHtml(c.domain)}</span>
                <span class="notif-meta-pill">${c.automated ? 'Automated' : 'Manual'}</span>
                <span class="notif-meta-pill">Owner: ${escapeNotifHtml(c.recommended_owner)}</span>
            </div>
        </div>
        <div class="guide-section"><h4>Requirement</h4><p>${escapeNotifHtml(c.requirement)}</p></div>
        <div class="guide-section"><h4>Pass criteria</h4><p>${escapeNotifHtml(c.pass_criteria)}</p></div>
        ${c.gate_expression ? `<div class="guide-section"><h4>Gate expression</h4><pre class="guide-pre">${escapeNotifHtml(c.gate_expression)}</pre></div>` : ''}
        <div class="guide-section"><h4>Failure impact</h4><p>${escapeNotifHtml(c.failure_impact)}</p></div>
        <div class="guide-section"><h4>Required evidence</h4>
            <div class="guide-pills">${(c.evidence_required||[]).map(e => `<span class="notif-meta-pill">${escapeNotifHtml(e)}</span>`).join('')}</div>
        </div>
        <div class="guide-section"><h4>Framework mappings</h4>
            <div class="guide-pills">${(c.framework_mappings||[]).map(fm => `<span class="notif-meta-pill"><strong>${escapeNotifHtml(fm.framework)}</strong> · ${escapeNotifHtml(fm.clause)}</span>`).join('')}</div>
        </div>
    `;
    document.getElementById('guideBackBtn').addEventListener('click', () => loadGuideTab('controls'));
}

function renderGuideFrameworks() {
    const groups = {};
    (GUIDE_STATE.frameworks || []).forEach(it => {
        (groups[it.framework] = groups[it.framework] || []).push(it);
    });
    const html = Object.keys(groups).sort().map(fw => `
        <div class="guide-section">
            <h4>${escapeNotifHtml(fw.replace(/_/g, ' '))}</h4>
            <div class="guide-control-grid">
                ${groups[fw].map(it => `
                    <button class="guide-control-row" data-fid="${escapeNotifAttr(it.id)}">
                        <strong>${escapeNotifHtml(it.display_name)}</strong>
                        <span>${escapeNotifHtml(it.snippet)}</span>
                    </button>
                `).join('')}
            </div>
        </div>
    `).join('');
    document.getElementById('guideBody').innerHTML = html;
    document.querySelectorAll('.guide-control-row').forEach(b => {
        b.addEventListener('click', () => showFrameworkItemDetail(b.dataset.fid));
    });
}

async function showFrameworkItemDetail(fid) {
    const r = await fetch(`/api/guide/framework-item?q=${encodeURIComponent(fid)}`);
    if (!r.ok) return;
    const it = await r.json();
    document.getElementById('guideBody').innerHTML = `
        <button class="guide-back" id="guideBackBtn">‹ Back to Frameworks</button>
        <div class="guide-hero">
            <div class="guide-hero-title">${escapeNotifHtml(it.display_name)}</div>
            <div class="guide-hero-q">
                <span class="notif-meta-pill">${escapeNotifHtml(it.framework)}</span>
                <span class="notif-meta-pill">Owner: ${escapeNotifHtml(it.recommended_owner)}</span>
            </div>
        </div>
        <div class="guide-section"><h4>What it covers</h4><p>${escapeNotifHtml(it.description)}</p></div>
        ${it.exact_clauses?.length ? `<div class="guide-section"><h4>Clauses</h4><div class="guide-pills">${it.exact_clauses.map(c => `<span class="notif-meta-pill">${escapeNotifHtml(c)}</span>`).join('')}</div></div>` : ''}
    `;
    document.getElementById('guideBackBtn').addEventListener('click', () => loadGuideTab('frameworks'));
}

async function runGuideSearch(q) {
    GUIDE_STATE.searchTerm = q;
    const body = document.getElementById('guideBody');
    if (!q || q.length < 2) {
        loadGuideTab(GUIDE_STATE.tab);
        return;
    }
    body.innerHTML = '<div class="notif-empty">Searching…</div>';
    try {
        const r = await fetch(`/api/guide/search?q=${encodeURIComponent(q)}`);
        const d = await r.json();
        const ctrls = (d.controls||[]).map(c => `
            <button class="guide-control-row" data-ctrl="${escapeNotifAttr(c.control_id)}">
                <span class="notif-meta-pill">${escapeNotifHtml(c.priority)}</span>
                <strong>${escapeNotifHtml(c.control_id)}</strong>
                <span>${escapeNotifHtml(c.title)}</span>
            </button>
        `).join('');
        const items = (d.framework_items||[]).map(it => `
            <button class="guide-control-row" data-fid="${escapeNotifAttr(it.id)}">
                <span class="notif-meta-pill">${escapeNotifHtml(it.framework)}</span>
                <strong>${escapeNotifHtml(it.display_name)}</strong>
                <span>${escapeNotifHtml(it.snippet)}</span>
            </button>
        `).join('');
        const gloss = (d.glossary||[]).map(t => `
            <div class="guide-glossary-row">
                <div class="guide-glossary-term">${escapeNotifHtml(t.term)} <span class="notif-meta-pill">${escapeNotifHtml(t.category)}</span></div>
                <div class="guide-glossary-def">${escapeNotifHtml(t.definition)}</div>
            </div>
        `).join('');
        const totalHits = (d.controls||[]).length + (d.framework_items||[]).length + (d.glossary||[]).length;
        body.innerHTML = `
            <div class="guide-hero"><div class="guide-hero-title">Search: "${escapeNotifHtml(q)}"</div>
              <div class="guide-hero-q">${totalHits} result${totalHits === 1 ? '' : 's'}</div></div>
            ${ctrls ? `<div class="guide-section"><h4>Controls</h4><div class="guide-control-grid">${ctrls}</div></div>` : ''}
            ${items ? `<div class="guide-section"><h4>Framework items</h4><div class="guide-control-grid">${items}</div></div>` : ''}
            ${gloss ? `<div class="guide-section"><h4>Glossary</h4>${gloss}</div>` : ''}
            ${!totalHits ? '<div class="guide-empty">No matches.</div>' : ''}
        `;
        body.querySelectorAll('.guide-control-row[data-ctrl]').forEach(b =>
            b.addEventListener('click', () => showControlDetail(b.dataset.ctrl)));
        body.querySelectorAll('.guide-control-row[data-fid]').forEach(b =>
            b.addEventListener('click', () => showFrameworkItemDetail(b.dataset.fid)));
    } catch (e) {
        body.innerHTML = `<div class="notif-empty">Search failed.</div>`;
    }
}

function openGuidePanel() {
    const panel = document.getElementById('guidePanel');
    const overlay = document.getElementById('guideOverlay');
    if (!panel || !overlay) return;
    panel.classList.add('open');
    overlay.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    loadGuideTab(GUIDE_STATE.tab);
}
function closeGuidePanel() {
    const panel = document.getElementById('guidePanel');
    const overlay = document.getElementById('guideOverlay');
    if (!panel || !overlay) return;
    panel.classList.remove('open');
    overlay.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
}
function wireGuidePanel() {
    const btn = document.getElementById('guideBtn');
    if (btn) btn.addEventListener('click', openGuidePanel);
    const close = document.getElementById('guideCloseBtn');
    if (close) close.addEventListener('click', closeGuidePanel);
    const overlay = document.getElementById('guideOverlay');
    if (overlay) overlay.addEventListener('click', closeGuidePanel);
    const input = document.getElementById('guideSearchInput');
    if (input) {
        let t = null;
        input.addEventListener('input', (e) => {
            clearTimeout(t);
            t = setTimeout(() => runGuideSearch(e.target.value.trim()), 200);
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeGuidePanel();
    });
}

function renderNotificationPanel() {
    return `
        <div class="notif-overlay" id="notifOverlay"></div>
        <aside class="notif-panel" id="notifPanel" aria-hidden="true">
            <header class="notif-header">
                <div>
                    <div class="notif-title">AI Risk Operations</div>
                    <div class="notif-subtitle" id="notifSubtitle">Loading…</div>
                </div>
                <button class="notif-close" id="notifCloseBtn" aria-label="Close">×</button>
            </header>
            <div class="notif-tabs" id="notifTabs"></div>
            <div class="notif-list" id="notifList">
                <div class="notif-empty">Loading…</div>
            </div>
            <footer class="notif-footer">
                <a href="/findings" class="notif-link">View All Incidents ›</a>
                <button class="notif-reset" id="notifResetBtn" title="Clear local 'resolved' state">Reset</button>
            </footer>
        </aside>
    `;
}

// ============================================================================
// Notification center — runtime
// ============================================================================

const NOTIF_TABS = [
    { key: 'all',       label: 'All' },
    { key: 'critical',  label: 'Critical' },
    { key: 'release',   label: 'Release' },
    { key: 'runtime',   label: 'Runtime' },
    { key: 'approvals', label: 'Approvals' },
];

const NOTIF_STATE = { tab: 'all', items: [], unread: 0, byTab: {}, bySeverity: {} };

async function loadNotifications() {
    try {
        const r = await fetch('/api/grc/notifications?include_resolved=true');
        const d = await r.json();
        NOTIF_STATE.items = d.items || [];
        NOTIF_STATE.unread = d.unread || 0;
        NOTIF_STATE.byTab = d.counts_by_tab || {};
        NOTIF_STATE.bySeverity = d.counts_by_severity || {};
        renderNotifBadge();
        renderNotifPanelBody();
    } catch (e) {
        const list = document.getElementById('notifList');
        if (list) list.innerHTML = `<div class="notif-empty">Failed to load: ${escapeNotifHtml(String(e))}</div>`;
    }
}

function renderNotifBadge() {
    const dot = document.getElementById('notifUnreadDot');
    if (!dot) return;
    if (NOTIF_STATE.unread > 0) {
        dot.style.display = '';
        dot.textContent = NOTIF_STATE.unread > 99 ? '99+' : String(NOTIF_STATE.unread);
    } else {
        dot.style.display = 'none';
    }
}

function renderNotifPanelBody() {
    const subtitle = document.getElementById('notifSubtitle');
    const tabsEl = document.getElementById('notifTabs');
    const list = document.getElementById('notifList');
    if (!subtitle || !tabsEl || !list) return;

    const sev = NOTIF_STATE.bySeverity || {};
    subtitle.innerHTML = `
        <span class="notif-sev-pill crit">${sev.CRITICAL || 0} CRITICAL</span>
        <span class="notif-sev-pill high">${sev.HIGH || 0} HIGH</span>
        <span class="notif-sev-pill med">${sev.MEDIUM || 0} MEDIUM</span>
        <span class="notif-sev-pill low">${(sev.LOW || 0) + (sev.INFO || 0)} INFO</span>
    `;

    tabsEl.innerHTML = NOTIF_TABS.map(t => {
        const count = (NOTIF_STATE.byTab || {})[t.key] || 0;
        const active = t.key === NOTIF_STATE.tab ? 'active' : '';
        return `<button class="notif-tab ${active}" data-tab="${t.key}">${t.label} <span class="notif-tab-count">${count}</span></button>`;
    }).join('');
    tabsEl.querySelectorAll('.notif-tab').forEach(b => {
        b.addEventListener('click', () => {
            NOTIF_STATE.tab = b.dataset.tab;
            renderNotifPanelBody();
        });
    });

    const filtered = NOTIF_STATE.items
        .filter(n => !n.resolved)
        .filter(n => NOTIF_STATE.tab === 'all' || n.tab === NOTIF_STATE.tab);

    if (!filtered.length) {
        list.innerHTML = `<div class="notif-empty">No open notifications in this view.</div>`;
        return;
    }

    list.innerHTML = filtered.map(renderNotifCard).join('');
    list.querySelectorAll('.notif-resolve').forEach(b => {
        b.addEventListener('click', async (ev) => {
            ev.stopPropagation();
            const id = b.dataset.id;
            await fetch(`/api/grc/notifications/${encodeURIComponent(id)}/resolve`, { method: 'POST' });
            await loadNotifications();
        });
    });
    list.querySelectorAll('.notif-card').forEach(card => {
        card.addEventListener('click', () => {
            const href = card.dataset.href;
            if (href) window.location.href = href;
        });
    });
}

function renderNotifCard(n) {
    const sevCls = ({CRITICAL:'crit', HIGH:'high', MEDIUM:'med', LOW:'low', INFO:'low'})[n.severity] || 'low';
    const catLabel = ({
        CRITICAL_FINDING: 'Critical Finding',
        GATE_FAILURE: 'Release Gate',
        RUNTIME_SECURITY: 'Runtime Security',
        APPROVAL_REQUEST: 'Approval',
        EVIDENCE_GAP: 'Evidence Gap',
        SLA_BREACH: 'SLA Breach',
        POLICY_VIOLATION: 'Policy',
        REASSESSMENT_REQUIRED: 'Reassessment',
        FRAMEWORK_DRIFT: 'Framework',
        AWS_TELEMETRY: 'AWS',
    })[n.category] || n.category;

    const meta = [];
    if (n.system_name) meta.push(`<span class="notif-meta-pill">${escapeNotifHtml(n.system_name)}</span>`);
    if (n.control_id)  meta.push(`<span class="notif-meta-pill">${escapeNotifHtml(n.control_id)}</span>`);
    if (n.framework)   meta.push(`<span class="notif-meta-pill">${escapeNotifHtml(n.framework)}</span>`);
    if (n.gate_id)     meta.push(`<span class="notif-meta-pill">${escapeNotifHtml(n.gate_id)}</span>`);

    const tsLabel = n.timestamp
        ? new Date(n.timestamp).toLocaleString(undefined, { month:'short', day:'numeric', hour:'numeric', minute:'2-digit' })
        : '';

    return `
        <article class="notif-card ${sevCls}" data-href="${escapeNotifAttr(n.linked_workflow || '')}">
            <div class="notif-card-head">
                <span class="notif-sev-pill ${sevCls}">${n.severity}</span>
                <span class="notif-cat">${catLabel}</span>
                <span class="notif-ts">${escapeNotifHtml(tsLabel)}</span>
            </div>
            <div class="notif-card-title">${escapeNotifHtml(n.title)}</div>
            <div class="notif-card-detail">${escapeNotifHtml(n.detail)}</div>
            <div class="notif-card-meta">${meta.join('')}</div>
            <div class="notif-card-action">${escapeNotifHtml(n.action_required || '')}</div>
            <div class="notif-card-actions">
                <a class="notif-open" href="${escapeNotifAttr(n.linked_workflow || '#')}" onclick="event.stopPropagation()">Open ›</a>
                <button class="notif-resolve" data-id="${escapeNotifAttr(n.id)}">Mark resolved</button>
            </div>
        </article>
    `;
}

function escapeNotifHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}
function escapeNotifAttr(s) { return escapeNotifHtml(s); }

// ============================================================================
// Contextual assurance-model helper — used by Summarize / Explain / Ask buttons
// ============================================================================

/**
 * Call an assurance-model endpoint and render the response into the supplied
 * container. Every call is policy-gated server-side; blocked responses render
 * with alternatives + remediation. No raw API keys are touched here.
 */
async function callAssuranceModel(endpoint, body, container) {
    if (typeof container === 'string') container = document.getElementById(container);
    if (!container) return;
    container.innerHTML = '<div class="assist-response"><div class="assist-body">Routing through policy engine…</div></div>';
    try {
        const r = await fetch(`/api/assurance-model/${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        const d = await r.json();
        if (!r.ok) {
            container.innerHTML = `<div class="assist-response blocked"><div class="assist-body">Error: ${escapeNotifHtml(d.detail || JSON.stringify(d))}</div></div>`;
            return;
        }
        renderAssuranceResponse(d, container);
    } catch (e) {
        container.innerHTML = `<div class="assist-response blocked"><div class="assist-body">Network error: ${escapeNotifHtml(String(e))}</div></div>`;
    }
}

function renderAssuranceResponse(d, container) {
    const sCls = d.status === 'blocked' ? 'bad' : (d.status === 'allowed' ? 'ok' : 'warn');
    const head = `
        <div class="assist-head">
            <span class="pill ${sCls}">${escapeNotifHtml(d.status || 'unknown')}</span>
            <span class="pill">${escapeNotifHtml(d.provider || '—')}</span>
            <span class="pill">${escapeNotifHtml(d.model || '—')}</span>
            <span class="pill">${escapeNotifHtml(d.use_case || '—')}</span>
        </div>`;
    let body = '';
    if (d.status === 'blocked') {
        const pol = d.policy_decision || {};
        const alts = (pol.alternatives || []).map(a =>
            `<li><strong>${escapeNotifHtml(a.provider_name)}</strong> — ${escapeNotifHtml(a.why)}</li>`).join('');
        const rem  = (pol.remediation || []).map(x => `<li>${escapeNotifHtml(x)}</li>`).join('');
        body = `
            <div class="assist-body"><strong>Blocked:</strong> ${escapeNotifHtml(pol.reason || d.response || '')}</div>
            ${alts ? `<div class="alts"><strong style="font-size:10px;color:var(--text-tertiary);">Allowed alternatives:</strong><ul>${alts}</ul></div>` : ''}
            ${rem ? `<div class="alts"><strong style="font-size:10px;color:var(--text-tertiary);">Remediation:</strong><ul>${rem}</ul></div>` : ''}
        `;
        container.innerHTML = `<div class="assist-response blocked">${head}${body}<div class="assist-meta">audit: ${escapeNotifHtml(d.audit_event_id || '')}</div></div>`;
        return;
    }
    body = `<div class="assist-body">${escapeNotifHtml(d.response || '')}</div>`;
    const meta = `<div class="assist-meta">audit: ${escapeNotifHtml(d.audit_event_id || '')} · status: ${escapeNotifHtml(d.status)} · ${(d.sanitized_redactions || []).length ? 'redacted: ' + d.sanitized_redactions.join(', ') : 'no redactions needed'}</div>`;
    container.innerHTML = `<div class="assist-response">${head}${body}${meta}</div>`;
}

window.callAssuranceModel = callAssuranceModel;

// ============================================================================
// Info tooltips — hover/focus help next to KPI labels, chart titles, columns.
// Markup: <span class="info-tip" data-tip-id="kpi.foo" tabindex="0">?</span>
// Or inline: <span class="info-tip" data-tip="Description here">?</span>
// ============================================================================

const TIP_STATE = { registry: null, pop: null, current: null };

async function loadTipRegistry() {
    if (TIP_STATE.registry) return TIP_STATE.registry;
    try {
        const r = await fetch('/api/guide/tips');
        const d = await r.json();
        TIP_STATE.registry = d.tips || {};
    } catch (e) {
        TIP_STATE.registry = {};
    }
    return TIP_STATE.registry;
}

function ensureTipPop() {
    if (TIP_STATE.pop) return TIP_STATE.pop;
    const p = document.createElement('div');
    p.className = 'info-pop';
    p.setAttribute('role', 'tooltip');
    document.body.appendChild(p);
    TIP_STATE.pop = p;
    return p;
}

function positionTipPop(target) {
    const pop = ensureTipPop();
    const r = target.getBoundingClientRect();
    const pr = pop.getBoundingClientRect();
    const margin = 8;
    // Prefer above, fall back below if no room.
    let top = r.top - pr.height - margin;
    if (top < margin) top = r.bottom + margin;
    let left = r.left + r.width / 2 - pr.width / 2;
    if (left < margin) left = margin;
    if (left + pr.width > window.innerWidth - margin) {
        left = window.innerWidth - pr.width - margin;
    }
    pop.style.top  = `${Math.round(top)}px`;
    pop.style.left = `${Math.round(left)}px`;
}

function showTip(target) {
    const pop = ensureTipPop();
    const tipId = target.dataset.tipId;
    const inline = target.dataset.tip;

    let content = null;
    if (tipId && TIP_STATE.registry && TIP_STATE.registry[tipId]) {
        content = TIP_STATE.registry[tipId];
    } else if (inline) {
        content = { title: target.dataset.tipTitle || '', description: inline };
    } else if (tipId) {
        content = { title: tipId, description: 'No description registered yet.' };
    } else {
        return;
    }

    const titleHtml = content.title ? `<div class="info-pop-title">${escapeNotifHtml(content.title)}</div>` : '';
    const descHtml  = content.description ? `<div class="info-pop-desc">${escapeNotifHtml(content.description)}</div>` : '';
    let meta = '';
    if (content.formula) meta += `<div><b>Formula:</b> ${escapeNotifHtml(content.formula)}</div>`;
    if (content.source)  meta += `<div><b>Source:</b> ${escapeNotifHtml(content.source)}</div>`;
    const metaHtml = meta ? `<div class="info-pop-meta">${meta}</div>` : '';

    pop.innerHTML = titleHtml + descHtml + metaHtml;
    pop.classList.add('show');
    // First show before positioning so we can measure size
    requestAnimationFrame(() => positionTipPop(target));
    TIP_STATE.current = target;
}

function hideTip() {
    if (TIP_STATE.pop) TIP_STATE.pop.classList.remove('show');
    TIP_STATE.current = null;
}

function wireTooltips(root = document) {
    root.querySelectorAll('.info-tip').forEach(el => {
        if (el.dataset.tipWired === '1') return;
        el.dataset.tipWired = '1';
        if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
        if (!el.textContent.trim()) el.textContent = '?';
        el.setAttribute('aria-label',
            el.dataset.tipTitle || el.dataset.tipId || el.dataset.tip || 'More info');
        el.addEventListener('mouseenter', () => showTip(el));
        el.addEventListener('mouseleave', hideTip);
        el.addEventListener('focus',  () => showTip(el));
        el.addEventListener('blur',   hideTip);
    });
}

// Re-scan whenever the page mutates (KPIs/cards are usually injected by fetch).
const _tipObserver = new MutationObserver(() => wireTooltips());
function startTipObserver() {
    if (TIP_STATE.observerRunning) return;
    TIP_STATE.observerRunning = true;
    _tipObserver.observe(document.body, { childList: true, subtree: true });
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideTip(); });

// Kick off
loadTipRegistry().then(() => { wireTooltips(); startTipObserver(); });

window.wireTooltips = wireTooltips;

function openNotifPanel() {
    const panel = document.getElementById('notifPanel');
    const overlay = document.getElementById('notifOverlay');
    if (!panel || !overlay) return;
    panel.classList.add('open');
    overlay.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    loadNotifications();
}
function closeNotifPanel() {
    const panel = document.getElementById('notifPanel');
    const overlay = document.getElementById('notifOverlay');
    if (!panel || !overlay) return;
    panel.classList.remove('open');
    overlay.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
}
function wireNotifPanel() {
    const bell = document.getElementById('notifBellBtn');
    if (bell) bell.addEventListener('click', openNotifPanel);
    const close = document.getElementById('notifCloseBtn');
    if (close) close.addEventListener('click', closeNotifPanel);
    const overlay = document.getElementById('notifOverlay');
    if (overlay) overlay.addEventListener('click', closeNotifPanel);
    const reset = document.getElementById('notifResetBtn');
    if (reset) reset.addEventListener('click', async () => {
        if (!confirm('Reset locally resolved notifications? This restores the inbox to its computed state.')) return;
        await fetch('/api/grc/notifications/reset', { method: 'POST' });
        await loadNotifications();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeNotifPanel();
    });
    // Initial unread-count fetch so the dot is accurate before the panel opens.
    loadNotifications();
}

function severityBadge(severity) {
    const map = {
        CRITICAL: 'badge-critical',
        HIGH: 'badge-high',
        MEDIUM: 'badge-medium',
        LOW: 'badge-low',
        INFO: 'badge-info',
        PASS: 'badge-pass',
        P0: 'badge-critical',
        P1: 'badge-high',
        P2: 'badge-medium',
    };
    return `<span class="badge ${map[severity] || 'badge-neutral'}">${severity}</span>`;
}

function decisionBadge(decision) {
    const map = {
        APPROVED: { cls: 'decision-approved', label: 'Approved' },
        APPROVED_PILOT: { cls: 'decision-approved', label: 'Approved Pilot' },
        CONDITIONAL_PILOT: { cls: 'decision-conditional', label: 'Conditional Pilot' },
        HOLD: { cls: 'decision-hold', label: 'Hold' },
        REJECT: { cls: 'decision-reject', label: 'Reject' },
    };
    const info = map[decision] || { cls: 'badge-neutral', label: decision };
    return `<span class="badge ${info.cls}">${info.label}</span>`;
}

function statusBadge(status) {
    const map = {
        OPEN: 'badge-critical',
        IN_PROGRESS: 'badge-high',
        REMEDIATED: 'badge-pass',
        VERIFIED: 'badge-pass',
        RISK_ACCEPTED: 'badge-neutral',
        PASS: 'badge-pass',
        FAIL: 'badge-critical',
    };
    return `<span class="badge ${map[status] || 'badge-neutral'}">${status.replace(/_/g, ' ')}</span>`;
}

function frameworkBadges(frameworks) {
    if (!frameworks || frameworks.length === 0) return '';
    return frameworks.map(f => `<span class="framework-badge">${f}</span>`).join('');
}

function actionBadge(action) {
    const cls = {
        Blocked: 'action-blocked',
        Masked: 'action-masked',
        Escalated: 'action-escalated',
    }[action] || 'badge-neutral';
    return `<span class="action-badge ${cls}">${action}</span>`;
}

function riskDot(level) {
    const cls = level.toLowerCase();
    return `<span class="risk-dot ${cls}"></span>${level.charAt(0) + level.slice(1).toLowerCase()}`;
}

function slaCell(remainingHours) {
    if (remainingHours == null) return '—';
    if (remainingHours < 0) return `<span class="sla-breach">${Math.abs(remainingHours)}h overdue</span>`;
    if (remainingHours < 24) return `<span class="sla-warning">${remainingHours}h left</span>`;
    if (remainingHours < 72) return `<span class="text-medium">${Math.floor(remainingHours / 24)}d ${remainingHours % 24}h</span>`;
    return `<span class="text-secondary">${Math.floor(remainingHours / 24)}d</span>`;
}

function timeAgo(iso) {
    const then = new Date(iso);
    const seconds = Math.floor((Date.now() - then) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function runtimeStatusDot(status) {
    const map = {
        PRODUCTION: 'production',
        PILOT: 'pilot',
        STAGED: 'staged',
    };
    const cls = map[status] || 'pilot';
    return `<span class="status-dot ${cls}"></span>${status.charAt(0) + status.slice(1).toLowerCase()}`;
}

/* === SVG donut chart === */
function renderDonut(segments, size = 140, strokeWidth = 22, centerText = '', centerSubtext = '') {
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const total = segments.reduce((s, x) => s + x.value, 0);

    let offset = 0;
    const arcs = segments.map(seg => {
        const portion = total > 0 ? seg.value / total : 0;
        const length = circumference * portion;
        const arc = `<circle cx="${size/2}" cy="${size/2}" r="${radius}"
                     stroke="${seg.color}" stroke-width="${strokeWidth}" fill="none"
                     stroke-dasharray="${length} ${circumference - length}"
                     stroke-dashoffset="${-offset}"/>`;
        offset += length;
        return arc;
    }).join('');

    const center = centerText
        ? `<text x="${size/2}" y="${size/2 - 4}" text-anchor="middle" dy="0.3em"
                 fill="#e4e8f0" font-size="22" font-weight="700" transform="rotate(90 ${size/2} ${size/2})">${centerText}</text>
            <text x="${size/2}" y="${size/2 + 14}" text-anchor="middle"
                 fill="#98a3b8" font-size="10" transform="rotate(90 ${size/2} ${size/2})">${centerSubtext}</text>`
        : '';

    return `<svg class="donut-svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="transform: rotate(-90deg);">
        <circle cx="${size/2}" cy="${size/2}" r="${radius}" stroke="#1d2436" stroke-width="${strokeWidth}" fill="none"/>
        ${arcs}
        ${center}
    </svg>`;
}

/* === SVG line chart === */
function renderLineChart(series, options = {}) {
    const width = options.width || 700;
    const height = options.height || 200;
    const padding = { left: 30, right: 16, top: 20, bottom: 30 };
    const innerW = width - padding.left - padding.right;
    const innerH = height - padding.top - padding.bottom;

    const allValues = series.flatMap(s => s.data);
    const maxY = Math.max(...allValues, 10);
    const numPoints = series[0].data.length;

    // X-axis labels (dates)
    const xLabels = options.xLabels || Array(numPoints).fill('');

    // Grid lines
    let grid = '';
    for (let i = 0; i <= 4; i++) {
        const y = padding.top + (innerH / 4) * i;
        grid += `<line x1="${padding.left}" y1="${y}" x2="${padding.left + innerW}" y2="${y}" stroke="#1d2436" stroke-width="1"/>`;
        const value = Math.round(maxY - (maxY / 4) * i);
        grid += `<text x="${padding.left - 6}" y="${y + 3}" text-anchor="end" fill="#6b7689" font-size="10">${value}</text>`;
    }

    // X-axis labels
    let xAxis = '';
    xLabels.forEach((label, i) => {
        if (i % Math.max(1, Math.floor(numPoints / 6)) === 0 || i === numPoints - 1) {
            const x = padding.left + (innerW / (numPoints - 1)) * i;
            xAxis += `<text x="${x}" y="${height - 10}" text-anchor="middle" fill="#6b7689" font-size="10">${label}</text>`;
        }
    });

    // Lines and dots
    const lines = series.map(s => {
        const points = s.data.map((v, i) => {
            const x = padding.left + (innerW / (numPoints - 1)) * i;
            const y = padding.top + innerH - (v / maxY) * innerH;
            return [x, y];
        });

        const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p[0]} ${p[1]}`).join(' ');
        const line = `<path d="${path}" stroke="${s.color}" stroke-width="2" fill="none"/>`;
        const dots = points.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="${s.color}"/>`).join('');
        return line + dots;
    }).join('');

    return `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="max-width: 100%;">
        ${grid}
        ${xAxis}
        ${lines}
    </svg>`;
}

function initPage(activePath) {
    const sidebarEl = document.getElementById('sidebar');
    const topbarEl = document.getElementById('topbar');
    const appEl = document.querySelector('.app');

    if (appEl && sidebarEl && topbarEl) {
        // New layout: fill in shells
        sidebarEl.outerHTML = renderSidebar(activePath);
        topbarEl.outerHTML = renderTopbar();
        wireNotifPanel();
    setGuideActivePath(activePath);
    wireGuidePanel();
    wireTopbarIdentity();
        return;
    }

    // Legacy layout: capture every body child EXCEPT the orphan #topbar/#sidebar
    // shell divs. Some pages have siblings of `.page` (e.g. modal overlays) that
    // would be discarded if we only kept `.page.outerHTML`.
    const SKIP = new Set(['topbar', 'sidebar']);
    const preserved = Array.from(document.body.children)
        .filter(el => !(el.id && SKIP.has(el.id)))
        .map(el => el.outerHTML)
        .join('');

    document.body.innerHTML = `
        <div class="app">
            ${renderSidebar(activePath)}
            <div class="main">
                ${renderTopbar()}
                ${preserved}
            </div>
        </div>
    `;
    wireNotifPanel();
    setGuideActivePath(activePath);
    wireGuidePanel();
    wireTopbarIdentity();
}
