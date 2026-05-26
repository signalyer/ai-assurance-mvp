import { signal } from '@preact/signals';
import { useEffect } from 'preact/hooks';
import { apiGet, apiPost } from '../api/client';
import type { WhoAmI } from '../api/types';
import { DataModeToggle } from './DataModeToggle';

const identity = signal<WhoAmI | null>(null);

async function loadIdentity(): Promise<void> {
  const r = await apiGet<WhoAmI>('/auth/whoami');
  if (r.ok) identity.value = r.data;
}

async function logout(): Promise<void> {
  await apiPost<void>('/auth/logout');
  window.location.href = '/login';
}

export function Topbar() {
  useEffect(() => {
    void loadIdentity();
  }, []);

  const user = identity.value?.user ?? '';
  const role = user ? user.replace(/^demo-/, '').toUpperCase() : '—';
  const initials = role.slice(0, 2) || '··';

  return (
    <div class="topbar">
      <div class="search-bar">
        <input type="text" placeholder="Search findings, systems, policies..." />
      </div>
      <div class="topbar-right">
        <DataModeToggle />
        <div class="user-block">
          <div class="user-avatar">{initials}</div>
          <div class="user-info">
            <div class="user-name">{user || 'Signed in'}</div>
            <div class="user-role">{role}</div>
          </div>
        </div>
        <button class="topbar-action topbar-logout" onClick={logout} title="Sign out">
          <span>⎋</span>
          <span class="topbar-action-label">Sign out</span>
        </button>
      </div>
    </div>
  );
}
