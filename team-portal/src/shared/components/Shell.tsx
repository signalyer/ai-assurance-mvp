import type { ComponentChildren } from 'preact';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export interface ShellProps {
  children: ComponentChildren;
}

/**
 * Top-level chrome for Team Workspace.
 * Mirrors the V1 sidebar + topbar layout (static/shared.js renderSidebar/renderTopbar)
 * but trimmed to the surfaces this portal exposes.
 */
export function Shell({ children }: ShellProps) {
  return (
    <div class="app">
      <Sidebar />
      <main class="main">
        <Topbar />
        <div class="content">{children}</div>
      </main>
    </div>
  );
}
