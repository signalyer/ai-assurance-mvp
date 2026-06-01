import { Link, useLocation } from 'wouter-preact';

interface NavItem {
  path: string;
  label: string;
  badge?: string;
  badgeClass?: string;
}

// Team Workspace nav — engineer-facing surfaces only.
// V1's full nav (governance, findings, release gates, etc.) lives on the CISO Console.
// Per V2-PORTAL-SPLIT.md §3, Team Workspace has 12 surfaces; Phase 2 ships the first 4.
const NAV_ITEMS: NavItem[] = [
  { path: '/ai-systems', label: 'AI Systems' },
  { path: '/runtime', label: 'Runtime' },
  { path: '/evals', label: 'Evals' },
  { path: '/agent-library', label: 'Agent Library' },
  { path: '/agent-runner', label: 'Agent Runner', badge: 'NEW', badgeClass: 'sidebar-nav-badge-new' },
  { path: '/agent-runs', label: 'Agent Runs' },
  { path: '/memory', label: 'Memory' },
  { path: '/sdk', label: 'SDK Quickstart' },
  { path: '/rtf', label: 'Right-to-Forget' },
  { path: '/portfolio', label: 'My Portfolio' },
  { path: '/rag', label: 'RAG Corpus' },
  { path: '/adversarial', label: 'Adversarial Suite' },
];

export function Sidebar() {
  const [location] = useLocation();

  return (
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="sidebar-brand-icon">⬢</div>
        <div>
          <div class="sidebar-brand-text">AI ASSURANCE</div>
          <div class="sidebar-brand-subtitle">Team Workspace</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        {NAV_ITEMS.map((item) => {
          const isActive = location === item.path || (location === '/' && item.path === '/ai-systems');
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
