# Diagnostic, not a gate: screenshots at every guide-car stop.
# Usage: tour.py <landing-url> <out-dir> <width> <height>
import sys
from playwright.sync_api import sync_playwright
URL, SP, W, H = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
def go(pg, y, wait):
    # Scroll in wheel steps so Lenis and ScrollTrigger see real scrolling.
    for _ in range(200):
        cur = pg.evaluate('scrollY')
        if abs(cur - y) < 30: break
        pg.mouse.wheel(0, max(-400, min(400, y - cur))); pg.wait_for_timeout(40)
    pg.wait_for_timeout(wait)
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    pg = b.new_page(viewport={'width': W, 'height': H}); errs = []
    pg.on('console', lambda m: m.type == 'error' and errs.append(m.text)); pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(6500); pg.mouse.move(W / 2, H / 2)
    pg.screenshot(path=f'{SP}/t{W}-0hero.png')
    S = pg.evaluate("""()=>{const q=s=>document.querySelector(s),top=e=>e.getBoundingClientRect().top+scrollY,c=document.getElementById('count'),s0=c.parentElement,a0=s0.getBoundingClientRect().top+scrollY,p={start:a0,end:a0+s0.offsetHeight-c.offsetHeight};
      return {pin:[p.start,p.end],grid:top(q('.index'))-innerHeight*.5,stack:top(q('.stack'))+300,tl:top(q('.tl'))+100,spec:top(q('.spec'))-innerHeight*.3,
      au:top(q('#author .k'))-innerHeight*.4,end:document.documentElement.scrollHeight-innerHeight}}""")
    a, e = S['pin']
    go(pg, a + (e - a) * .2, 1500); pg.screenshot(path=f'{SP}/t{W}-1row0.png')
    go(pg, a + (e - a) * .5, 1500); pg.screenshot(path=f'{SP}/t{W}-2row3.png')
    go(pg, S['grid'], 700); pg.screenshot(path=f'{SP}/t{W}-3drift.png'); pg.wait_for_timeout(2200); pg.screenshot(path=f'{SP}/t{W}-4gridrest.png')
    go(pg, S['stack'], 1500); pg.screenshot(path=f'{SP}/t{W}-5cards.png')
    go(pg, S['tl'], 1500); pg.screenshot(path=f'{SP}/t{W}-6method.png')
    go(pg, S['spec'], 1500); pg.screenshot(path=f'{SP}/t{W}-7spec.png')
    go(pg, S['au'], 1500); pg.screenshot(path=f'{SP}/t{W}-8author.png')
    go(pg, S['end'], 3500); pg.screenshot(path=f'{SP}/t{W}-9lap.png'); pg.wait_for_timeout(7500); pg.screenshot(path=f'{SP}/t{W}-10park.png')
    print(W, 'errors:', errs)
    b.close()
