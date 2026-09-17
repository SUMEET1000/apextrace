/** The Streamlit widget vocabulary, rebuilt.
 *
 * One component per `st.*` call the three pages use, styled entirely by the
 * classes in `styles/global.css`. No component here may introduce a colour,
 * radius, duration or spacing value of its own — every one of those lives in
 * `styles/tokens.css`, which is itself a port of `pitwall/viz/theme.py`.
 */

import {
  Children, useEffect, useId, useRef, useState,
  type CSSProperties, type ReactNode,
} from 'react';

// --------------------------------------------------------------------------
// Layout
// --------------------------------------------------------------------------

/** `st.columns`. Ratios are the `[3, 2]`-style weights Streamlit accepts.
 *
 * `Children.toArray` rather than a plain filter, because a caller that mixes a
 * mapped list with a sibling — `{rows.map(...)}<Metric/>` — hands React two
 * children, one of which is an array. Filtering that gives two columns with
 * the whole mapped list stacked inside the first; flattening gives the N+1
 * Streamlit's `st.columns(len(rows) + 1)` asked for. It drops nulls and
 * `false` from short-circuited children on the way through.
 */
export function Columns(
  { children, ratios, gap = 'small' }:
  { children: ReactNode; ratios?: number[]; gap?: 'small' | 'medium' | 'large' },
) {
  const items = Children.toArray(children);
  return (
    <div className="pw-columns" data-gap={gap}>
      {items.map((child, i) => (
        <div className="pw-column" key={i} style={{ flex: ratios?.[i] ?? 1 }}>
          {child}
        </div>
      ))}
    </div>
  );
}

/** A top-level page section. The reveal hook observes these and nothing else. */
export function Section({ children, className = '' }:
{ children: ReactNode; className?: string }) {
  return <div className={`pw-reveal ${className}`.trim()}>{children}</div>;
}

/**
 * A group of elements inside a column, with Streamlit's 1rem stacking rhythm.
 *
 * Needed wherever a subheader / chart / caption trio sits inside a `Columns`
 * child: `.pw-column` spaces its own children, but a bare wrapper `div`
 * swallows that and `.pw-caption`'s deliberate -.35rem top margin then prints
 * over the chart above it.
 */
export function Stack({ children }: { children: ReactNode }) {
  return <div className="pw-stack">{children}</div>;
}

// --------------------------------------------------------------------------
// Branded rules and blocks
// --------------------------------------------------------------------------

export const Kerb = () => <div className="pw-kerb" />;
export const FlagStrip = () => <div className="pw-flag" />;

export function Kicker({ children, muted = false }:
{ children: ReactNode; muted?: boolean }) {
  return (
    <div className={muted ? 'pw-kicker pw-kicker--muted' : 'pw-kicker'}>
      {children}
    </div>
  );
}

export function Caption({ children }: { children: ReactNode }) {
  return <div className="pw-caption">{children}</div>;
}

export function SectionIntro({ children }: { children: ReactNode }) {
  return <div className="pw-section-intro">{children}</div>;
}

export function Verdict({ children }: { children: ReactNode }) {
  return <div className="pw-verdict">{children}</div>;
}

export function Subheader({ children }: { children: ReactNode }) {
  return <h3 className="pw-subheader">{children}</h3>;
}

// --------------------------------------------------------------------------
// Help tooltip — the `help=` argument on metrics, selects and sliders
// --------------------------------------------------------------------------

export function Help({ text }: { text: string }) {
  return (
    <span className="pw-help" tabIndex={0} role="note" aria-label={text}>
      ?<span>{text}</span>
    </span>
  );
}

// --------------------------------------------------------------------------
// Metric
// --------------------------------------------------------------------------

/**
 * `st.metric`.
 *
 * `deltaColor` mirrors Streamlit's argument. "off" is the common case here:
 * the delta slot is used as a caption ("1,006 laps · 20 drivers"), not as a
 * change indicator, so an arrow and a red/green would assert a direction the
 * value does not have. The arrow is suppressed in every mode for the same
 * reason. "inverse" is the one place colour is wanted — a negative lap-time
 * gap is a driver going faster.
 */
export function Metric(
  { label, value, delta, deltaColor = 'off', help }: {
    label: ReactNode;
    value: ReactNode;
    delta?: ReactNode;
    deltaColor?: 'off' | 'inverse';
    help?: string;
  },
) {
  let tone: string | undefined;
  if (deltaColor === 'inverse' && typeof delta === 'string') {
    const numeric = parseFloat(delta);
    if (Number.isFinite(numeric) && numeric !== 0) {
      tone = numeric < 0 ? 'inverse-good' : 'inverse-bad';
    }
  }
  return (
    <div className="pw-metric">
      <div className="pw-metric-label">
        {label}
        {help && <Help text={help} />}
      </div>
      <div className="pw-metric-value">{value}</div>
      {delta !== undefined && delta !== null && (
        <div className="pw-metric-delta" data-tone={tone}>{delta}</div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Alerts — st.info / st.warning / st.success / st.error
// --------------------------------------------------------------------------

const ALERT_ICONS: Record<string, ReactNode> = {
  info: <path d="M12 16v-4M12 8h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" />,
  success: <path d="m9 12 2 2 4-4M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" />,
  warning: <path d="M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />,
  error: <path d="M12 8v4M12 16h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" />,
};

export function Alert(
  { kind, children }: { kind: 'info' | 'success' | 'warning' | 'error'; children: ReactNode },
) {
  return (
    <div className="pw-alert" data-kind={kind} role={kind === 'error' ? 'alert' : 'status'}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {ALERT_ICONS[kind]}
      </svg>
      <div>{children}</div>
    </div>
  );
}

export const Info = ({ children }: { children: ReactNode }) =>
  <Alert kind="info">{children}</Alert>;
export const Warning = ({ children }: { children: ReactNode }) =>
  <Alert kind="warning">{children}</Alert>;
export const Success = ({ children }: { children: ReactNode }) =>
  <Alert kind="success">{children}</Alert>;
export const ErrorBox = ({ children }: { children: ReactNode }) =>
  <Alert kind="error">{children}</Alert>;

// --------------------------------------------------------------------------
// Inputs
// --------------------------------------------------------------------------

interface SelectProps<T> {
  label: string;
  options: T[];
  value: T;
  onChange: (value: T) => void;
  format?: (value: T) => string;
  disabled?: boolean;
  help?: string;
}

/**
 * `st.selectbox`.
 *
 * A disabled select still renders, with its reason in the tooltip. That is
 * load-bearing on Corner Analysis: `store.get_lap` silently falls back to a
 * driver's fastest stored lap, so hiding the control when only one lap exists
 * would leave the reader unable to tell which lap they were looking at. The
 * answer to "which lap?" must always be on screen.
 */
export function Select<T extends string | number>(
  { label, options, value, onChange, format, disabled, help }: SelectProps<T>,
) {
  const id = useId();
  const isNumeric = typeof options[0] === 'number';
  return (
    <div className="pw-widget pw-select">
      <label className="pw-widget-label" htmlFor={id}>
        {label}
        {help && <Help text={help} />}
      </label>
      <select
        id={id}
        value={String(value)}
        disabled={disabled}
        onChange={(e) => onChange((isNumeric ? Number(e.target.value) : e.target.value) as T)}
      >
        {options.map((option) => (
          <option key={String(option)} value={String(option)}>
            {format ? format(option) : String(option)}
          </option>
        ))}
      </select>
    </div>
  );
}

/** `st.radio`, horizontal by default — the session picker and the map view. */
export function RadioGroup<T extends string>(
  { label, options, value, onChange, format, horizontal = true }: {
    label: string;
    options: T[];
    value: T;
    onChange: (value: T) => void;
    format?: (value: T) => string;
    horizontal?: boolean;
  },
) {
  const name = useId();
  return (
    <div className="pw-widget" role="group" aria-label={label}>
      <span className="pw-widget-label">{label}</span>
      <div className={horizontal ? 'pw-radio' : 'pw-radio pw-radio--vertical'}>
        {options.map((option) => (
          <label key={option}>
            <input
              type="radio" name={name} value={option}
              checked={option === value}
              onChange={() => onChange(option)}
            />
            <span className="pw-radio-dot" />
            {format ? format(option) : option}
          </label>
        ))}
      </div>
    </div>
  );
}

/** `st.slider`. Streamlit shows the live value above and the bounds below. */
export function Slider(
  { label, min, max, step, value, onChange, format, help }: {
    label: string;
    min: number; max: number; step: number;
    value: number;
    onChange: (value: number) => void;
    format?: (value: number) => string;
    help?: string;
  },
) {
  const id = useId();
  const show = format ?? ((v: number) => String(v));
  const fill = `${((value - min) / (max - min)) * 100}%`;
  return (
    <div className="pw-widget pw-slider">
      <label className="pw-widget-label" htmlFor={id}>
        {label}
        {help && <Help text={help} />}
      </label>
      <div className="pw-slider-value">{show(value)}</div>
      <input
        id={id} type="range" min={min} max={max} step={step} value={value}
        style={{ '--pw-fill': fill } as CSSProperties}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="pw-slider-ticks"><span>{show(min)}</span><span>{show(max)}</span></div>
    </div>
  );
}

/** `st.multiselect`. Chips for what is chosen, a select to add the rest. */
export function MultiSelect(
  { label, options, value, onChange }: {
    label: string; options: string[]; value: string[];
    onChange: (value: string[]) => void;
  },
) {
  const remaining = options.filter((option) => !value.includes(option));
  return (
    <div className="pw-widget pw-multiselect">
      <span className="pw-widget-label">{label}</span>
      <div className="pw-multiselect-box">
        {value.map((item) => (
          <span className="pw-chip" key={item}>
            {item}
            <button
              type="button" aria-label={`Remove ${item}`}
              onClick={() => onChange(value.filter((v) => v !== item))}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="3" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </span>
        ))}
        <select
          value="" aria-label={`Add to ${label}`}
          disabled={remaining.length === 0}
          onChange={(e) => { if (e.target.value) onChange([...value, e.target.value]); }}
        >
          <option value="">{remaining.length ? 'Choose an option' : 'All selected'}</option>
          {remaining.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </div>
    </div>
  );
}

/** `st.toggle`. */
export function Toggle(
  { label, value, onChange }:
  { label: string; value: boolean; onChange: (value: boolean) => void },
) {
  return (
    <label className="pw-toggle">
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
      <span className="pw-toggle-track" />
      <span className="pw-toggle-label">{label}</span>
    </label>
  );
}

// --------------------------------------------------------------------------
// Tabs and expander
// --------------------------------------------------------------------------

export function Tabs(
  { tabs, active, onChange }:
  { tabs: string[]; active: string; onChange: (tab: string) => void },
) {
  return (
    <div className="pw-tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab} type="button" role="tab" className="pw-tab"
          aria-selected={tab === active}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

export function Expander(
  { label, children, defaultOpen = false }:
  { label: string; children: ReactNode; defaultOpen?: boolean },
) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="pw-expander" data-open={open}>
      <button
        type="button" className="pw-expander-summary"
        aria-expanded={open} onClick={() => setOpen((v) => !v)}
      >
        {label}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open && <div className="pw-expander-body">{children}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------
// Copy link
// --------------------------------------------------------------------------

/**
 * A button that puts the current deep link on the clipboard.
 *
 * Every selection on every page already round-trips through the query string,
 * so the address bar *is* the shareable state. This only removes the step of
 * noticing that. The URL is read at click time rather than captured on render,
 * so it is always the live one — including selections made after this button
 * was drawn.
 */
export function CopyLink({ label = 'Copy link to this view' }: { label?: string }) {
  const [text, setText] = useState(label);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = () => {
    window.clearTimeout(timer.current);
    navigator.clipboard.writeText(window.location.href).then(
      () => {
        setText('Link copied');
        timer.current = window.setTimeout(() => setText(label), 1600);
      },
      () => setText('Press Ctrl+L to copy the URL'),
    );
  };

  return (
    <button type="button" className="pw-copy" onClick={copy}>{text}</button>
  );
}
