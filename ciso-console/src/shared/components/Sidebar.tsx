import { Link, useLocation } from 'wouter-preact';

interface NavItem {
  path: string;
  label: string;
  badge?: string;
  badgeClass?: string;
}

// CISO Console nav — governance/audit-facing surfaces only.
// Per V2-PORTAL-SPLIT.md §3.2, CISO Console has 10 surfaces.
// CSM-1 wires: /findings, /audit, /rtf-approvals.
// CSM-2/3/4 will wire the remaining 7 surfaces.
const NAV_ITEMS: NavItem[] = [
  { path: '/findings',      label: 'Findings' },
  { path: '/audit',         label: 'Audit Chain' },
  { path: '/rtf-approvals',  label: 'RTF Approvals' },
  { path: '/rtf-forensics',  label: 'RTF Forensics' },
  { path: '/portfolio',     label: 'Portfolio Overview' },
  { path: '/release-gates', label: 'Release Gates' },
  { path: '/frameworks',    label: 'Framework Coverage' },
  { path: '/evidence',      label: 'Evidence Bundles' },
  { path: '/analytics',     label: 'Analytics' },
  { path: '/policies',      label: 'Policy Governance' },
  { path: '/reports',       label: 'Reports' },
];

export function Sidebar() {
  const [location] = useLocation();

  return (
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="sidebar-brand-icon">⬢</div>
        <div>
          <div class="sidebar-brand-text">AI ASSURANCE</div>
          <div class="sidebar-brand-subtitle">CISO Console</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const isActive = location === item.path || (location === '/' && item.path === '/findings');
          return (
            <Link key={item.path} href={item.path} class={isActive ? 'active' : ''}>
              {item.label}
              {item.badge ? (
                <span class={`sidebar-nav-badge ${item.badgeClass ?? ''}`}>{item.badge}</span>
              ) : null}
              {isActive ? <span class="nav-arrow">›</span> : null}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
