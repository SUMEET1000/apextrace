/** A three-route SPA router over the History API.
 *
 * Hand-rolled rather than pulled from a library because this app has exactly
 * three routes and already owns its query-string handling: every selection on
 * every page round-trips through the URL so a view can be shared as a link,
 * and that contract (`year`, `round`, `session`, `drivers`, `laps`, `view`) is
 * the same one the Streamlit app maintained. A router package would sit on top
 * of that rather than replace it.
 *
 * The single subscription below is what makes `pushState` observable: the
 * History API fires `popstate` for back/forward but says nothing when the app
 * itself navigates, so `navigate` dispatches its own event. */

import {
  createContext, useCallback, useContext, useEffect, useMemo,
  useSyncExternalStore, type ReactNode,
} from 'react';

const NAVIGATED = 'pw:navigated';

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange);
  window.addEventListener(NAVIGATED, onChange);
  return () => {
    window.removeEventListener('popstate', onChange);
    window.removeEventListener(NAVIGATED, onChange);
  };
}

const snapshot = () => window.location.pathname + window.location.search;

/** The current path and query string, re-rendering the tree on any change. */
export function useLocation(): { pathname: string; search: string } {
  const href = useSyncExternalStore(subscribe, snapshot, snapshot);
  return useMemo(() => {
    const index = href.indexOf('?');
    return index === -1
      ? { pathname: href, search: '' }
      : { pathname: href.slice(0, index), search: href.slice(index) };
  }, [href]);
}

export function navigate(to: string, options: { replace?: boolean } = {}): void {
  if (to === snapshot()) return;
  if (options.replace) window.history.replaceState(null, '', to);
  else window.history.pushState(null, '', to);
  window.dispatchEvent(new Event(NAVIGATED));
}

/** Rewrite only the query string, keeping the current path.
 *
 * Always a `replace`: the picker writes on every render to keep the address
 * bar honest, and pushing each of those would fill the back button with
 * states the reader never chose.
 */
export function setQuery(params: URLSearchParams): void {
  const query = params.toString();
  navigate(window.location.pathname + (query ? `?${query}` : ''), { replace: true });
}

export function useQuery(): URLSearchParams {
  const { search } = useLocation();
  return useMemo(() => new URLSearchParams(search), [search]);
}

function handleClick(event: React.MouseEvent, to: string) {
  // Let the browser handle anything that is not a plain left click, so
  // middle-click and ctrl-click still open a new tab.
  if (event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(to);
  window.scrollTo({ top: 0 });
}

interface LinkProps extends Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string;
  children: ReactNode;
}

export function Link({ to, children, ...rest }: LinkProps) {
  return (
    <a href={to} onClick={(e) => handleClick(e, to)} {...rest}>
      {children}
    </a>
  );
}

/** A Link that marks itself as the current page when its path matches. */
export function NavLink({ to, children, ...rest }: LinkProps) {
  const { pathname } = useLocation();
  const path = to.split('?')[0];
  const active = pathname === path;
  return (
    <a
      href={to}
      aria-current={active ? 'page' : undefined}
      onClick={(e) => handleClick(e, to)}
      {...rest}
    >
      {children}
    </a>
  );
}

// --------------------------------------------------------------------------
// The deep-link contract
//
// Identical to the one the Streamlit app maintained, param for param, so a URL
// copied out of the old app opens the same view in this one.
// --------------------------------------------------------------------------

export interface SessionParams {
  year: number | null;
  round: number | null;
  session: string | null;
}

interface QueryContextValue {
  params: URLSearchParams;
  /** Merge keys into the query string. `null` removes a key. */
  update: (patch: Record<string, string | null>) => void;
}

const QueryContext = createContext<QueryContextValue | null>(null);

export function QueryProvider({ children }: { children: ReactNode }) {
  const params = useQuery();

  const update = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(window.location.search);
    let changed = false;
    for (const [key, value] of Object.entries(patch)) {
      const current = next.get(key);
      if (value === null) {
        if (current !== null) { next.delete(key); changed = true; }
      } else if (current !== value) {
        next.set(key, value);
        changed = true;
      }
    }
    // Writing an unchanged query string would still be a state replacement,
    // and doing it inside an effect on every render is an infinite loop.
    if (changed) setQuery(next);
  }, []);

  const value = useMemo(() => ({ params, update }), [params, update]);
  return <QueryContext.Provider value={value}>{children}</QueryContext.Provider>;
}

export function useQueryParams(): QueryContextValue {
  const value = useContext(QueryContext);
  if (!value) throw new Error('useQueryParams must be used inside QueryProvider');
  return value;
}

/** Build a link to `route` carrying the given query parameters. */
export function withParams(route: string, params: Record<string, string>): string {
  const query = new URLSearchParams(params).toString();
  return query ? `${route}?${query}` : route;
}

/** Nudge effects to run after paint so a route change never blocks the frame. */
export function useScrollTopOnRouteChange(pathname: string): void {
  useEffect(() => { window.scrollTo({ top: 0 }); }, [pathname]);
}
