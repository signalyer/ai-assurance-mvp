import type { ComponentChildren } from 'preact';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import { AiSummaryDrawer } from './AiSummaryDrawer';

export interface ShellProps {
  children: ComponentChildren;
}

/**
 * Top-level chrome for CISO Console.
 * Mirrors the V1 sidebar + topbar layout, trimmed to the 10 CISO Console surfaces.
 *
 * S72: AiSummaryDrawer mounted at shell so any page can call openAiSummary()
 * to trigger a streaming LLM summary (findings, evidence, ad-hoc Ask).
 */
export function Shell({ children }: ShellProps) {
  return (
    <div class="app">
      <Sidebar />
      <main class="main">
        <Topbar />
        <div class="content">{children}</div>
      </main>
      <AiSummaryDrawer />
    </div>
  );
}
