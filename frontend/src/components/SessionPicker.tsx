/** Year / event / session picker, backed by the manifest.
 *
 * Ported from `session_picker` in `app/common.py`. Selections are mirrored
 * into the URL so a particular view can be shared as a link, using the same
 * `year` / `round` / `session` parameters the Streamlit app wrote.
 */

import { useEffect, useMemo } from 'react';
import { RadioGroup, Select, Kicker, ErrorBox } from './ui/primitives';
import { useQueryParams } from '../lib/router';
import { useSessionLabel } from '../lib/theme';
import type { ManifestSession } from '../lib/types';

export interface Selection {
  slug: string;
  meta: ManifestSession;
}

interface SessionPickerProps {
  sessions: ManifestSession[];
  years: number[];
  /** The slug to fall back to when the URL says nothing.
   *
   * This is what keeps a page from opening on a session it cannot analyse:
   * the curated list leads with a qualifying session because Corner Analysis
   * is the best first impression, but Race Arc stops dead on anything but a
   * race — landing it there greets a first-time visitor with a "pick a Race
   * session" notice and an otherwise empty page. Each page asks for what it
   * can actually use. */
  openerSlug?: string | null;
  onChange: (selection: Selection | null) => void;
}

export function SessionPicker(
  { sessions, years, openerSlug, onChange }: SessionPickerProps,
) {
  const { params, update } = useQueryParams();
  const label = useSessionLabel();

  const opener = useMemo(
    () => sessions.find((s) => s.slug === openerSlug),
    [sessions, openerSlug],
  );

  // ---- resolve the three selections, URL first, opener second ------------

  const wantedYear = Number(params.get('year'));
  const year = years.includes(wantedYear)
    ? wantedYear
    : (opener && years.includes(opener.year) ? opener.year : years[0]);

  const inYear = useMemo(
    () => sessions.filter((s) => s.year === year).sort((a, b) => a.round - b.round),
    [sessions, year],
  );

  const events = useMemo(() => {
    const seen = new Map<number, string>();
    for (const session of inYear) {
      if (!seen.has(session.round)) seen.set(session.round, session.event_name);
    }
    return [...seen.entries()].map(([round, name]) => ({ round, name }));
  }, [inYear]);

  const rounds = events.map((event) => event.round);
  const wantedRound = Number(params.get('round'));
  const round = rounds.includes(wantedRound)
    ? wantedRound
    : (opener && opener.year === year && rounds.includes(opener.round)
        ? opener.round
        : rounds[0]);

  const available = useMemo(
    () => inYear.filter((s) => s.round === round).map((s) => s.session),
    [inYear, round],
  );

  const wantedSession = params.get('session') ?? '';
  const session = available.includes(wantedSession)
    ? wantedSession
    : (opener && opener.year === year && opener.round === round
        && available.includes(opener.session)
        ? opener.session
        : available[0]);

  const slug = `${year}/${String(round).padStart(2, '0')}_${session}`;
  const meta = sessions.find((s) => s.slug === slug);

  // ---- publish, both to the URL and to the page --------------------------

  useEffect(() => {
    if (!meta) return;
    update({ year: String(year), round: String(round), session });
    onChange({ slug, meta });
    // `update` and `onChange` are stable; the selection is what should
    // re-publish. Listing the callbacks here would re-run this on every
    // parent render and fight the URL back and forth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, meta, year, round, session]);

  if (sessions.length === 0) {
    return (
      <ErrorBox>
        <p>No sessions have been built yet. Run:</p>
        <pre>python scripts/build_dataset.py --years 2024 --sessions Q R</pre>
      </ErrorBox>
    );
  }

  if (!meta) {
    return (
      <ErrorBox>
        Session {slug} is in the picker but missing from the manifest.
      </ErrorBox>
    );
  }

  return (
    <>
      <Kicker>Session</Kicker>
      <Select
        label="Season" options={years} value={year}
        onChange={(next) => update({
          year: String(next),
          // The chosen round and session almost certainly do not exist in
          // another season, so clear them and let the fallbacks above pick.
          round: null, session: null,
        })}
      />
      <Select
        label="Event" options={rounds} value={round}
        format={(value) => {
          const event = events.find((e) => e.round === value);
          return `R${String(value).padStart(2, '0')}  ${event?.name ?? ''}`;
        }}
        onChange={(next) => update({ round: String(next), session: null })}
      />
      <RadioGroup
        label="Session" options={available} value={session}
        format={label}
        onChange={(next) => update({ session: next })}
      />
    </>
  );
}
