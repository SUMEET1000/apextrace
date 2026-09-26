/** An F1 term's one-line explanation, printed in the page's sentence voice.
 *
 * The text comes from lib/glossary.json, the same file scripts/ui/gate.py reads,
 * so the page and the gate cannot disagree (Phase 2B D9). `data-term-def` is
 * what the gate looks for.
 */

import glossary from '../lib/glossary.json';

const TEXT: Record<string, string> = Object.fromEntries(glossary.map((e) => [e.id, e.text]));

export function Term({ id }: { id: string }) {
  return <span data-term-def={id}>{TEXT[id]}</span>;
}
