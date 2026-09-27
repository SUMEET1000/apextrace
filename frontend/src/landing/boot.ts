// @ts-nocheck - ported, not rewritten (Phase 2B D6): the imperative code of
// landings/08-finished.html with common.js, sheet.js and halftone.js, in 08's
// order. What changed: numbers and positions come from facts.json, gsap, lenis
// come from npm, links are relative app routes, and every listener, loop,
// observer and DOM change is undone by the returned cleanup, so a route change
// leaves nothing running.
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';
import { lifting } from './loader';

gsap.registerPlugin(ScrollTrigger);

const NS = 'http://www.w3.org/2000/svg';
export const el = (n, a = {}) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };

export function boot(root, F) {
  const D = document, undo = [];
  let alive = true;
  const on = (t, type, fn, o) => { t.addEventListener(type, fn, o); undo.push(() => t.removeEventListener(type, fn, o)); };
  const later = (fn, ms) => { const id = setTimeout(fn, ms); undo.push(() => clearTimeout(id)); };
  // Restores a node's children on cleanup, for the spots this code rewrites.
  const keep = n => { const html = n.innerHTML; undo.push(() => { n.innerHTML = html; }); };
  const off = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Silverstone centreline and corners (facts.json track, equal to 08's track.js).
  const TRACK = F.track;
  // DELTA = t_VER - t_RUS per corner: positive means Russell was faster there. HOT are the
  // three corners where Verstappen won the most time back.
  const DELTA = Object.fromEntries(F.corners.map(c => [c.n, c.delta_s]));
  const HOT = Object.fromEntries(F.faster.b_top.map(n => [n, -DELTA[n]]));
  const ACC = () => getComputedStyle(D.documentElement).getPropertyValue('--acc').trim();
  const TW = { trackW: 9, ghostR: 14, terrain: 0, glow: true, boxes: true, circle: true, ghostOn: true, lapMs: 10000 };

  // common.js: the track path and a two-dot ghost lap. The leader is ahead by the real gap as
  // a share of the lap, exaggerated 10x so the eye can see it.
  function drawTrack(svg, o = {}) {
    svg.setAttribute('viewBox', `0 0 ${TRACK.w} ${TRACK.h}`);
    const p = el('path', { d: TRACK.d, fill: 'none', stroke: o.stroke || 'currentColor', 'stroke-width': o.width || 6, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', class: 'trk' });
    svg.append(p);
    if (o.draw) { const L = p.getTotalLength(); p.style.strokeDasharray = L; p.style.strokeDashoffset = L; p.animate([{ strokeDashoffset: L }, { strokeDashoffset: 0 }], { duration: o.draw, easing: 'cubic-bezier(.6,0,.2,1)', fill: 'forwards' }); }
    (o.corners || []).forEach(n => { const c = TRACK.corners[n - 1]; if (o.cornerFn) o.cornerFn(svg, c); });
    if (o.ghost) ghost(svg, p, o.ghost);
    return p;
  }
  function ghost(svg, path, g) {
    const L = path.getTotalLength();
    const a = el('circle', { r: g.r || 12, fill: g.a }), b = el('circle', { r: g.r || 12, fill: g.b });
    svg.append(b, a);
    const lap = g.lap || TW.lapMs, gap = (F.lap.gap_s * 10 / F.lap.a.time_s) * L;
    // Stops once a redraw or the cleanup has removed the dots, so loops never stack.
    const tick = t => {
      if (!alive || !a.isConnected) return;
      const s = ((t % lap) / lap) * L;
      const pa = path.getPointAtLength(s), pb = path.getPointAtLength((s - gap + L) % L);
      a.setAttribute('cx', pa.x); a.setAttribute('cy', pa.y); b.setAttribute('cx', pb.x); b.setAttribute('cy', pb.y);
      requestAnimationFrame(tick);
    };
    if (!off) requestAnimationFrame(tick);
  }

  // sheet.js: the hero circuit - square-pixel glow, numbered corner boxes, ghost lap.
  function sheetTrack(svg, o = {}) {
    const W = TW, T = TRACK, ink = '#131313';
    svg.innerHTML = `<defs><pattern id="dt" width="9" height="9" patternUnits="userSpaceOnUse"><circle cx="4.5" cy="4.5" r="2.4" fill="${ink}"/></pattern></defs>
<circle cx="${T.w / 2}" cy="${T.h / 2}" r="${T.h * .6}" fill="none" stroke="${ink}" stroke-width="1.2"/><circle cx="${T.w / 2}" cy="${T.h / 2}" r="8" fill="${ink}"/>`;
    let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    F.faster.b_top.map((n, i) => [n, [86, 66, 60][i]]).forEach(([n, R]) => {
      const c = T.corners[n - 1], g = el('g');
      for (let i = 0; i < 200; i++) { const a = rnd() * 6.3, d = Math.pow(rnd(), .7) * R, s = 8 + rnd() * 10; g.append(el('rect', { x: c.x + Math.cos(a) * d - s / 2, y: c.y + Math.sin(a) * d - s / 2, width: s, height: s, style: `fill:${d < R * .33 ? ink : 'var(--acc)'}` })); }
      svg.append(g);
    });
    drawTrack(svg, { stroke: ink, width: W.trackW, draw: o.draw ?? 3000, ghost: { a: ink, b: '#fff', r: W.ghostR }, corners: [...Array(T.corners.length)].map((_, i) => i + 1), cornerFn: (s, c) => {
      const g = el('g'); g.append(el('rect', { x: c.x + 16, y: c.y - 46, width: 38, height: 34, fill: '#fff', stroke: ink, 'stroke-width': 3 }));
      const t = el('text', { x: c.x + 35, y: c.y - 21, 'text-anchor': 'middle', 'font-family': 'Archivo Black', 'font-size': 20, fill: ink }); t.textContent = c.n; g.append(t);
      if (HOT[c.n]) { const l = el('text', { x: c.x + 62, y: c.y - 22, 'font-family': 'IBM Plex Mono', 'font-weight': 700, 'font-size': 16, fill: ink }); l.textContent = c.name.toUpperCase() + ' · VER −' + HOT[c.n].toFixed(3); g.append(l); }
      s.append(g);
    } });
    svg.querySelectorAll(`circle[r="${W.ghostR}"]`).forEach(c => { c.setAttribute('stroke', ink); c.setAttribute('stroke-width', 3); });
  }

  function cornerGrid(node) {
    node.classList.add('index');
    node.innerHTML = TRACK.corners.map(c => { const d = DELTA[c.n], who = d > 0 ? 'RUS' : d < 0 ? 'VER' : 'EVEN';
      return `<div class="${d > 0 ? 'hot' : ''}" data-reveal><b>${String(c.n).padStart(2, '0')}</b><span class="lab">${c.name}</span><em>${who} ${Math.abs(d).toFixed(3)}</em></div>`; }).join('');
  }

  // halftone.js: a screenprint halftone of an image, one dot per cell, dot area by darkness.
  function halftone(canvas, O) {
    const img = new Image(); img.src = canvas.dataset.src;
    const draw = () => {
      const cell = O.cell, ink = O.ink;
      const W = canvas.clientWidth, H = canvas.clientHeight, r = devicePixelRatio || 1;
      if (!alive || !W || !H || !img.complete || !img.naturalWidth) return;
      canvas.width = W * r; canvas.height = H * r;
      const cols = Math.ceil(W / cell) + 1, rows = Math.ceil(H / cell) + 1;
      const offc = D.createElement('canvas'); offc.width = cols; offc.height = rows;
      const x = offc.getContext('2d', { willReadFrequently: true });
      const s = Math.max(cols / img.width, rows / img.height) * (O.zoom || 1);
      const px = (O.x ?? 50) / 100, py = (O.y ?? 50) / 100;
      x.drawImage(img, (cols - img.width * s) * px, (rows - img.height * s) * py, img.width * s, img.height * s);
      const d = x.getImageData(0, 0, cols, rows).data, c = canvas.getContext('2d');
      c.setTransform(r, 0, 0, r, 0, 0); c.clearRect(0, 0, W, H); c.fillStyle = ink;
      for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
        const k = (j * cols + i) * 4, lum = (d[k] * .3 + d[k + 1] * .59 + d[k + 2] * .11) / 255;
        const dark = Math.min(1, Math.max(0, ((1 - lum) - .08) * 1.35));
        const rad = cell * .56 * Math.sqrt(dark);
        if (rad < .5) continue;
        c.beginPath(); c.arc(i * cell + (j % 2 ? cell / 2 : 0), j * cell, rad, 0, 7); c.fill();
      }
    };
    // Watch the canvas box itself: fonts, hero height or layout can resize it without a window resize.
    img.onload = draw; const ro = new ResizeObserver(draw); ro.observe(canvas); undo.push(() => { img.onload = null; ro.disconnect(); });
  }

  const ctx = gsap.context(() => {}, root);
  let lenis = null;

  // ---- boot (08's first script) ----
  (() => {
    const DIST = 120, DUR = 1.45, STAG = .12;
    const FROM = { rise: d => ({ y: d, opacity: 0 }), fade: () => ({ opacity: 0 }), slide: d => ({ x: -d, opacity: 0 }), scale: () => ({ scale: .9, opacity: 0 }) };
    const WORD = { rise: { yPercent: 110 }, fade: { opacity: 0 }, slide: { xPercent: -110 }, scale: { yPercent: 60, scale: .6, opacity: 0 } };
    // Each section enters its own way, in page order.
    const ENT = { grid: 'rise', questions: 'fade', method: 'slide', proof: 'scale', author: 'rise' };
    const ent = e => ENT[e.closest('section').id] || 'rise';

    const trk = D.getElementById('trk'); keep(trk);
    sheetTrack(trk, { draw: off ? 0 : 3000 });
    const grid = root.querySelector('[data-corner-grid]'); keep(grid); cornerGrid(grid);

    // Corner labels. Each label takes the spot, one ring out from its corner, farthest from the
    // track and from labels already placed, and a short leader line runs back to the exact corner.
    const P = TRACK.d.match(/-?[\d.]+/g).map(Number), PTS = [];
    for (let i = 0; i < P.length; i += 2) PTS.push([P[i], P[i + 1]]);
    const SPOT = (() => {
      const T = TRACK, out = [];
      T.corners.forEach(c => {
        let best = null;
        for (const R of [46, 58, 72]) {
          for (let k = 0; k < 24; k++) {
            const a = k / 24 * Math.PI * 2, x = c.x + R * Math.cos(a), y = c.y + R * Math.sin(a);
            if (x < 24 || x > T.w - 24 || y < 22 || y > T.h - 22) continue;
            const clr = Math.min(...PTS.map(([px, py]) => Math.hypot(px - x, py - y)), ...out.map(o => Math.hypot(o.x - x, o.y - y) - 16));
            if (!best || clr > best.clr) best = { x, y, clr };
          }
          if (best && best.clr >= 32) break;
        }
        out.push(best);
      });
      return out;
    })();
    [...trk.querySelectorAll('g')].filter(g => g.querySelector('rect[width="38"]')).forEach((g, i) => {
      const c = TRACK.corners[i], p = SPOT[i], [n, l] = g.querySelectorAll('text'), r = g.querySelector('rect');
      r.setAttribute('x', p.x - 19); r.setAttribute('y', p.y - 17); n.setAttribute('x', p.x); n.setAttribute('y', p.y + 7);
      // The name text tries the four sides of its box, on one line or two, and takes the spot
      // farthest from the track, from the dark core of each glow and from the other boxes.
      if (l) {
        const [nm, dt] = l.textContent.split(' · VER '), CW = 9.8, cores = F.faster.b_top.map(k => TRACK.corners[k - 1]), best = { clr: -1e9 };
        for (const two of [false, true]) {
          const rows = two ? [nm, 'VER ' + dt] : [l.textContent], w = Math.max(...rows.map(t => t.length)) * CW, hh = rows.length * 18;
          for (const [x0, y0] of [[p.x + 27, p.y - hh / 2], [p.x - 27 - w, p.y - hh / 2], [p.x - 19, p.y + 24], [p.x - 19, p.y - 24 - hh]]) {
            const S = []; for (let fx = 0; fx <= 1; fx += .125) for (let fy = 0; fy <= 1; fy += .5) S.push([x0 + fx * w, y0 + fy * hh]);
            if (x0 < 0 || x0 + w > TRACK.w || y0 < 0 || y0 + hh > TRACK.h) continue;
            const clr = Math.min(...S.flatMap(([x, y]) => [...PTS.map(([a, b]) => Math.hypot(a - x, b - y) - 8), ...cores.map(k => Math.hypot(k.x - x, k.y - y) - 30), ...SPOT.filter(q => q !== p).map(q => Math.max(Math.abs(q.x - x) - 19, Math.abs(q.y - y) - 17))]));
            if (clr > best.clr) Object.assign(best, { clr, x0, y0, rows });
          }
        }
        l.textContent = ''; l.setAttribute('x', best.x0); l.removeAttribute('y');
        best.rows.forEach((t, k) => { const s = el('tspan', { x: best.x0, y: best.y0 + 13 + k * 18 }); s.textContent = t; l.append(s); });
      }
      g.prepend(el('line', { x1: c.x, y1: c.y, x2: p.x, y2: p.y, stroke: '#131313', 'stroke-width': 2 }), el('circle', { cx: c.x, cy: c.y, r: 4, fill: '#131313' }));
    });
    halftone(root.querySelector('.hero .photo canvas'), { cell: 6, zoom: 1.15, x: 60, y: 50, ink: '#131313' });

    // The hero word must never overflow its band.
    const h1 = root.querySelector('.panel h1');
    function fit() {
      h1.style.removeProperty('font-size');
      const cs = getComputedStyle(h1), pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
      const avail = h1.clientWidth - pad, need = h1.scrollWidth - pad;
      if (need > avail + 1) h1.style.setProperty('font-size', parseFloat(cs.fontSize) * avail / need * .985 + 'px', 'important');
    }
    fit(); D.fonts.ready.then(() => { if (!alive) return; fit(); ScrollTrigger.refresh(); }); on(window, 'resize', fit);

    // End-of-sheet print: a halftone pass set 6 u off register from the ink pass.
    const svg = root.querySelector('#sig svg'), T = TRACK; keep(svg);
    svg.setAttribute('viewBox', `-40 -40 ${T.w + 80} ${T.h + 80}`);
    svg.innerHTML = '<defs><pattern id="sgd" width="8.8" height="8.8" patternUnits="userSpaceOnUse"><circle cx="4.4" cy="4.4" r="2.992" style="fill:var(--acc)"/></pattern></defs>';
    const half = el('path', { d: T.d, fill: 'none', stroke: 'url(#sgd)', 'stroke-width': 27.2, 'stroke-linejoin': 'round', transform: 'translate(6 6)' });
    const ink = el('path', { d: T.d, fill: 'none', stroke: '#131313', 'stroke-width': 8, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' });
    svg.append(half, ink);
    const nums = T.corners.map((c, i) => { const p = SPOT[i], g = el('g'), t = el('text', { x: p.x, y: p.y + 8, 'text-anchor': 'middle', 'font-size': 22, fill: '#131313', style: 'font-family:var(--fd)' });
      t.textContent = c.n; g.append(el('line', { x1: c.x, y1: c.y, x2: p.x + (c.x - p.x) * 14 / Math.hypot(c.x - p.x, c.y - p.y), y2: p.y + (c.y - p.y) * 14 / Math.hypot(c.x - p.x, c.y - p.y), stroke: '#131313', 'stroke-width': 2 }), t); svg.append(g); return g; });
    if (!off) ghost(svg, ink, { a: '#131313', b: '#F2E600', r: 12, lap: 15000 });

    // Gap counter: pinned and scroll-driven at >= 860 px whatever the motion setting.
    const li = [...root.querySelectorAll('#parts li')], sum = D.getElementById('sum');
    const show = k => { let s = 0; li.forEach((l, i) => { l.classList.toggle('on', i < k); l.classList.toggle('now', i === k - 1); if (i < k) s += +l.dataset.v; }); sum.textContent = s.toFixed(3); };
    let gap = null, acc = 0;
    const mm = gsap.matchMedia(); undo.push(() => mm.revert());
    mm.add({ desk: '(min-width: 860px)', mob: '(max-width: 859.98px)' }, c => {
      if (c.conditions.mob) { show(li.length); return; }
      gap = ScrollTrigger.create({ trigger: '#count', start: 'top top', end: '+=200%', pin: true, scrub: true,
        onUpdate: st => show(Math.min(li.length, Math.floor(st.progress * (li.length + .999)))) });
      return () => { gap = null; };
    });
    // One wheel notch = one row inside the pin. Each notch (one event of 50 px or more, or small
    // deltas adding up to 100 px) steps to the middle of the next row's band; at the first and last
    // row the wheel passes through, so the page scrolls on out of the pin. A ScrollTrigger snap
    // fought Lenis and skipped rows at 800 px tall. Capture phase on window runs before Lenis's own
    // wheel listener.
    on(window, 'wheel', e => {
      if (!gap || e.ctrlKey || !e.deltaY) return;
      const n = li.length + .999, len = gap.end - gap.start, y = lenis ? lenis.targetScroll : scrollY;
      if (y < gap.start - 1 || y > gap.end + 1) return;
      const k = Math.min(li.length, Math.max(0, Math.floor((y - gap.start) / len * n + 1e-6)));
      const next = k + Math.sign(e.deltaY);
      if (next < 0 || next > li.length) return;
      e.preventDefault(); e.stopImmediatePropagation();
      const dy = e.deltaMode ? e.deltaY * 40 : e.deltaY;   // Firefox can report lines (3 per notch), not px
      if (Math.sign(acc) !== Math.sign(dy)) acc = 0;
      if (Math.abs(dy) < 50 && Math.abs(acc += dy) < 100) return;   // small deltas (smooth mouse, trackpad) add up to one 100 px notch
      acc = 0;
      const to = gap.start + len * (next === li.length ? 1 : next && (next + .5) / n);
      lenis ? lenis.scrollTo(to, { lerp: .09 }) : scrollTo(0, to);   // same glide as free scroll; a duration eases expo-out and read as a jump
    }, { capture: true, passive: false });

    if (off) return;

    lenis = new Lenis({ lerp: .09 }); lenis.on('scroll', ScrollTrigger.update);
    const raf = t => lenis.raf(t * 1000);
    gsap.ticker.add(raf); gsap.ticker.lagSmoothing(0);
    undo.push(() => { gsap.ticker.remove(raf); gsap.ticker.lagSmoothing(500, 33); lenis.destroy(); lenis = null; });
    // In-page links glide through Lenis instead of jumping; the offset keeps the section clear of
    // the 56 px fixed header.
    D.querySelectorAll('a[href^="#"]').forEach(a => on(a, 'click', e => {
      const id = a.getAttribute('href').slice(1), t = id ? D.getElementById(id) : 0;
      if (t === null || !lenis) return;
      e.preventDefault(); lenis.scrollTo(t, { offset: t ? -56 : 0, duration: 1.4 });
    }));

    ctx.add(() => {
      // Opening: the hero enters while the loader is half lifted. A 0.7 s expo.out read as instant;
      // 1 s power3.out still reads as a rise.
      const hero = gsap.timeline({ paused: true }).from(['.hero .photo', '.panel', '.stage', ...root.querySelectorAll('.hero .ann')].map(s => typeof s === 'string' ? root.querySelector(s) : s),
        { ...FROM.rise(DIST), duration: 1, ease: 'power3.out', stagger: .1 });
      lifting.then(at => { if (alive) later(() => hero.play(), Math.max(0, at + 450 - performance.now())); });

      // Reveals.
      root.querySelectorAll('[data-split]').forEach(h => {
        keep(h);
        h.innerHTML = h.innerHTML.split(' ').filter(Boolean).map(w => `<span class="w"><span>${w}</span></span>`).join(' ');
        gsap.from(h.querySelectorAll('.w>span'), { ...WORD[ent(h)], duration: DUR, ease: 'expo.out', stagger: STAG, scrollTrigger: { trigger: h, start: 'top 85%' } });
      });
      const els = [...root.querySelectorAll('[data-reveal]')].filter(e => e.getBoundingClientRect().top >= innerHeight * .88);
      els.forEach(e => gsap.set(e, FROM[ent(e)](DIST)));
      ScrollTrigger.batch(els, { start: 'top 88%', once: true, onEnter: b => gsap.to(b, { x: 0, y: 0, scale: 1, opacity: 1, duration: DUR, ease: 'expo.out', stagger: STAG, overwrite: true }) });

      // Question cards: all stick at one top, and each fades out while the next one rises to
      // cover it, so no edge of an earlier card stays visible behind the stack.
      const cards = [...root.querySelectorAll('.sc')];
      cards.slice(0, -1).forEach((c, i) => gsap.to(c, { opacity: 0, scale: .96, ease: 'none',
        scrollTrigger: { trigger: cards[i + 1], start: 'top 75%', end: 'top 80px', scrub: true } }));

      // Footer draw-in: both passes draw, then the corner numbers and ghost dots come in. It
      // triggers on the circuit, not the section, which fired with the circuit below the fold.
      const L = ink.getTotalLength(), dots = [...svg.querySelectorAll(':scope > circle')];
      [ink, half].forEach(p => p.style.strokeDasharray = L);
      gsap.timeline({ scrollTrigger: { trigger: '#sig .sig-stage', start: 'top 80%', once: true } })
        .fromTo(ink, { strokeDashoffset: L }, { strokeDashoffset: 0, duration: 1.3, ease: 'power2.inOut', immediateRender: true }, 0)
        .fromTo(half, { strokeDashoffset: L }, { strokeDashoffset: 0, duration: 1.3, ease: 'power2.inOut', immediateRender: true }, .15)
        .from(nums, { opacity: 0, duration: .2, stagger: .05, immediateRender: true }, .15)
        .from(dots, { opacity: 0, duration: .4, immediateRender: true }, 1.4);
    });
    later(() => ScrollTrigger.refresh(), 180);
  })();

  // ---- the counter's digits roll like an odometer; #sum stays the source of truth ----
  (() => {
    const sum = D.getElementById('sum'), roll = D.createElement('span');
    roll.className = 'roll'; roll.setAttribute('aria-hidden', 'true'); sum.after(roll); sum.classList.add('sr');
    let key = '', cols = [];
    function render() {
      const s = sum.textContent, k = s.replace(/\d/g, 'd');
      if (k !== key) {
        key = k; roll.textContent = '';
        cols = [...s].map(ch => { const c = D.createElement('span'); c.className = 'c';
          if (/\d/.test(ch)) c.innerHTML = '<span class="s">' + [...'0123456789'].map(d => '<b>' + d + '</b>').join('') + '</span>'; else c.textContent = ch;
          roll.append(c); return c; });
      }
      [...s].forEach((ch, i) => { if (/\d/.test(ch)) cols[i].firstElementChild.style.transform = 'translateY(' + -ch + 'em)'; });
    }
    const mo = new MutationObserver(render); mo.observe(sum, { childList: true, characterData: true, subtree: true });
    render();
    undo.push(() => { mo.disconnect(); roll.remove(); sum.classList.remove('sr'); });
  })();

  // ---- magnetic buttons: pull toward the pointer, spring back on leave ----
  if (!off && matchMedia('(hover: hover)').matches) {
    root.querySelectorAll('.btn, .credits nav a').forEach(b => {
      on(b, 'pointermove', e => { const r = b.getBoundingClientRect(); b.style.translate = (e.clientX - r.left - r.width / 2) * .2 + 'px ' + (e.clientY - r.top - r.height / 2) * .35 + 'px'; });
      on(b, 'pointerleave', () => { b.style.translate = '0 0'; });
    });
  }

  // ---- scroll progress: a lap bar under the header with a tick per section ----
  (() => {
    const bar = D.createElement('div'); bar.className = 'prog'; bar.setAttribute('aria-hidden', 'true');
    bar.innerHTML = '<i></i>'; root.append(bar); const fill = bar.firstChild; undo.push(() => bar.remove());
    const S = [['count', 'ANSWER'], ['questions', 'QUESTIONS'], ['method', 'METHOD'], ['proof', 'DATA'], ['author', 'AUTHOR']];
    // Ticks come from the live layout, so the pinned counter's spacer is counted; they are placed
    // again later and on resize because ScrollTrigger adds that spacer late.
    function place() {
      bar.style.top = D.querySelector('header').getBoundingClientRect().bottom + 'px';
      bar.querySelectorAll('u').forEach(u => u.remove());
      const max = D.documentElement.scrollHeight - innerHeight;
      S.forEach(([id, name]) => { const e = D.getElementById(id); if (!e) return; const u = D.createElement('u'); u.style.left = (e.getBoundingClientRect().top + scrollY) / max * 100 + '%'; u.innerHTML = '<b>' + name + '</b>'; bar.append(u); });
      tick();
    }
    function tick() { const max = D.documentElement.scrollHeight - innerHeight; fill.style.width = Math.min(100, scrollY / max * 100) + '%'; }
    on(window, 'scroll', tick, { passive: true }); on(window, 'resize', place);
    later(place, 300); later(place, 3500); place();
  })();

  // ---- specification numbers roll up from 0, forward only ----
  if (!off) (() => {
    const line = root.querySelector('.spec'), bs = [...line.querySelectorAll('.sp b')];
    bs.forEach(b => {
      keep(b);
      const n = b.textContent.trim(), L = n.length;
      b.innerHTML = '<span class="sr">' + n + '</span><span class="roll" aria-hidden="true">' + [...n].map((d, i) =>
        '<span class="c"><span class="s" data-to="' + (Math.max(0, 2 - (L - 1 - i)) * 10 + +d) + '">' + [...'012345678901234567890123456789'].map(q => '<i>' + q + '</i>').join('') + '</span></span>').join('') + '</span>';
    });
    // Scrubbed by the scroll: the numbers reach their value as the line reaches the upper third,
    // each block a little behind the one before. Scrolling back up leaves the final values.
    const cols = bs.map(b => [...b.querySelectorAll('.s')]), st = { p: 0 };
    const set = () => cols.forEach((cs, k) => { const q = Math.min(1, Math.max(0, st.p * 1.3 - k * .1)), e = 1 - Math.pow(1 - q, 3);
      cs.forEach(c => { c.style.transform = 'translateY(' + -c.dataset.to * e + 'em)'; }); });
    let top = 0;
    ctx.add(() => ScrollTrigger.create({ trigger: line, start: 'top 92%', end: 'top 35%', onUpdate: s => {
      if (s.progress <= top) return; top = s.progress; gsap.to(st, { p: top, duration: .4, ease: 'none', overwrite: true, onUpdate: set }); } }));
    undo.push(() => gsap.killTweensOf(st));
  })();

  // ---- corner grid: Verstappen's corners in solid ink ----
  root.querySelectorAll('.index > div').forEach(d => { if (/^VER/.test(d.querySelector('em').textContent)) d.classList.add('ver'); });

  // ---- Ask the data: a small chart per question card, drawn only from numbers the card states ----
  (() => {
    const T = (x, y, s, a = 'start', c = '') => `<text x="${x}" y="${y}" text-anchor="${a}" class="${c}">${s}</text>`;
    const soft = F.tyres.SOFT, hard = F.tyres.HARD, pit = F.pit_loss, f3 = v => v.toFixed(3), f1 = v => v.toFixed(1);
    const C = {
      corners() {
        const st = 380 / 18, bw = 13, max = .2; let g = '<line x1="0" y1="90" x2="400" y2="90" class="ax"/>';
        TRACK.corners.forEach((c, i) => { const d = DELTA[c.n], h = Math.max(1.5, Math.abs(d) / max * 70), x = 10 + i * st + (st - bw) / 2;
          g += `<rect x="${x}" y="${d >= 0 ? 90 - h : 90}" width="${bw}" height="${h}" class="${d > 0 ? 'ru' : d < 0 ? 've' : 'ev'}" data-t="T${c.n} ${c.name.toUpperCase()} · ${d > 0 ? 'RUS' : d < 0 ? 'VER' : 'EVEN'} ${f3(Math.abs(d))} S"/>`; });
        return [`<svg viewBox="0 0 400 180">${g}${T(0, 10, 'RUSSELL FASTER ↑')}${T(0, 180, 'VERSTAPPEN FASTER ↓')}</svg>`, 'HOVER A BAR · SECONDS GAINED IN EACH CORNER',
          `Russell was faster in ${F.faster.a} of ${TRACK.corners.length} corners, Verstappen in ${F.faster.b}.`];
      },
      tyres() {
        const X = l => 40 + l / 25 * 340, Y = v => 160 - v / 3.4 * 140;
        const g = `<polygon points="${X(0)},${Y(0)} ${X(25)},${Y(soft.ci_high * 25)} ${X(25)},${Y(soft.ci_low * 25)}" class="band" data-t="SOFT · 95% CI ${f3(soft.ci_low)}–${f3(soft.ci_high)} S/LAP"/>`
          + `<line x1="${X(0)}" y1="${Y(0)}" x2="${X(25)}" y2="${Y(soft.s_per_lap * 25)}" class="soft" data-t="SOFT · +${f3(soft.s_per_lap)} S PER LAP, ${soft.stints} STINTS"/><line x1="${X(0)}" y1="${Y(0)}" x2="${X(25)}" y2="${Y(hard.s_per_lap * 25)}" class="hard" data-t="HARD · +${f3(hard.s_per_lap)} S PER LAP, ${hard.stints} STINTS"/>`
          + `<line x1="40" y1="160" x2="385" y2="160" class="ax"/><line x1="40" y1="12" x2="40" y2="160" class="ax"/>`
          + T(X(25), Y(soft.ci_high * 25) - 8, 'SOFT +' + f3(soft.s_per_lap), 'end', 'b') + T(X(25), Y(hard.s_per_lap * 25) + 58, 'HARD +' + f3(hard.s_per_lap), 'end') + T(40, 178, 'LAP 0') + T(385, 178, '25 LAPS INTO A STINT', 'end') + T(46, 20, 'SECONDS LOST');
        return [`<svg viewBox="0 0 400 180">${g}</svg>`, `BAHRAIN ${F.source.year} · YELLOW BAND = SOFT TYRE 95% CONFIDENCE INTERVAL`,
          `The soft tyre lost ${f3(soft.s_per_lap)} s a lap as it wore, the hard ${f3(hard.s_per_lap)} s.`];
      },
      track() {
        const P = f => { let d = ''; for (let i = 0; i <= 40; i++) { const x = 40 + i / 40 * 340; d += (i ? 'L' : 'M') + x.toFixed(1) + ',' + f(i / 40).toFixed(1); } return d; };
        const L = [['TRACK · GRIPS UP, LAPS GET FASTER', 'ln y', P(u => 60 + 50 * (1 - Math.exp(-3 * u)))], ['TYRE · WEARS, RESETS AT EACH STOP', 'ln', P(u => 150 - 60 * ((u * 3) % 1))], ['FUEL · BURNS OFF, CAR GETS LIGHTER', 'ln d', P(u => 30 + 90 * u)]];
        const g = L.map(([t, c, d]) => `<g data-t="${t}"><path d="${d}" class="hit"/><path d="${d}" class="${c}"/></g>`).join('');
        return [`<svg viewBox="0 0 400 180"><line x1="40" y1="165" x2="385" y2="165" class="ax"/>${g}${T(40, 180, 'LAP 1')}${T(385, 180, 'RACE', 'end')}</svg>`, 'SHAPE ONLY, NOT TO SCALE · HOVER A LINE',
          `${L.length} effects change every lap time at once.`];
      },
      undercut() {
        const X = v => 20 + v / pit.total_s * 360;
        const g = `<rect x="${X(0)}" y="60" width="${X(pit.in_s) - X(0)}" height="44" class="in" data-t="IN-LAP · ${f1(pit.in_s)} S LOST"/><rect x="${X(pit.in_s)}" y="60" width="${X(pit.total_s) - X(pit.in_s)}" height="44" class="out" data-t="OUT-LAP · ${f1(pit.out_s)} S LOST, PIT LANE INCLUDED"/>`
          + T(X(0), 50, 'IN-LAP ' + f1(pit.in_s), 'start', 'b') + T((X(pit.in_s) + X(pit.total_s)) / 2, 50, 'OUT-LAP ' + f1(pit.out_s), 'middle', 'b')
          + `<path d="M${X(0)},116 v8 H${X(pit.total_s)} v-8" fill="none" class="ax"/>` + T(X(pit.total_s / 2), 144, `= ${f1(pit.total_s)} S PIT LOSS`, 'middle', 'b');
        return [`<svg viewBox="0 0 400 180">${g}</svg>`, `BAHRAIN ${F.source.year} · HOVER A PART`,
          `A stop cost ${f1(pit.total_s)} s: ${f1(pit.in_s)} s coming in, ${f1(pit.out_s)} s going out.`];
      },
    };
    root.querySelectorAll('.sc').forEach(sc => {
      const f = C[sc.dataset.q]; if (!f) return; let [svg, cap, finding] = f();
      // A touch screen cannot hover, and a tap on the card opens the tool, so the hover hint is dropped there.
      if (matchMedia('(hover: none)').matches) cap = cap.replace(/HOVER A \w+ · |\s·\sHOVER A \w+/, '');
      // A figure, so the finding sentence sits above its chart (gate.py's A2 check).
      const box = D.createElement('figure'); box.className = 'qc';
      box.innerHTML = '<figcaption class="lab fnd" data-finding></figcaption>' + svg + '<div class="cap">' + cap + '</div>';
      box.firstChild.textContent = finding; box.querySelector('svg').dataset.chart = sc.dataset.q;
      const pane = sc.classList.contains('acc') ? sc.querySelector('.r') : sc.querySelector('.l'); pane.classList.contains('r') ? (pane.prepend(box), box.style.marginBottom = 'auto') : pane.firstElementChild.after(box);
      undo.push(() => box.remove());
      const capEl = box.querySelector('.cap');
      box.querySelectorAll('[data-t]').forEach(e => { on(e, 'pointerenter', () => { capEl.textContent = e.dataset.t; }); on(e, 'pointerleave', () => { capEl.textContent = cap; }); });
    });
  })();

  // ---- hero terrain: a hidden dot grid shown through nine morphing, wandering windows ----
  (() => {
    // Dot pitch, size and ink match sheet.js. The pointer ripples the windows like water; the dots
    // themselves never move.
    const stage = root.querySelector('.hero .stage'), svg = D.getElementById('trk'), c = D.createElement('canvas'); c.className = 'terr'; stage.prepend(c);
    undo.push(() => c.remove());
    const x = c.getContext('2d'), still = off;
    let w, h, sc = .7, G, r, cols, rows, cov, B = [], RIP = [], last = 0, run = false, vis = true, px = -1e4, py = -1e4, mx = -1e4, my = -1e4;
    const rnd = (a, b) => a + Math.random() * (b - a);
    function size() {
      const q = c.getBoundingClientRect(), d = devicePixelRatio || 1, vb = svg.viewBox.baseVal;
      w = q.width; h = q.height; c.width = w * d; c.height = h * d; x.setTransform(d, 0, 0, d, 0, 0);
      if (vb && vb.width) sc = Math.min(w / vb.width, h / vb.height); G = 9 * sc; r = 2.4 * sc;
      cols = Math.ceil(w / G) + 1; rows = Math.ceil(h / G) + 1; cov = new Float32Array(cols * rows);
      if (!B.length) B = Array.from({ length: 9 }, () => ({ x: rnd(0, w), y: rnd(0, h), R: rnd(60, 110) * sc / .7, hd: rnd(0, 6.28), v: rnd(.12, .3),
        p: [rnd(0, 6.28), rnd(0, 6.28), rnd(0, 6.28)], s: [rnd(.0002, .0005), rnd(.0002, .0005), rnd(.0001, .0003)] }));
    }
    // Water: moving the pointer drops ripples - rings spreading at 0.35 px/ms, gone in 1.4 s - and a
    // soft lens sits under the cursor. They bend where the windows are sampled, not the dots.
    function warp(X, Y, t) {
      let dx = 0, dy = 0;
      for (const q of RIP) { const age = t - q.t, ex = X - q.x, ey = Y - q.y, d = Math.hypot(ex, ey) || 1, f = d - age * .35;
        if (f > 70 || f < -70) continue; const a = 5 * Math.exp(-age / 600) * Math.cos(f * .1) * Math.exp(-f * f / 1200); dx += ex / d * a; dy += ey / d * a; }
      const ex = X - mx, ey = Y - my, d2 = ex * ex + ey * ey; if (d2 < 25600) { const k = .1 * (1 - d2 / 25600) ** 2; dx -= ex * k; dy -= ey * k; }
      return [X + dx, Y + dy];
    }
    function draw(t) {
      if (Math.abs(px - mx) > 2000) { mx = px; my = py; } mx += (px - mx) * .15; my += (py - my) * .15;
      while (RIP.length && t - RIP[0].t > 1400) RIP.shift();
      cov.fill(0); const soft = 1.5 * G;
      for (const b of B) {
        if (!still) { b.hd += Math.sin(t * .0003 + b.p[0]) * .004; b.x += Math.cos(b.hd) * b.v; b.y += Math.sin(b.hd) * b.v;
          const m = b.R * 1.5; if (b.x < -m) b.x = w + m; if (b.x > w + m) b.x = -m; if (b.y < -m) b.y = h + m; if (b.y > h + m) b.y = -m; }
        const R = b.R * (1 + .15 * Math.sin(t * b.s[2] + b.p[1])), lim = R * 1.45 + 40;
        const i0 = Math.max(0, Math.floor((b.x - lim) / G)), i1 = Math.min(cols - 1, Math.ceil((b.x + lim) / G)), j0 = Math.max(0, Math.floor((b.y - lim) / G)), j1 = Math.min(rows - 1, Math.ceil((b.y + lim) / G));
        for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
          const [X, Y] = warp(i * G + G / 2, j * G + G / 2, t), u = X - b.x, v = Y - b.y, d = Math.hypot(u, v), th = Math.atan2(v, u);
          const edge = R * (1 + .22 * Math.sin(3 * th + b.p[0] + t * b.s[0]) + .14 * Math.sin(5 * th + b.p[1] - t * b.s[1]) + .09 * Math.sin(2 * th + b.p[2] + t * b.s[2]));
          const k = Math.min(1, (edge - d) / soft), idx = j * cols + i; if (k > cov[idx]) cov[idx] = k;
        }
      }
      x.clearRect(0, 0, w, h); x.fillStyle = 'rgba(19,19,19,.42)'; x.beginPath();
      for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) { const k = cov[j * cols + i]; if (k <= 0) continue;
        const X = i * G + G / 2, Y = j * G + G / 2, rr = r * (k * k * (3 - 2 * k)); x.moveTo(X + rr, Y); x.arc(X, Y, rr, 0, 6.2832); }
      x.fill();
    }
    function loop(t) { if (!alive) { run = false; return; } draw(still ? 0 : t); if (vis && !still) requestAnimationFrame(loop); else run = false; }
    function kick() { if (!run && vis && alive) { run = true; requestAnimationFrame(loop); } }
    on(window, 'pointermove', e => { const q = c.getBoundingClientRect(), t = performance.now(); px = e.clientX - q.left; py = e.clientY - q.top;
      if (t - last > 90) { RIP.push({ x: px, y: py, t }); last = t; if (RIP.length > 14) RIP.shift(); } }, { passive: true });
    on(window, 'resize', () => { size(); kick(); });
    const io = new IntersectionObserver(es => { vis = es[0].isIntersecting; kick(); }); io.observe(stage); undo.push(() => io.disconnect());
    size(); kick();
  })();

  return () => {
    alive = false;
    ctx.revert();
    for (let i = undo.length - 1; i >= 0; i--) undo[i]();
    D.documentElement.classList.remove('lenis', 'lenis-smooth');
  };
}
