// AI Assurance Control Plane — Shared components

const NAV_ITEMS = [
    { path: "/", label: "Overview" },
    { path: "/ai-systems", label: "AI Systems" },
    { path: "/governance", label: "Governance" },
    { path: "/security", label: "Security" },
    { path: "/runtime", label: "Runtime" },
    { path: "/evals", label: "Evals" },
    { path: "/findings", label: "Findings", badge: "24" },
    { path: "/release-gates", label: "Release Gates", badge: "6", badgeClass: "medium" },
    { path: "/evidence", label: "Evidence" },
    { path: "/policies", label: "Policies" },
];

const QUICK_ACTIONS = [
    { label: "Run Assessment", action: "assessment" },
    { label: "View Runtime Events", action: "runtime" },
    { label: "Create Policy", action: "policy" },
    { label: "Upload Evidence", action: "evidence" },
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
        `<a class="sidebar-quick-action" data-action="${a.action}">${a.label}</a>`
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
                <button class="icon-btn"><span>🔔</span><span class="badge-dot">3</span></button>
                <button class="icon-btn"><span>?</span></button>
                <div class="user-block">
                    <div class="user-avatar">JS</div>
                    <div class="user-info">
                        <div class="user-name">Jane Smith</div>
                        <div class="user-role">CISO</div>
                    </div>
                </div>
            </div>
        </div>
    `;
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
    // If the page has explicit shell containers, fill those
    const sidebarEl = document.getElementById('sidebar');
    const topbarEl = document.getElementById('topbar');

    if (sidebarEl && topbarEl) {
        sidebarEl.outerHTML = renderSidebar(activePath);
        topbarEl.outerHTML = renderTopbar();
        return;
    }

    // Otherwise wrap existing body content
    const existingContent = document.body.innerHTML;
    document.body.innerHTML = `
        <div class="app">
            ${renderSidebar(activePath)}
            <div class="main">
                ${renderTopbar()}
                ${existingContent}
            </div>
        </div>
    `;
}
