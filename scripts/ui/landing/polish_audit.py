# Diagnostic, not a gate: tab order, focus rings, phone touch targets, captions.
# Usage: polish_audit.py <landing-url>
"""Polish evidence: tab order and focus visibility, phone touch targets, headings, hover-only captions."""
import sys, json
from playwright.sync_api import sync_playwright
U = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900}); pg.goto(U); pg.wait_for_timeout(4000)
    stops = []
    for _ in range(20):
        pg.keyboard.press("Tab")
        stops.append(pg.evaluate("""()=>{const e=document.activeElement,s=getComputedStyle(e);
          const ring=(s.outlineStyle!=='none'&&parseFloat(s.outlineWidth)>0)||s.boxShadow!=='none';
          return [e.tagName, (e.textContent||'').trim().slice(0,28), e.getAttribute('href')||'', ring?'RING':'no ring']}"""))
    for s in stops: print("TAB", s)
    print("H", pg.evaluate("[...document.querySelectorAll('h1,h2,h3,h4')].map(h=>h.tagName+':'+h.textContent.trim().slice(0,24)).join(' | ')"))
    print("SEL", pg.evaluate("getComputedStyle(document.body,'::selection').backgroundColor"))
    ph = b.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True); ph.goto(U); ph.wait_for_timeout(4000)
    print("PHONE targets <44px:", ph.evaluate("""()=>[...document.querySelectorAll('a,button')].filter(e=>e.offsetParent||getComputedStyle(e).position==='fixed').map(e=>{const r=e.getBoundingClientRect();return [e.textContent.trim().slice(0,20),Math.round(r.width),Math.round(r.height)]}).filter(x=>x[1]<44||x[2]<44)"""))
    print("PHONE captions:", ph.evaluate("[...document.querySelectorAll('.qc .cap')].map(c=>c.textContent)"))
    print("PHONE sticky nav covers footer?", ph.evaluate("""()=>{scrollTo(0,1e6);const n=document.querySelector('header nav').getBoundingClientRect(),f=document.querySelector('footer').getBoundingClientRect();return {navTop:Math.round(n.top),footBottom:Math.round(f.bottom)}}"""))
    b.close()
