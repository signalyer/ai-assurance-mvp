// CISO Console — top-level router.
// Per A7 acceptance criterion: default landing route is /findings.
// CSM-1 wires: /findings, /audit, /rtf-approvals.
// CSM-2/3/4 will replace stubs with real implementations.

import { Route, Switch, Redirect } from 'wouter-preact';
import { Shell } from './shared/components/Shell';

// CSM-1 — wired surfaces
import { FindingsInboxPage }     from './pages/findings/FindingsInboxPage';
import { AuditVerifyPage }       from './pages/audit/AuditVerifyPage';
import { RtfApprovalQueuePage }  from './pages/rtf/RtfApprovalQueuePage';

// CSM-2 stubs
import { PortfolioPage }         from './pages/portfolio/PortfolioPage';
import { ReleaseGatesPage }      from './pages/release-gates/ReleaseGatesPage';
import { FrameworksPage }        from './pages/frameworks/FrameworksPage';

// CSM-3 wired
import { EvidencePage }          from './pages/evidence/EvidencePage';
import { AnalyticsPage }         from './pages/analytics/AnalyticsPage';
import { RtfForensicsPage }      from './pages/rtf-forensics/RtfForensicsPage';

// CSM-4 stubs
import { PoliciesPage }          from './pages/policies/PoliciesPage';
import { ReportsPage }           from './pages/reports/ReportsPage';

export function App() {
  return (
    <Shell>
      <Switch>
        {/* Default landing — per A7, CISO login lands on /findings */}
        <Route path="/">
          <Redirect to="/findings" />
        </Route>

        {/* CSM-1: wired */}
        <Route path="/findings"       component={FindingsInboxPage} />
        <Route path="/audit"          component={AuditVerifyPage} />
        <Route path="/rtf-approvals"  component={RtfApprovalQueuePage} />

        {/* CSM-2: stubs */}
        <Route path="/portfolio"      component={PortfolioPage} />
        <Route path="/release-gates"  component={ReleaseGatesPage} />
        <Route path="/frameworks"     component={FrameworksPage} />

        {/* CSM-3: wired */}
        <Route path="/evidence"        component={EvidencePage} />
        <Route path="/analytics"       component={AnalyticsPage} />
        <Route path="/rtf-forensics"   component={RtfForensicsPage} />

        {/* CSM-4: stubs */}
        <Route path="/policies"       component={PoliciesPage} />
        <Route path="/reports"        component={ReportsPage} />

        <Route>
          <div class="empty-state">Page not found.</div>
        </Route>
      </Switch>
    </Shell>
  );
}
