// @ts-nocheck - ported, not rewritten (Phase 2B D6): the guide car module of
// landings/08-finished.html. What changed: three comes from npm (Landing.tsx
// imports this file only at >= 860 px without reduced motion, so phones never
// download it), the canvas is created here, the drive-in starts when the loader
// is removed instead of 3.3 s after load, and the returned cleanup removes
// every listener, trigger and GPU resource.
// Guide car: an F1 car built in code on photos of the RB20 (2024), in its livery colours with no
// logos or text beyond the number 1. It drives in from the left of the hero, runs down the gap beside the
// bars, drifts onto the top edge of the corner grid, runs the right gutter beside the cards,
// rides the method line, races the spec numbers, faces the author's name, laps the footer
// circuit and parks beside it. Desktop only (>= 860 px); off with reduced motion.
//
// Each key is a scroll position and a spot read from a live element rect. Between keys the car
// sits exactly on the interpolated spot (Lenis already smooths the scroll), so it never lags or
// swings against the scroll. Timed keys (intro, drift, lap) play on the clock once reached; where
// one hands over to scrolling, the jump is blended out over 0.3 s. It runs on the GSAP ticker,
// after Lenis and ScrollTrigger have moved the page, so a pinned section and the car never
// disagree for a frame.
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

const D = document, DEG = Math.PI / 180, TILT = 74 * DEG, LEN = 5.45;

export function startCar(host, introAt) {
  const cv = D.createElement('canvas'); cv.id = 'car'; cv.setAttribute("aria-hidden", "true"); host.append(cv);
  const undo = [], on = (t, type, fn, o) => { t.addEventListener(type, fn, o); undo.push(() => t.removeEventListener(type, fn, o)); };
  const ctx = gsap.context(() => {});
  // Model units are metres: nose along +x, left along +y, up along +z, ground at z = 0. Sizes follow
  // photos of the RB20: LEN from front wing to rear wing, a 3.6 wheelbase, 0.36 tyre radius.
  const TR = .36, FX = 1.59, RX = -2.01;
  const NAVY = 0x151b35, RED = 0xcc1433, YEL = 0xffc906, BLK = 0x0b0b0d;
  const mat = (c, r = .6, m = .25) => new THREE.MeshStandardMaterial({ color: c, roughness: r, metalness: m, side: THREE.DoubleSide });
  const PAINT = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .62, metalness: .25, side: THREE.DoubleSide });
  const M_NAVY = mat(NAVY), M_RED = mat(RED, .55, .2), CARB = new THREE.MeshPhysicalMaterial({ color: 0x0e0f12, roughness: .5, metalness: .2, clearcoat: .15, clearcoatRoughness: .4, side: THREE.DoubleSide }),
    BLACK = mat(BLK, .8, .1), TYRE = mat(0x141414, .95, 0), COVER = new THREE.MeshPhysicalMaterial({ color: 0x0d0d10, roughness: .35, metalness: .3, clearcoat: .6, clearcoatRoughness: .2, side: THREE.DoubleSide }),
    LIME = mat(0xc4e000, .4, .3), METAL = mat(0x9a9aa0, .3, .9), LAMP = new THREE.MeshStandardMaterial({ color: 0xff2030, emissive: 0xff1020, emissiveIntensity: 1.5 }), FLOOR = mat(0x050506, .9, 0);
  // Near-black parts reflect less of the studio room, or it lifts them to mid grey.
  for (const [m, k] of [[FLOOR, .15], [TYRE, .35], [BLACK, .35], [CARB, .35], [COVER, .6]]) m.envMapIntensity = k;
  const B = (a, b, c) => new THREE.BoxGeometry(a, b, c), C = (t, b, h, n = 16) => new THREE.CylinderGeometry(t, b, h, n), V = (...a) => new THREE.Vector3(...a);
  const col = new THREE.Color(), cr = (a, b, c, d, t) => .5 * (2 * b + (c - a) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (3 * b - a - 3 * c + d) * t * t * t);
  const sp = (v, e) => Math.sign(v) * Math.abs(v) ** e, cl = t => Math.min(1, Math.max(0, t));
  // Livery edges ramp over a centimetre or two so they do not stair-step between vertices; band is
  // the same on a ring angle, in radians.
  const blend = (a, b, t) => new THREE.Color(a).lerp(new THREE.Color(b), cl(t)), ramp = (d, w = .012) => cl(d / w + .5), band = (th, lo, hi) => ramp(th - lo, .03) * ramp(hi - th, .03);
  const resample = (S, steps) => { const R = [], g = j => S[Math.max(0, Math.min(S.length - 1, j))];
    for (let i = 0; i <= steps; i++) { const u = i / steps * (S.length - 1), k = Math.min(S.length - 2, Math.floor(u)), f = u - k; R.push(S[0].map((_, c) => cr(g(k - 1)[c], g(k)[c], g(k + 1)[c], g(k + 2)[c], f))); }
    return R; };
  const mesh = (pos, idx, m, cols) => { const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    if (cols) geo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3)); geo.setIndex(idx); geo.computeVertexNormals(); return new THREE.Mesh(geo, m); };
  // A body panel: cross-sections [x, yCentre, halfWidth, zBottom, zTop, bottomHalfWidth, bottomCentre],
  // front to back, resampled with Catmull-Rom and wrapped in superellipse rings that narrow from the
  // top half to the bottom half (the sidepod undercut). paint(x, y, z, a) colours a vertex; a is its
  // angle round the ring, 0 at +y and PI/2 on top, -1 on the end caps.
  function loft(S, paint, p = 3.2, n = 72, steps = 128) {
    const R = resample(S.map(s => [s[0], s[1], s[2], s[3], s[4], s[5] ?? s[2], s[6] ?? s[1]]), steps), pos = [], cols = [], idx = [];
    const put = (x, y, z, a) => { pos.push(x, y, z); col.set(typeof paint === 'function' ? paint(x, y, z, a) : paint); cols.push(col.r, col.g, col.b); };
    R.forEach(([x, yc, hw, z0, z1, hb, yb]) => { const zc = (z0 + z1) / 2, hh = Math.max(.003, (z1 - z0) / 2);
      const ring = a => { const c = Math.cos(a), s = Math.sin(a), t = (s + 1) / 2; return [yb + (yc - yb) * t + Math.max(.003, hb + (hw - hb) * t) * sp(c, 2 / p), zc + hh * sp(s, 2 / p)]; };
      // Ring points evenly spaced by arc length: even angles bunch them at the corners and leave the
      // flat flanks so sparse that livery edges stair-step there.
      const M = 3 * n, A = [0], P = [ring(0)];
      for (let j = 1; j <= M; j++) { const pt = ring(j / M * Math.PI * 2); A.push(A[j - 1] + Math.hypot(pt[0] - P[j - 1][0], pt[1] - P[j - 1][1])); P.push(pt); }
      for (let i = 0, j = 0; i < n; i++) { const d = i / n * A[M]; while (A[j + 1] < d) j++; const a = (j + (d - A[j]) / (A[j + 1] - A[j] || 1)) / M * Math.PI * 2; put(x, ...ring(a), a); } });
    for (let k = 0; k < R.length - 1; k++) for (let i = 0; i < n; i++) { const a = k * n + i, b = k * n + (i + 1) % n; idx.push(a, a + n, b, b, a + n, b + n); }
    for (const k of [0, R.length - 1]) { const [x, yc, , z0, z1, , yb] = R[k], c = pos.length / 3; put(x, (yc + yb) / 2, (z0 + z1) / 2, -1); for (let i = 0; i < n; i++) idx.push(c, k * n + i, k * n + (i + 1) % n); }
    return mesh(pos, idx, PAINT, cols);
  }
  // A thin wing element: stations [lx, ly, lz, tx, ty, tz] are its leading and trailing edge along
  // the span, resampled with Catmull-Rom and given a thin airfoil section th thick.
  const L = V(), T = V(), cd = V(), sd = V(), nm = V();
  function ribbon(S, m = CARB, th = .014, steps = 24) {
    const R = resample(S, steps), F = [[0, 0], [.2, .5], [.65, .35], [1, 0], [.65, -.3], [.2, -.5]], n = F.length, pos = [], idx = [];
    R.forEach((r, i) => { const a = R[Math.max(0, i - 1)], b = R[Math.min(R.length - 1, i + 1)];
      L.set(r[0], r[1], r[2]); T.set(r[3], r[4], r[5]); cd.subVectors(T, L); sd.set(b[0] - a[0] + b[3] - a[3], b[1] - a[1] + b[4] - a[4], b[2] - a[2] + b[5] - a[5]); nm.crossVectors(cd, sd).normalize();
      for (const [f, t] of F) pos.push(L.x + cd.x * f + nm.x * th * t, L.y + cd.y * f + nm.y * th * t, L.z + cd.z * f + nm.z * th * t); });
    for (let k = 0; k < R.length - 1; k++) for (let i = 0; i < n; i++) { const a = k * n + i, b = k * n + (i + 1) % n; idx.push(a, a + n, b, b, a + n, b + n); }
    for (const k of [0, R.length - 1]) for (let i = 1; i < n - 1; i++) idx.push(k * n, k * n + i, k * n + i + 1);
    return mesh(pos, idx, m);
  }
  // Stations given from the centre line outwards, mirrored to span both sides.
  const sym = S => [...S.slice(1).reverse().map(([a, b, c, d, e, f]) => [a, -b, c, d, -e, f]), ...S];
  const add = (g, o, x = 0, y = 0, z = 0) => { o.position.set(x, y, z); g.add(o); return o; };
  const box = (g, dims, m, x, y, z, rz = 0, ry = 0) => { const o = add(g, new THREE.Mesh(B(...dims), m), x, y, z); o.rotation.set(0, ry, rz); return o; };
  const rod = (g, a, b, r = .018, m = CARB) => { const A = V(...a), Z = V(...b), o = new THREE.Mesh(C(r, r, A.distanceTo(Z), 6), m);
    o.position.copy(A).add(Z).multiplyScalar(.5); o.quaternion.setFromUnitVectors(V(0, 1, 0), Z.sub(A).normalize()); g.add(o); };
  const fronts = [], spins = [];
  const tyre = w => new THREE.LatheGeometry([[.24, -w / 2], [.325, -w / 2], [.35, -w / 2 + .03], [TR, -w / 2 + .08], [TR, w / 2 - .08], [.35, w / 2 - .03], [.325, w / 2], [.24, w / 2]].map(([r, y]) => new THREE.Vector2(r, y)), 40);
  function wheel(g, x, y, w, front) {
    const s = Math.sign(y), hub = add(g, new THREE.Group(), x, y, TR), steer = add(hub, new THREE.Group()), spin = add(steer, new THREE.Group());
    spin.add(new THREE.Mesh(tyre(w), TYRE));
    for (const k of [1, -1]) {
      add(spin, new THREE.Mesh(C(.27, .27, .012, 32), COVER), 0, k * (w / 2 - .005), 0);   // wheel cover
      const band = add(spin, new THREE.Mesh(new THREE.RingGeometry(.3, .318, 48), M_RED), 0, k * (w / 2 + .003), 0); band.rotation.x = Math.PI / 2;   // soft-tyre stripe
      add(spin, new THREE.Mesh(C(.05, .05, .03, 12), LIME), 0, k * (w / 2 + .008), 0);   // wheel nut
      add(spin, new THREE.Mesh(B(.36, .006, .02), mat(0x2a2a30, .5, .3)), 0, k * (w / 2 + .004), 0);   // a mark on the cover, so the spin reads
    }
    add(steer, new THREE.Mesh(C(.17, .17, .12, 14), BLACK), 0, -s * (w / 2 + .04), 0);   // brake duct drum
    if (front) { add(steer, new THREE.Mesh(new THREE.CylinderGeometry(TR + .03, TR + .03, w * .92, 20, 1, true, -25 * DEG, 95 * DEG), CARB)); fronts.push(steer); }   // wheel deflector over the tyre
    spins.push(spin);
  }
  function build() {
    const g = new THREE.Group();
    // Floor and diffuser: matte black, or it reads grey.
    add(g, loft([[1.2, 0, .25, .05, .09], [1, 0, .45, .04, .09], [.6, 0, .7, .035, .085], [0, 0, .8, .035, .085], [-.8, 0, .78, .035, .085], [-1.35, 0, .62, .035, .09], [-1.62, 0, .52, .04, .12], [-1.95, 0, .52, .1, .2], [-2.25, 0, .5, .22, .34], [-2.38, 0, .48, .28, .38]], BLK, 8, 36, 64)).material = FLOOR;
    // Nose and tub: yellow tip behind a red flame edge, a red pin stripe along the upper flank.
    // The cockpit opening is painted black on the tub top.
    const tub = add(g, loft([[2.58, 0, .045, .11, .2], [2.45, 0, .075, .11, .27], [2.15, 0, .11, .13, .38], [1.8, 0, .15, .14, .49], [1.4, 0, .2, .12, .56], [1, 0, .25, .1, .62], [.6, 0, .29, .09, .66], [.2, 0, .32, .08, .68], [-.25, 0, .33, .08, .67], [-.7, 0, .3, .08, .6]],
      (x, y, z, a) => { const e = 2.05 + .035 * Math.sin(z * 60 + Math.abs(y) * 25), up = Math.sin(a);
        const pit = up > .75 && ((x - .08) / .36) ** 2 + (y / .2) ** 2 < 1, stripe = a > 0 && a < Math.PI ? band(Math.min(a, Math.PI - a), .52, .66) * ramp(x - .55, .03) * ramp(.93 - x, .03) : 0;
        return blend(blend(blend(pit ? BLK : NAVY, RED, stripe), RED, ramp(x - e + .07, .025)), YEL, ramp(x - e, .025)); }));
    // Airbox and engine cover: yellow airbox running back in a wedge, edged in red.
    g.add(loft([[-.28, 0, .11, .6, .9], [-.4, 0, .16, .55, .95], [-.6, 0, .22, .45, .94], [-.9, 0, .26, .32, .9], [-1.2, 0, .26, .26, .83], [-1.5, 0, .22, .23, .73], [-1.8, 0, .15, .23, .6], [-2.05, 0, .1, .24, .48], [-2.3, 0, .05, .27, .4]],
      (x, y, z) => { const zb = .64 + Math.max(0, -.5 - x) * .2; return blend(blend(NAVY, RED, ramp(z - zb + .05, .02) * ramp(-.4 - x, .03)), YEL, ramp(z - zb, .02)); }));
    add(g, loft([[-.262, 0, .075, .72, .88], [-.3, 0, .075, .72, .88]], BLK, 3, 36, 4));   // airbox intake
    for (const s of [1, -1]) {
      // Sidepod: a letterbox inlet high up, a deep undercut below, the top falling away to the floor.
      // Its inboard edge is buried in the tub and engine cover, so the body reads as one mass.
      g.add(loft([[.46, .45 * s, .1, .54, .65, .06, .45 * s], [.36, .49 * s, .2, .34, .7, .08, .42 * s], [.1, .5 * s, .24, .1, .71, .08, .36 * s], [-.3, .48 * s, .25, .1, .69, .09, .32 * s], [-.7, .44 * s, .23, .1, .64, .09, .28 * s], [-1.1, .37 * s, .2, .1, .54, .08, .24 * s], [-1.45, .28 * s, .14, .1, .41, .07, .2 * s], [-1.75, .2 * s, .07, .12, .27, .05, .16 * s]],
        (x, y, z, a) => blend(NAVY, RED, a < 0 ? 0 : band(s > 0 ? a : Math.PI - a, 1.0, 1.16) * ramp(.36 - x, .03) * ramp(x + 1.15, .03))));
      box(g, [.03, .2, .06], BLACK, .47, .45 * s, .6);   // inlet mouth
      // Front wing endplate, rear wing endplate.
      g.add(ribbon([[2.74, .97 * s, .04, 2.2, .97 * s, .04], [2.71, .97 * s, .14, 2.08, .97 * s, .3], [2.62, .95 * s, .2, 1.96, .93 * s, .5]], CARB, .016, 12));
      g.add(ribbon([[-2.22, .55 * s, .42, -2.6, .55 * s, .4], [-2.2, .56 * s, .7, -2.72, .56 * s, .74], [-2.3, .54 * s, .92, -2.73, .54 * s, .96]], CARB, .016, 12));
      rod(g, [.46, .55 * s, .66], [.42, .6 * s, .72], .014); box(g, [.08, .17, .08], M_NAVY, .42, .62 * s, .74);   // mirror
      // Suspension: pull rod at the front, push rod at the back, carbon arms.
      rod(g, [FX + .26, .16 * s, .5], [FX - .02, .66 * s, .52]); rod(g, [FX - .3, .2 * s, .52], [FX - .02, .66 * s, .52]);
      rod(g, [FX + .28, .13 * s, .22], [FX, .68 * s, .2]); rod(g, [FX - .3, .16 * s, .2], [FX, .68 * s, .2]);
      rod(g, [FX + .12, .15 * s, .34], [FX + .1, .68 * s, .34]); rod(g, [FX - .02, .66 * s, .5], [FX - .25, .17 * s, .22]);
      rod(g, [RX + .35, .24 * s, .48], [RX, .58 * s, .52]); rod(g, [RX - .25, .16 * s, .5], [RX, .58 * s, .52]);
      rod(g, [RX + .38, .26 * s, .2], [RX, .6 * s, .2]); rod(g, [RX - .3, .16 * s, .22], [RX, .6 * s, .2]);
      rod(g, [RX, .58 * s, .24], [RX + .1, .2 * s, .45]); rod(g, [RX, .58 * s, .36], [RX + .05, .12 * s, .33], .024);
      wheel(g, FX, .81 * s, .305, true); wheel(g, RX, .79 * s, .405, false);
    }
    // Front wing: main plane and three flaps, low and flat in the middle, sweeping back and climbing
    // steeply into the endplates, each tucked under the one above so no slot shows from above.
    // Each is [LE x, TE x, LE z, TE z], at the centre then at the tip.
    for (const [lc, lo, tc, to, zlc, zlo, ztc, zto] of [[2.72, 2.62, 2.44, 2.28, .07, .08, .09, .16], [2.5, 2.33, 2.34, 2.12, .095, .15, .15, .29], [2.39, 2.17, 2.25, 2.02, .145, .27, .21, .39], [2.3, 2.06, 2.19, 1.95, .2, .37, .25, .47]])
      g.add(ribbon(sym([0, .25, .5, .72, .88, .95].map(y => { const k = (y / .95) ** 1.6, kz = (y / .95) ** 2.5;
        return [lc + (lo - lc) * k, y, zlc + (zlo - zlc) * kz, tc + (to - tc) * k, y, ztc + (zto - ztc) * kz]; })), CARB, .014, 40));
    // Rear wing: main plane, upper flap, tips curving down into the endplates; beam wing below.
    g.add(ribbon(sym([[-2.24, 0, .7, -2.5, 0, .76], [-2.24, .36, .7, -2.5, .36, .76], [-2.26, .5, .66, -2.52, .5, .72], [-2.28, .55, .58, -2.54, .55, .62]]), CARB, .02));
    g.add(ribbon(sym([[-2.47, 0, .79, -2.7, 0, .93], [-2.47, .4, .79, -2.7, .4, .93], [-2.49, .55, .8, -2.72, .55, .94]]), CARB, .016));
    g.add(ribbon(sym([[-2.3, 0, .36, -2.44, 0, .38], [-2.3, .45, .36, -2.44, .45, .38]]), CARB, .012));
    g.add(ribbon(sym([[-2.44, 0, .41, -2.56, 0, .46], [-2.44, .45, .41, -2.56, .45, .46]]), CARB, .012));
    rod(g, [-2.3, 0, .34], [-2.38, 0, .74], .028);   // pillar
    box(g, [.7, .24, .2], CARB, -2.05, 0, .26); box(g, [.36, .1, .09], CARB, -2.4, 0, .3); box(g, [.025, .1, .05], LAMP, -2.59, 0, .3);   // gearbox, crash structure, rain light
    const ex = add(g, new THREE.Mesh(C(.045, .05, .12, 12), METAL), -2.42, 0, .4); ex.rotation.z = Math.PI / 2;
    // Halo, cockpit, driver, T-cam.
    g.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([[-.3, .29, .64], [-.05, .31, .8], [.28, .22, .85], [.46, 0, .86], [.28, -.22, .85], [-.05, -.31, .8], [-.3, -.29, .64]].map(p => V(...p))), 48, .032, 8), M_NAVY));
    rod(g, [.46, 0, .86], [.64, 0, .64], .03, M_NAVY);
    const hg = new THREE.SphereGeometry(.12, 22, 16), hc = [], hp = hg.attributes.position;
    for (let i = 0; i < hp.count; i++) { const x = hp.getX(i), y = hp.getY(i); col.set(y > .06 ? RED : x > .05 && y > -.035 && y < .03 ? BLK : 0xeeeeee); hc.push(col.r, col.g, col.b); }
    hg.setAttribute('color', new THREE.Float32BufferAttribute(hc, 3));
    const hel = add(g, new THREE.Mesh(hg, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .35, metalness: .2 })), -.05, 0, .76); hel.rotation.x = Math.PI / 2; hel.scale.set(1.15, .95, 1);
    box(g, [.12, .18, .07], BLACK, -.5, 0, .975);   // T-cam
    // The race number, a red 1, laid where a ray from outside meets the tub. On the nose top it reads
    // upright with the nose pointing right, as on the car; on each flank it reads from that side.
    const one = new THREE.ShapeGeometry(new THREE.Shape([[.2, 0], [.58, 0], [.58, 1], [.3, 1], [0, .8], [0, .62], [.2, .72]].map(([x, y]) => new THREE.Vector2(x - .29, y - .5))));
    const ray = new THREE.Raycaster(), n = V(), r = V(), u = V();
    const num = (o, d, up, h) => { ray.set(V(...o), V(...d)); const hit = ray.intersectObject(tub)[0]; n.copy(hit.face.normal); if (n.dot(ray.ray.direction) > 0) n.negate();
      u.set(...up).addScaledVector(n, -n.dot(V(...up))).normalize(); r.crossVectors(u, n);
      const m = add(g, new THREE.Mesh(one, M_RED)); m.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(r, u, n)); m.position.copy(hit.point).addScaledVector(n, .005); m.scale.setScalar(h); };
    num([1.38, 0, 2], [0, 0, -1], [0, 1, 0], .2);
    for (const s of [1, -1]) num([1.02, s, .45], [0, -s, 0], [0, 0, 1], .15);
    return g;
  }

  const R = new THREE.WebGLRenderer({ canvas: cv, alpha: true, antialias: true });
  const scene = new THREE.Scene(), cam = new THREE.OrthographicCamera(0, 1, 0, -1, -3000, 3000);
  // A studio room for reflections, then key, fill and rim lights. Light positions are directions
  // in screen space: +y is up the page, +z is toward the viewer.
  scene.environment = new THREE.PMREMGenerator(R).fromScene(new RoomEnvironment(), .04).texture;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3a44, .8));
  for (const [x, y, z, i] of [[-.4, .5, 1, 2.2], [.7, -.3, .6, .7], [0, 1, -.6, 1.2]]) { const l = new THREE.DirectionalLight(0xffffff, i); l.position.set(x, y, z); scene.add(l); }
  // tilt is the camera elevation (0 top-down, 1 near side profile); yaw is the heading inside it.
  const tilt = new THREE.Group(), yaw = new THREE.Group(), body = build(); yaw.add(body); tilt.add(yaw); scene.add(tilt);
  const size = () => { R.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); R.setSize(innerWidth, innerHeight, false); cam.right = innerWidth; cam.bottom = -innerHeight; cam.updateProjectionMatrix(); };
  size(); on(window, 'resize', size);

  // Grab to turn: dragging over the car spins it about its own up axis (sideways) and tips the view
  // (up and down); on release it eases back to the path's pose. The canvas stays pointer-events:none
  // so the page under it keeps working, and hits are raycast from window events instead. The ray
  // starts at the camera's near plane: setFromCamera puts it mid-range (z 0), under a top-down car. A press on
  // the car eats the click that follows, so nothing under it is clicked too.
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), root = D.documentElement;
  const hit = e => { if (innerWidth < 860) return false; ndc.set(e.clientX / innerWidth * 2 - 1, 1 - e.clientY / innerHeight * 2); ray.setFromCamera(ndc, cam); ray.ray.origin.z = 3000; return ray.intersectObject(body, true).length > 0; };
  const hand = c => { root.classList.toggle('car-grab', c === 1); root.classList.toggle('car-grabbing', c === 2); };
  let turn = 0, tip = 0, drag = null, eat = false;
  on(window, 'pointermove', e => {
    if (drag) { turn = drag.turn + (e.clientX - drag.x) * .012; tip = Math.max(-1.4, Math.min(1.4, drag.tip + (e.clientY - drag.y) * .008)); return; }
    hand(e.pointerType === 'mouse' && hit(e) ? 1 : 0);
  }, { passive: true });
  on(window, 'pointerdown', e => {
    eat = false; if (e.button !== 0 || !hit(e)) return;
    e.preventDefault(); e.stopPropagation(); eat = true;
    drag = { x: e.clientX, y: e.clientY, turn, tip }; hand(2);
  }, { capture: true });
  const drop = e => { if (!drag) return; drag = null; turn = Math.atan2(Math.sin(turn), Math.cos(turn)); hand(hit(e) ? 1 : 0); };
  on(window, 'pointerup', drop); on(window, 'pointercancel', drop);
  on(window, 'click', e => { if (eat) { eat = false; e.preventDefault(); e.stopPropagation(); } }, { capture: true });

  // Smoke: white puffs with a faint grey rim, in page coordinates so a trail stays where it was left.
  const tex = (() => { const c = D.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d');
    for (const [px, py, r] of [[64, 64, 44], [44, 58, 30], [84, 56, 30], [58, 82, 28], [80, 80, 26]]) { const g = x.createRadialGradient(px, py, 0, px, py, r);
      g.addColorStop(0, 'rgba(255,255,255,.9)'); g.addColorStop(.6, 'rgba(250,250,248,.5)'); g.addColorStop(.85, 'rgba(205,205,200,.22)'); g.addColorStop(1, 'rgba(200,200,196,0)'); x.fillStyle = g; x.fillRect(0, 0, 128, 128); }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; })();
  const puffs = [], rnd = (a, b) => a + Math.random() * (b - a);
  function puff(x, y, vx, vy, r0, r1, life, a) {
    if (puffs.length > 200) return;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0, rotation: rnd(0, 6.3) }));
    s.position.z = -1000; scene.add(s); puffs.push({ s, x, y, vx, vy, r0, r1, life, a, t: 0 });
  }

  // Anchors. Every spot is read from a live rect, so resizes and entrance transforms are followed.
  // In side view the car's origin is its ground line, so parked spots are the line it stands on.
  const q = s => D.querySelector(s), rc = e => e.getBoundingClientRect();
  const at = (trigger, start) => { let t; ctx.add(() => { t = ScrollTrigger.create({ trigger, start }); }); return () => t.start; };
  const parts = q('#parts'), lis = [...parts.children], leftCol = q('#count > div'), glab = q('#grid > .lab'), grid = q('.index'),
    stack = q('.stack'), tl = q('.tl'), plab = q('#proof > .lab'), spec = q('.spec'), name = q('#author .k'), stage = q('.sig-stage'), ssvg = q('.sig-svg');
  const pin = () => ScrollTrigger.getAll().find(s => s.pin && s.trigger && s.trigger.id === 'count') || { start: 0, end: 1 };
  // Hero: parked in side view on the photo band's bottom line, right end, over its yellow.
  const photoBand = q('.hero .photo'), heroL = () => Math.min(224, innerWidth * .128, rc(photoBand).height * .96);
  // Wheels on the band's bottom border: the ground sits cos(TILT) of a wheel unit below the origin, as gridRest.
  const heroPos = () => { const r = rc(photoBand), L = heroL(); return [innerWidth - innerWidth * .03 - L / 2, r.bottom - 3 - Math.cos(TILT) * L / LEN - 2]; };
  // Count: straight down the gap between the number and the bars, level with the lit bar.
  const gapL = () => Math.min(120, Math.max(60, (rc(parts).left - rc(leftCol).right - 10) / .39));
  const rowPos = i => () => { const r = rc(lis[i]); return [(rc(leftCol).right + r.left) / 2, r.top + r.height / 2]; };
  const rowS = (i, f) => () => { const p = pin(); return p.start + (p.end - p.start) * Math.min(1, (i + 1 + f) / 6.999); };
  // Grid: speed along the label row, drift through 180 degrees and settle in side view on the
  // grid's top edge (wheels 1.0 unit out from the centre line, so cos(TILT) of that below it).
  const gY = () => { const r = rc(glab); return r.top + r.height / 2; }, gridL = () => Math.max(120, Math.min(160, innerWidth * .11));
  const gridRest = () => { const r = rc(grid), L = gridL(); return { x: r.right - L * .55 - 6, y: r.top - Math.cos(TILT) * L / LEN - 2 }; };
  const drift = t => {
    const y = gY(), bx = rc(glab).right + 110, cx = rc(grid).right - 380, L = gridL(), P = gridRest();
    if (t < .5) { const e = (t / .5) ** 2; return { x: bx + (cx - bx) * e, y, h: 0, v: 0, L }; }
    const u = (t - .5) / .5, e = 1 - (1 - u) ** 3;
    return { x: cx + (P.x - cx) * e, y: y + (P.y - y) * e, h: -180 * (1 - (1 - u) ** 2.2), v: Math.max(0, (u - .45) / .55) ** 1.5, L };
  };
  const gut = () => (innerWidth + rc(stack).right) / 2, gutL = () => Math.min(130, (innerWidth - rc(stack).right) * 2.1);
  const lineX = () => rc(tl).left + 31.5, bandY = () => (rc(plab).bottom + rc(spec).top) / 2;
  const nameBox = () => { const r = D.createRange(); r.selectNodeContents(name); return r.getBoundingClientRect(); }, auL = () => Math.min(210, innerWidth * .15);
  // Footer: track points come from the printed ink path through its screen matrix.
  const ink = () => ssvg.querySelector('path[stroke="#131313"]');
  const onTrack = len => { const p = ink(), m = p.getScreenCTM(), T = p.getTotalLength(), w = l => { const a = p.getPointAtLength(((l % T) + T) % T); return new DOMPoint(a.x, a.y).matrixTransform(m); };
    const A = w(len), P0 = w(len - 5), P1 = w(len + 5); return [A.x, A.y, Math.atan2(P1.y - P0.y, P1.x - P0.x) / DEG]; };
  const lapL = () => Math.max(34, Math.min(48, rc(stage).height * .08));
  const parkAt = () => { const p = ink(), m = p.getScreenCTM(), bb = p.getBBox(), s = rc(stage), right = m.a * (bb.x + bb.width) + m.e;
    return { x: (right + s.right) / 2, y: s.top + s.height * .84, L: Math.min(140, (s.right - right) * .62) }; };
  const lap = t => {
    const T = ink().getTotalLength(), k = .8, a = .1;
    if (t < k) { const u = t / k, d = u < a ? u * u / (2 * a) : u - a / 2, [x, y, h] = onTrack(T * d / (1 - a / 2)); return { x, y, h, v: 0, L: lapL() }; }
    const u = 1 - (1 - (t - k) / (1 - k)) ** 2, [x0, y0, h0] = onTrack(0), P = parkAt(), c = [x0 + Math.cos(h0 * DEG) * 140, y0 + Math.sin(h0 * DEG) * 140];
    const x = (1 - u) ** 2 * x0 + 2 * (1 - u) * u * c[0] + u * u * P.x, y = (1 - u) ** 2 * y0 + 2 * (1 - u) * u * c[1] + u * u * P.y;
    const dx = 2 * (1 - u) * (c[0] - x0) + 2 * u * (P.x - c[0]), dy = 2 * (1 - u) * (c[1] - y0) + 2 * u * (P.y - c[1]), w = Math.max(0, (u - .55) / .45);
    return { x, y, h: mix(Math.atan2(dy, dx) / DEG, 180, w), v: w, L: lapL() + (P.L - lapL()) * w };
  };

  const keys = [
    { s: () => 0, at: introAt, timed: { dur: 1800, fn: t => { const [x, y] = heroPos(), L = heroL(), e = 1 - (1 - t) ** 3; return { x: innerWidth + L - (innerWidth + L - x) * e, y, h: 180, v: .3 + .7 * Math.max(0, (t - .55) / .45), L }; } } },
    ...lis.flatMap((_, i) => [{ s: rowS(i, 0), pos: rowPos(i), h: 90, L: gapL, lin: true }, { s: i === lis.length - 1 ? () => pin().end : rowS(i, .6), pos: rowPos(i), h: 90, L: gapL }]),
    { s: at(grid, 'top 65%'), timed: { dur: 1900, fn: drift } },
    { s: at(grid, 'bottom 55%'), pos: () => { const P = gridRest(); return [P.x, P.y]; }, h: 180, v: 1, L: gridL },
    { s: at(stack, 'top 50%'), pos: () => [gut(), rc(stack).top], h: 90, L: gutL, lin: true },
    { s: at(stack, 'bottom 50%'), pos: () => [gut(), rc(stack).bottom], h: 90, L: gutL },
    { s: at(tl, 'top 70%'), pos: () => [lineX(), rc(tl).top], h: 90, L: () => 110, lin: true },
    { s: at(tl, 'bottom 70%'), pos: () => [lineX(), rc(tl).bottom], h: 90, L: () => 110 },
    { s: at(spec, 'top 80%'), pos: () => [rc(spec).left + 60, bandY()], h: 0, L: () => 120 },
    { s: at(spec, 'top 35%'), pos: () => [rc(spec).right - 60, bandY()], h: 0, L: () => 120 },
    { s: at(name, 'top 60%'), pos: () => { const b = nameBox(); return [b.left - auL() * .7, b.bottom - b.height * .18]; }, h: 0, v: 1, L: auL },
    { s: at(stage, 'center 58%'), timed: { dur: 9000, fn: lap } },
  ];

  function mix(a, b, t) { return a + wrap(b - a) * t; }
  function wrap(d) { return ((d % 360) + 540) % 360 - 180; }
  function stateAt(k, now, reached) {
    if (!k.timed) { const [x, y] = k.pos(); return { x, y, h: k.h, v: k.v || 0, L: k.L() }; }
    if (!reached) return k.timed.fn(0);
    const t0 = k.at ?? k.t0; return k.timed.fn(t0 == null ? 0 : Math.min(1, Math.max(0, (now - t0) / k.timed.dur)));
  }
  function target(now) {
    const S = scrollY, s = []; keys.forEach((k, i) => s.push(Math.max(k.s(), i ? s[i - 1] + 1 : -1e9)));
    keys.forEach((k, i) => { if (!k.timed || k.at) return; if (S >= s[i] && k.t0 == null) k.t0 = now; else if (S < s[i] - 40) k.t0 = null; });
    let i = 0; while (i < keys.length - 1 && S >= s[i + 1]) i++;
    const a = stateAt(keys[i], now, true); if (i === keys.length - 1 || S < s[0]) return { ...a, i };
    const b = stateAt(keys[i + 1], now, false), t = Math.min(1, Math.max(0, (S - s[i]) / (s[i + 1] - s[i]))), e = keys[i].lin ? t : t * t * (3 - 2 * t);
    const o = { i, x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, v: a.v + (b.v - a.v) * e, L: a.L + (b.L - a.L) * e, h: mix(a.h, b.h, e) };
    if (!keys[i].lin && Math.hypot(b.x - a.x, b.y - a.y) > 30) o.h = mix(o.h, Math.atan2(b.y - a.y, b.x - a.x) / DEG, Math.sin(Math.PI * t) ** .6);
    return o;
  }

  const tmp = new THREE.Vector3(), clamp = (x, a) => Math.max(-a, Math.min(a, x));
  let prev = null, lastI = -1, ox = 0, oy = 0, oh = 0, oL = 0, ov = 0, vx = 0, vy = 0, hdot = 0, fwdL = 0, acc = 0, spin = 0, idleT = 0, emit = 0, last = performance.now();
  const frame = () => {
    const now = performance.now(), raw = (now - last) / 1000, dt = Math.min(1 / 30, Math.max(1e-3, raw)); last = now;
    if (innerWidth < 860) return;
    const S = scrollY, T = target(now), tx = T.x, ty = T.y + S;
    // A timed key starting, finishing early or being scrolled away can jump the target: keep the
    // car where it was and let the difference decay.
    if (prev && T.i !== lastI && (keys[lastI]?.timed || keys[T.i].timed)) { ox = prev.x - tx; oy = prev.y - ty; oh = wrap(prev.h - T.h); oL = prev.L - T.L; ov = prev.v - T.v; }
    lastI = T.i;
    const k = Math.exp(-dt / .3); ox *= k; oy *= k; oh *= k; oL *= k; ov *= k;
    const x = tx + ox, y = ty + oy, h = T.h + oh, L = T.L + oL, v = Math.min(1, Math.max(0, T.v + ov)), hr = h * DEG;
    if (prev) { const a = 1 - Math.exp(-dt / .1); vx += ((x - prev.x) / dt - vx) * a; vy += ((y - prev.y) / dt - vy) * a; hdot += (wrap(h - prev.h) / dt - hdot) * a; }
    prev = { x, y, h, L, v };
    const sp = Math.hypot(vx, vy), fwd = vx * Math.cos(hr) + vy * Math.sin(hr), idle = 1 - Math.min(1, sp / 50), u = L / LEN;
    acc += ((fwd - fwdL) / dt - acc) * (1 - Math.exp(-dt / .15)); fwdL = fwd;

    // Engine idle: a small shake, stronger when parked. Leans out of turns, squats under throttle,
    // front wheels steer into the turn and all four roll with the distance covered.
    const j = (.3 + .7 * idle) * .8;
    tilt.position.set(x + (Math.random() - .5) * j, -(y - S + (Math.random() - .5) * j), 0);
    if (!drag) { const r = Math.exp(-raw / .25); turn *= r; tip *= r; }   // raw time: slow frames still ease back in 1 s
    tilt.rotation.x = -v * TILT + tip; yaw.rotation.z = -hr + turn + (Math.random() - .5) * .006 * idle; body.scale.setScalar(u);
    body.rotation.x = clamp(-hdot * fwd * 1.5e-6, .06); body.rotation.y = clamp(-acc * 1.5e-5, .035);
    const steer = clamp(hdot * DEG * .15 * Math.sign(fwd || 1), .38); fronts.forEach(g => { g.rotation.z = -steer; });
    spin += fwd * dt / (TR * u); spins.forEach(g => { g.rotation.y = spin; });

    scene.updateMatrixWorld();
    const P = (lx, ly, lz) => { tmp.set(lx, ly, lz).applyMatrix4(body.matrixWorld); return [tmp.x, -tmp.y + S]; }, ex = P(-2.5, 0, .4), bk = [-Math.cos(hr), -Math.sin(hr)];
    idleT -= dt;
    if (sp < 30 && idleT <= 0) { idleT = rnd(.22, .42); puff(ex[0], ex[1], bk[0] * 16 + rnd(-5, 5), bk[1] * 16 - rnd(10, 22), L * .035, L * .15, rnd(1.4, 2), .8); }
    emit += dt * Math.min(45, sp / 14);
    while (emit >= 1) { emit--; const w = Math.random() < .5 ? ex : P(-1.6, rnd(-.8, .8), .05); puff(w[0], w[1], -vx * .1 + rnd(-18, 18), -vy * .1 + rnd(-18, 18) - 6, L * .05, L * .26, rnd(1.1, 1.7), .6); }
    const slip = sp > 150 ? Math.abs(wrap(h - Math.atan2(vy, vx) / DEG)) : 0;
    if (slip > 25 && slip < 155 && Math.random() < .7) for (const s of [1, -1]) { const w = P(-1.6, .85 * s, .05); puff(w[0], w[1], rnd(-30, 30), rnd(-30, 30), L * .08, L * .42, rnd(1.3, 2), .7); }

    for (let i = puffs.length - 1; i >= 0; i--) {
      const p = puffs[i]; p.t += dt; const f = p.t / p.life;
      if (f >= 1) { scene.remove(p.s); p.s.material.dispose(); puffs.splice(i, 1); continue; }
      const d = Math.pow(.25, dt); p.vx *= d; p.vy *= d; p.x += p.vx * dt; p.y += p.vy * dt;
      const r = p.r0 + (p.r1 - p.r0) * (1 - (1 - f) ** 2); p.s.scale.set(r * 2, r * 2, 1); p.s.position.set(p.x, -(p.y - S), -1000);
      p.s.material.opacity = p.a * Math.min(1, f / .12) * (1 - f) ** 1.4;
    }
    R.render(scene, cam);
  };
  gsap.ticker.add(frame);

  return () => {
    gsap.ticker.remove(frame);
    ctx.revert();
    for (let i = undo.length - 1; i >= 0; i--) undo[i]();
    for (const p of puffs) p.s.material.dispose();
    scene.traverse(o => { o.geometry?.dispose(); });
    R.dispose(); cv.remove();
    D.documentElement.classList.remove('car-grab', 'car-grabbing');
  };
}
