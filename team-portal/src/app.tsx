import { Route, Switch, useLocation } from 'wouter-preact';
import { Shell } from './shared/components/Shell';
import { AiSystemsPage } from './pages/ai-systems/AiSystemsPage';
import { RegisterSystemPage } from './pages/ai-systems/RegisterSystemPage';
import { RuntimePage } from './pages/runtime/RuntimePage';
import { EvalsPage } from './pages/evals/EvalsPage';
import { AgentLibraryPage } from './pages/agent-library/AgentLibraryPage';
import { MemoryPage } from './pages/memory/MemoryPage';
import { SdkQuickstartPage } from './pages/sdk-quickstart/SdkQuickstartPage';
import { RtfRequestPage } from './pages/rtf/RtfRequestPage';
import { PortfolioPage } from './pages/portfolio/PortfolioPage';
import { RagCorpusPage } from './pages/rag/RagCorpusPage';
import { AdversarialPage } from './pages/adversarial/AdversarialPage';
import { LoginPage } from './pages/login/LoginPage';

export function App() {
  const [location] = useLocation();
  // /login renders standalone — Shell expects an authenticated session and
  // its Sidebar/Topbar would either look broken or attempt to fetch behind
  // a 401 wall.
  if (location === '/login') {
    return <LoginPage />;
  }
  return (
    <Shell>
      <Switch>
        <Route path="/" component={AiSystemsPage} />
        <Route path="/ai-systems" component={AiSystemsPage} />
        <Route path="/ai-systems/new" component={RegisterSystemPage} />
        <Route path="/runtime" component={RuntimePage} />
        <Route path="/evals" component={EvalsPage} />
        <Route path="/agent-library" component={AgentLibraryPage} />
        <Route path="/memory" component={MemoryPage} />
        <Route path="/sdk" component={SdkQuickstartPage} />
        <Route path="/rtf" component={RtfRequestPage} />
        <Route path="/portfolio" component={PortfolioPage} />
        <Route path="/rag" component={RagCorpusPage} />
        <Route path="/adversarial" component={AdversarialPage} />
        <Route>
          <div class="empty-state">Page not found.</div>
        </Route>
      </Switch>
    </Shell>
  );
}
