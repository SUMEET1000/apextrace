/** The compact branded header every analysis page opens with.
 *
 * Ported from `session_header` in `app/common.py`. Carries the circuit outline
 * as artwork so each page is visually anchored to the session being analysed,
 * and the share affordance for the deep link the page is already maintaining
 * in the URL.
 */

import { CopyLink } from '../ui/primitives';
import { CircuitSvg } from './CircuitArt';
import { useMetaTags } from '../../hooks/useMetaTags';
import type { ManifestSession, Outline } from '../../lib/types';

export function SessionHeader(
  { meta, sessionLabel, pageTitle, track, showCorners = false }: {
    meta: ManifestSession;
    sessionLabel: string;
    pageTitle: string;
    track?: Outline;
    showCorners?: boolean;
  },
) {
  useMetaTags(
    `${pageTitle} · ${meta.event_name} ${meta.year} ${sessionLabel}`,
    `ApexTrace: ${pageTitle.toLowerCase()} for the ${meta.year} ` +
    `${meta.event_name} ${sessionLabel.toLowerCase()} at ${meta.location}, ` +
    `${meta.country}.`,
  );

  return (
    <>
      <div className="pw-hero pw-hero--page">
        <div className="pw-hero-text">
          <div className="pw-kicker">
            {meta.event_name} · {meta.year} · {sessionLabel}
          </div>
          <h1>{pageTitle}</h1>
          <div className="pw-hero-sub">{meta.location}, {meta.country}</div>
        </div>
        <div className="pw-hero-art">
          <CircuitSvg track={track} width={showCorners ? 320 : 190}
            height={showCorners ? 220 : 120} showCorners={showCorners} />
        </div>
      </div>
      <CopyLink />
    </>
  );
}
