import type { ComponentChildren } from 'preact';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export interface ShellProps {
  children: ComponentChildren;
}

/**
 * Top-level chrome for CISO Console.
 * Mirrors the V1 sidebar + topbar layout, trimmed to the 10 CISO Console surfaces.
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
