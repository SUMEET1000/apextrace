/** Open Graph / Twitter card tags describing the view on screen.
 *
 * Ported from `meta_tags` in `app/brand.py`, which had to write these from a
 * `<script>` because Streamlit only ever gave the page a `<body>` to render
 * into. React owns the document, so this writes to `<head>` directly.
 *
 * Be honest about what it buys: an unfurler that fetches the URL and reads the
 * raw HTML — which is most of them — sees `index.html`, not this. What it does
 * reach is anything that renders the page first, plus the browser tab and
 * anyone who inspects the document. It is the most a client-rendered app can
 * do without a server-side prerender in front of it.
 */

import { useEffect } from 'react';

function setMeta(key: string, content: string): void {
  const attribute = key.startsWith('og:') ? 'property' : 'name';
  let element = document.head.querySelector<HTMLMetaElement>(
    `meta[${attribute}="${key}"]`);
  if (!element) {
    element = document.createElement('meta');
    element.setAttribute(attribute, key);
    document.head.appendChild(element);
  }
  element.setAttribute('content', content);
}

export function useMetaTags(title: string, description: string): void {
  useEffect(() => {
    document.title = title;
    setMeta('og:title', title);
    setMeta('og:description', description);
    setMeta('og:type', 'website');
    setMeta('twitter:card', 'summary');
    setMeta('twitter:title', title);
    setMeta('twitter:description', description);
    setMeta('description', description);
  }, [title, description]);
}
