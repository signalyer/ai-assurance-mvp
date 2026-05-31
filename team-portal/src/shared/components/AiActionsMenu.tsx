// AiActionsMenu — S73: shared dropdown for LLM action surfaces.
//
// Background: S72 wired 4 LLM actions inline as adjacent <button> elements
// on AiSystemDrawer + FindingsInboxPage. With Ask + Draft Report joining
// Edit/Revisions/Frameworks/BoundAgents/RunAssessment in the drawer footer
// the row hit 7 controls — visual clutter, and each new AI use case piles
// on. This menu consolidates LLM-only actions into one "AI Actions ▾"
// affordance; operational actions stay inline.
//
// Used by:
//   - team-portal/AiSystemDrawer.tsx (Ask AI, Draft Report)
//   - ciso-console/PortfolioPage.tsx (Ask, Draft Report) — verbatim copy
//
// Pattern: duplicate per SPA per [[two-origins-spa-vs-engine]] / S72 rule.
// No workspace package until 3+ shared components justify it.

import { useEffect, useRef, useState } from 'preact/hooks';
import { createPortal } from 'preact/compat';

export interface AiActionItem {
  key: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

interface AiActionsMenuProps {
  items: AiActionItem[];
  label?: string;
}

export function AiActionsMenu({ items, label = 'AI Actions' }: AiActionsMenuProps) {
  const [open, setOpen] = useState(false);
  // S73 hotfix v2: portal the popover to document.body. `position: fixed`
  // alone is not enough — `.drawer` has `transform: translateX(...)` for
  // its slide animation, which creates a containing block for fixed-
  // positioned descendants. That re-anchors the menu to the (offscreen)
  // transformed drawer instead of the viewport. createPortal escapes the
  // transformed ancestor entirely.
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const MENU_WIDTH = 200;

  useEffect(() => {
    if (!open) {
      setCoords(null);
      return;
    }

    function place() {
      const btn = btnRef.current;
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      const spaceBelow = window.innerHeight - r.bottom;
      const menuH = menuRef.current?.offsetHeight ?? 0;
      const openUp = menuH > 0 && spaceBelow < menuH + 8;
      const top = openUp ? Math.max(8, r.top - menuH - 4) : r.bottom + 4;
      const left = Math.min(
        Math.max(8, r.right - MENU_WIDTH),
        window.innerWidth - MENU_WIDTH - 8,
      );
      setCoords({ top, left });
    }
    place();
    // Re-place once after menu mounts so we have its real height for openUp.
    const raf = requestAnimationFrame(place);

    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (
        rootRef.current && !rootRef.current.contains(t) &&
        menuRef.current && !menuRef.current.contains(t)
      ) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    function onScroll() { setOpen(false); }

    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', place);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', place);
    };
  }, [open]);

  function pick(item: AiActionItem) {
    if (item.disabled) return;
    setOpen(false);
    item.onClick();
  }

  return (
    <div ref={rootRef} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        ref={btnRef}
        class="btn btn-sm btn-secondary"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {label} {open ? '▴' : '▾'}
      </button>
      {open && createPortal(
        <div
          ref={menuRef}
          role="menu"
          style={{
            position: 'fixed',
            top: coords?.top ?? -9999,
            left: coords?.left ?? -9999,
            visibility: coords ? 'visible' : 'hidden',
            zIndex: 1000,
            width: MENU_WIDTH,
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
            padding: 4,
          }}
        >
          {items.map((item) => (
            <button
              key={item.key}
              role="menuitem"
              disabled={item.disabled}
              onClick={() => pick(item)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '6px 10px',
                fontSize: 13,
                background: 'transparent',
                color: 'var(--text-primary)',
                border: 'none',
                borderRadius: 4,
                cursor: item.disabled ? 'not-allowed' : 'pointer',
                opacity: item.disabled ? 0.5 : 1,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'var(--bg-card-hover)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
              }}
            >
              {item.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}
