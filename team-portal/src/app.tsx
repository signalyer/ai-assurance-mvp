import { Route, Switch } from 'wouter-preact';
import { Shell } from './shared/components/Shell';
import { AiSystemsPage } from './pages/ai-systems/AiSystemsPage';
import { RuntimePage } from './pages/runtime/RuntimePage';
import { EvalsPage } from './pages/evals/EvalsPage';
import { AgentLibraryPage } from './pages/agent-library/AgentLibraryPage';

export function App() {
  return (
    <Shell>
      <Switch>
        <Route path="/" component={AiSystemsPage} />
        <Route path="/ai-systems" component={AiSystemsPage} />
        <Route path="/runtime" component={RuntimePage} />
        <Route path="/evals" component={EvalsPage} />
        <Route path="/agent-library" component={AgentLibraryPage} />
        <Route>
          <div class="empty-state">Page not found.</div>
        </Route>
      </Switch>
    </Shell>
  );
}
