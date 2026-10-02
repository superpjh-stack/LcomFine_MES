"""QA3 — 화면의 폼을 실제 브라우저로 열어 요약한다 (탐색용). uv run --with playwright python tools/e2e/explore.py <role> <path> [...]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from playwright.sync_api import sync_playwright
from lcomfine.app.settings import get_settings

BASE = "http://localhost:8023"
JS = """() => {
  const out = [];
  document.querySelectorAll('form').forEach(f => {
    const fields = [];
    Array.from(f.elements).forEach(e => {
      let d = e.tagName.toLowerCase() + (e.type ? ':' + e.type : '') + ' name=' + (e.name||'') ;
      if (e.required) d += ' *';
      if (e.hasAttribute('data-scan')) d += ' [scan]';
      if (e.tagName==='SELECT') d += ' opts=' + Array.from(e.options).slice(0,8).map(o=>o.value+'|'+o.textContent.trim()).join(';');
      if (e.tagName==='BUTTON') d += ' text=' + e.textContent.trim();
      if (e.type==='hidden') d += ' val=' + e.value;
      if (e.offsetParent===null && e.type!=='hidden') d += ' (hidden)';
      fields.push(d);
    });
    out.push((f.method||'get') + ' ' + f.getAttribute('action') + ' cls=' + f.className + '\\n    ' + fields.join('\\n    '));
  });
  const loose = Array.from(document.querySelectorAll('button')).filter(b=>!b.form && !b.closest('.hdr') && !b.closest('#popup-layer') && !b.classList.contains('menu-head')).map(b=>b.outerHTML.slice(0,140));
  const links = Array.from(document.querySelectorAll('main a, .content a, table a')).slice(0,30).map(a=>a.textContent.trim()+' -> '+a.getAttribute('href'));
  return {forms: out, links, loose, active: document.activeElement ? document.activeElement.outerHTML.slice(0,120) : '', body: document.body.className, sw: document.documentElement.scrollWidth, vw: window.innerWidth};
}"""

def main():
    role, paths = sys.argv[1], sys.argv[2:]
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(BASE + "/login")
        pg.fill("input[name=login_id]", role)
        pg.fill("input[name=password]", get_settings().seed_password)
        pg.press("input[name=password]", "Enter")
        pg.wait_for_load_state()
        print("after login:", pg.url)
        for path in paths:
            r = pg.goto(BASE + path)
            info = pg.evaluate(JS)
            print("=" * 20, path, r.status, "body=", info["body"], "sw/vw", info["sw"], info["vw"])
            print("active:", info["active"])
            for f in info["forms"]:
                if "/logout" in f: continue
                print("  FORM", f)
            for l in info["loose"]:
                print("  LOOSE-BUTTON", l)
            for l in info["links"]:
                print("  LINK", l)
        b.close()

main()
