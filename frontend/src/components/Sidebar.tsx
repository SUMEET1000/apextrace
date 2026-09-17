/** The persistent left rail: logo, page nav, then per-page controls.
 *
 * Streamlit gave every page a `with st.sidebar:` block it filled itself. The
 * portal below is the equivalent — a page renders `<SidebarSection>` anywhere
 * in its tree and the content lands here, under the session picker, in the
 * same order it did before.
 */

import { createContext, useContext, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { NavLink } from '../lib/router';

const SidebarSlot = createContext<HTMLElement | null>(null);

/** Per-page sidebar controls. Renders into the rail, not where it is written. */
export function SidebarSection({ children }: { children: ReactNode }) {
  const slot = useContext(SidebarSlot);
  if (!slot) return null;
  return createPortal(children, slot);
}

const ROUTES = [
  {
    to: '/', label: 'Home',
    icon: <path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z" />,
  },
  {
    to: '/corner-analysis', label: 'Corner Analysis',
    icon: <path d="M3 3v18h18M7 15l3-4 3 3 5-7" />,
  },
  {
    to: '/race-arc', label: 'Race Arc & Strategy',
    icon: <path d="M3 12h4l3 8 4-16 3 8h4" />,
  },
];

export function Sidebar(
  { search, slotRef, open, onToggle, children }: {
    /** Carried onto every nav link so the session survives navigation. */
    search: string;
    slotRef: (element: HTMLDivElement | null) => void;
    open: boolean;
    onToggle: () => void;
    children: ReactNode;
  },
) {
  return (
    <>
      {!open && (
        <button type="button" className="pw-sidebar-toggle" onClick={onToggle}
                aria-label="Show the sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}
      {/* The rail is hidden with `display: none` rather than unmounted. It
          holds the session picker, and unmounting that would drop the selected
          session — which is how collapsing the sidebar, or simply loading the
          page on a phone where it starts collapsed, left the whole app blank. */}
      <aside className="pw-sidebar" data-open={open}>
      <div className="pw-sidebar-content">
        <button type="button"
                className="pw-sidebar-toggle pw-sidebar-collapse"
                style={{ position: 'static' }}
                onClick={onToggle} aria-label="Hide the sidebar">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round"
               strokeLinejoin="round">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>

        <div className="pw-sidebar-logo">
          <img src="/apextrace-logo.png" alt="ApexTrace" />
        </div>

        <nav className="pw-nav">
          {ROUTES.map((route) => (
            <NavLink key={route.to} to={route.to + search} className="pw-nav-link">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                   aria-hidden="true">
                {route.icon}
              </svg>
              {route.label}
            </NavLink>
          ))}
        </nav>

        {children}

        {/* Where a page's own controls land. */}
        <div ref={slotRef} className="pw-sidebar-slot" />
      </div>
      </aside>
    </>
  );
}

export { SidebarSlot };
