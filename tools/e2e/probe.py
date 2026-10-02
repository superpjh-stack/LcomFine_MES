"""QA3 — 채널·출력물 브라우저 실측 (G-13 · G-14). 실제 브라우저(Playwright Chromium)로 재서 JSON 으로 낸다.

    uv run --with playwright python tools/e2e/probe.py [--world '<json>'] [--skip-board] [--out outputs/e2e/_probe.json]

`tools/check_security.py` 가 자기 임시 데이터의 번호를 `--world` 로 넘겨 부른다. 서버(8023)가 안 떠 있으면 띄우고 끝나면 내린다.
world 키(전부 선택): job_no · lot_no · print_roll · roll · shipment_no(승인됨) · probe_shipment_no(등록 · 롤 0) · probe_rolls[2](재고)

재는 것
  pop      POP 채널(현장 계정): 확대 치수 · 화면을 열면 스캔칸이 포커스를 잡는가 · 없는 번호 스캔 뒤 스캔칸이 남아 다음 스캔을 받는가
           · 알림이 떠 있는 동안의 스캔 · 알림을 닫은 뒤의 포커스 · (world) 바코드 한 번 = 한 건
  mobile   뷰포트 390px: LOT 추적·실적 현황의 문서 scrollWidth ≤ 뷰포트
  board    `?device=board` 가 조작 없이 다시 그려지는가 (갱신 시각이 바뀔 때까지 기다린다)
  outputs  출력물 5종: 인쇄용 화면 · 인라인 SVG · 외부 요청 0 · 캡처를 zbarimg 로 디코드 · 그 값을 스캔칸에 넣으면 열리는가
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import BASE, OUT, ROOT, Session, zbar  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

NOPE = "Q3-NOPE-0000"     # 어디에도 없는 번호


def server_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 — 안 떠 있다는 사실만 필요하다
        return False


def start_server():
    if server_up():
        return None
    p = subprocess.Popen(["uv", "run", "uvicorn", "lcomfine.app.main:app", "--app-dir", "src", "--port", "8023"],
                         cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if server_up():
            return p
        time.sleep(0.5)
    p.terminate()
    raise RuntimeError("포트 8023 서버가 뜨지 않는다")


def px(page, selector: str, prop: str = "fontSize"):
    return page.evaluate("""([sel, prop]) => { const e = document.querySelector(sel); if (!e) return null;
        return prop === 'height' ? e.getBoundingClientRect().height : parseFloat(getComputedStyle(e)[prop]); }""", [selector, prop])


def scan_state(s: Session) -> dict:
    return s.page.evaluate("""() => { const sc = document.querySelector('[data-scan]'); const a = document.activeElement;
        return {scan_present: !!sc, focus_on_scan: !!sc && a === sc, scan_value: sc ? sc.value : null,
                focus: a ? a.tagName + (a.name ? '[' + a.name + ']' : '') : ''}; }""")


# ─────────────────────────────────────────────────────────────────────────
def probe_pop(b, world: dict) -> dict:
    out: dict = {"screens": {}, "bad_scan": {}, "popup": {}}
    s = Session(b, "field", device="pop", viewport={"width": 1280, "height": 800})
    out["landing"] = s.login().replace(BASE, "")
    s.goto("/pop/work")
    out["body_class"] = s.body_class()
    out["size"] = {"body_font_px": px(s.page, "body"), "scan_input_h_px": px(s.page, "[data-scan]", "height"),
                   "scan_input_font_px": px(s.page, "[data-scan]"), "button_h_px": px(s.page, ".scan-box button", "height")}
    web = Session(b, "field")
    web.login()
    web.goto("/pop/work")
    out["size_web"] = {"body_font_px": px(web.page, "body"), "scan_input_h_px": px(web.page, "[data-scan]", "height"),
                       "button_h_px": px(web.page, ".scan-box button", "height")}
    web.close()
    s.shot("ch-pop-작업실적.png")

    # (1) 화면을 열면 스캔칸이 포커스를 잡는가 — 현장 계정이 여는 POP 채널 화면 중 스캔칸이 있는 것
    scan_screens = ["/pop/work", "/pop/roll-labels", "/mat/inspections", "/mat/lots", "/clr/records",
                    "/rll/finishing", "/rll/slitting", "/rll/history", "/qua/inspections", "/shp/shipments"]
    for path in scan_screens:
        st = s.goto(path)
        out["screens"][path] = {"http": st, "body": s.body_class(), **scan_state(s)}

    # (2) 없는 번호를 스캔(타이핑 + Enter)한 뒤: 화면에 스캔칸이 남는가 · 포커스 · 곧바로 친 다음 스캔 글자가 스캔칸에 들어가는가
    for path in ["/pop/work", "/pop/roll-labels", "/mat/inspections", "/mat/lots", "/rll/finishing", "/rll/slitting",
                 "/rll/history", "/qua/inspections", "/shp/shipments"]:
        s.goto(path)
        statuses: list[int] = []
        handler = lambda r: statuses.append(r.status) if r.request.is_navigation_request() else None  # noqa: E731
        s.page.on("response", handler)
        r = s.scan(NOPE)
        s.page.remove_listener("response", handler)
        st = scan_state(s)
        err_px = s.page.evaluate("""() => { const e = document.querySelector('.err.big, #scan-result p, .error-page h1, main h1, h1');
                                            return e ? parseFloat(getComputedStyle(e).fontSize) : null; }""")
        shown = NOPE in s.text() or "없는" in s.text()
        s.page.keyboard.type("NEXT123")            # 스캐너가 곧바로 다음 번호를 쏜다
        after = scan_state(s)
        out["bad_scan"][path] = {"focus_before": r["focus_on_scan"], "http": statuses[-1] if statuses else None,
                                 "scan_present": st["scan_present"], "focus_on_scan": st["focus_on_scan"],
                                 "message_shown": shown, "message_px": err_px, "popup": bool(s.popup()),
                                 "next_scan_received": after["scan_value"] == "NEXT123", "url": s.page.url.replace(BASE, "")}
        if path in ("/qua/inspections", "/shp/shipments"):
            s.shot(f"ch-pop-없는번호스캔{path.replace('/', '-')}.png")
    s.close()

    # (3) 알림 팝업 — 폼 POST 의 422 알림이 떠 있을 때 스캔 글자가 스캔칸에 가는가 / 「확인」으로 닫으면 포커스가 돌아오는가
    cases = [("qc", "/qua/inspections", "form#inspection-form", {"roll_no": NOPE, "result": "합격"}),
             ("field", "/shp/shipments", "form.form-grid[action='/shp/shipments']", {"job_no": NOPE, "ship_date": time.strftime("%Y-%m-%d")}),
             ("field", "/clr/records", "form.form-grid[action='/clr/records']", {"job_no": NOPE, "color_name": "(예시) Q3"})]
    for role, path, form, values in cases:
        s = Session(b, role, device="pop", viewport={"width": 1280, "height": 800})
        s.login()
        res: dict = {}
        for mode in ("type_while_open", "close_then_focus"):
            s.goto(path)
            for name, v in values.items():
                loc = s.page.locator(f"{form} [name='{name}']").first
                (loc.select_option(v) if loc.evaluate("e => e.tagName") == "SELECT" else loc.fill(v))
            sub = s.submit(form)
            pop = s.popup()
            res["popup_shown"] = bool(pop)
            res["popup_font_px"] = px(s.page, "#popup-body p")
            if not pop:
                res["note"] = f"422 알림이 안 뜸: {sub['chain']}"
                break
            if mode == "type_while_open":
                s.page.keyboard.type("ABC123")
                s.page.wait_for_timeout(200)
                st = scan_state(s)
                res["typed_while_popup_reaches_scan"] = st["scan_value"] == "ABC123"
                res["typed_value_in_scan"] = st["scan_value"]
            else:
                s.page.click("#popup-layer [data-popup-close]")
                s.page.wait_for_timeout(300)
                st = scan_state(s)
                res["focus_on_scan_after_close"] = st["focus_on_scan"]
                res["focus_after_close"] = st["focus"]
        out["popup"][path] = res
        s.close()

    # (4) 바코드 한 번 = 한 건 (world 가 있을 때) — 출하 롤 스캔
    ship, rolls = world.get("probe_shipment_no"), world.get("probe_rolls") or []
    if ship and len(rolls) >= 2:
        from lib import conn

        def shipped(no: str) -> int:
            return conn.q1("""select count(*) as n from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id
                               join shipment sh on sh.shipment_id = g.child_shipment_id
                               where r.roll_no = %s and sh.shipment_no = %s""", (no, ship))["n"]

        s = Session(b, "field", device="pop", viewport={"width": 1280, "height": 800})
        s.login()
        s.goto("/shp/shipments")
        one: dict = {"open_focus": scan_state(s)["focus_on_scan"]}
        s.scan(ship)                                   # 출하 LOT 을 스캔해 연다
        one["opened"] = s.page.locator(f"form.scan-box[action='/shp/shipments/{ship}/rolls']").count() == 1
        one["roll_scan_focus"] = scan_state(s)["focus_on_scan"]
        s.scan(rolls[0])                               # 롤 A: 한 번 스캔
        one["first_scan_rows"] = shipped(rolls[0])
        one["popup_after_first"] = bool(s.popup())
        s.scan(rolls[1])                               # 롤 B: 알림이 떠 있는 채로 곧바로 스캔
        one["second_scan_while_popup_rows"] = shipped(rolls[1])
        one["error_shown_for_lost_scan"] = bool(s.popup())
        s.shot("ch-pop-출하-연속스캔.png")
        if s.popup():
            s.close_popup()
        one["focus_on_scan_after_close"] = scan_state(s)["focus_on_scan"]
        if not scan_state(s)["focus_on_scan"]:
            s.page.locator("[data-scan]").click()
        s.scan(rolls[0])                               # 롤 A 를 다시: 422, 행 수 그대로
        one["rescan_rows"] = shipped(rolls[0])
        one["rescan_warn"] = bool(s.popup() and s.popup()["warn"])
        out["one_scan_one_row"] = one
        s.close()
    return out


OVERFLOW_JS = """() => {
  const vw = window.innerWidth, de = document.documentElement;
  const over = [];
  document.querySelectorAll('body *').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.width > 0 && r.right > vw + 1 && getComputedStyle(e).position !== 'fixed') over.push(e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).split(' ')[0] : ''));
  });
  const scrollers = [];
  document.querySelectorAll('body *').forEach(e => {
    const ox = getComputedStyle(e).overflowX;
    if ((ox === 'auto' || ox === 'scroll') && e.scrollWidth > e.clientWidth + 1) scrollers.push(e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).split(' ')[0] : ''));
  });
  return {vw, scrollWidth: de.scrollWidth, bodyScrollWidth: document.body.scrollWidth, over: Array.from(new Set(over)).slice(0, 8),
          over_count: over.length, inner_scrollers: Array.from(new Set(scrollers)).slice(0, 5), body: document.body.className};
}"""


def probe_mobile(b, world: dict) -> dict:
    out: dict = {"pages": {}}
    pages = ["/trc/trace", "/sta/summary", "/sta/summary/production", "/sta/summary/quality", "/sta/summary/delivery", "/sta/board"]
    if world.get("shipment_no"):
        pages += [f"/trc/trace/backward?no={world['shipment_no']}", f"/trc/trace?q={world['shipment_no'][:6]}"]
    if world.get("lot_no"):
        pages += [f"/trc/trace/forward?no={world['lot_no']}"]
    for label, device in (("mobile", "mobile"), ("web", None)):
        s = Session(b, "qc", device=device, viewport={"width": 390, "height": 844}, is_mobile=True)
        s.login()
        res = {}
        for path in pages:
            st = s.goto(path)
            m = s.page.evaluate(OVERFLOW_JS)
            m["http"] = st
            res[path] = m
            if label == "mobile":
                name = "ch-mobile390" + path.split("?")[0].replace("/", "-") + ".png"
                s.shot(name)
        out["pages"][label] = res
        s.close()
    # 로그인 화면도 390 에서
    s = Session(b, "qc", device="mobile", viewport={"width": 390, "height": 844}, is_mobile=True)
    s.page.goto(BASE + "/login?device=mobile")
    out["login"] = s.page.evaluate(OVERFLOW_JS)
    s.close()
    return out


def probe_board(b, world: dict, max_wait: int = 75) -> dict:
    """현황판 — 아무것도 누르지 않고 기다려서 갱신 시각이 바뀌는지 본다."""
    s = Session(b, "prod", device="board", viewport={"width": 1920, "height": 1080})
    out: dict = {"landing": s.login().replace(BASE, "")}
    loads: list[float] = []
    s.page.on("load", lambda _p: loads.append(time.time()))
    s.goto("/sta/board?device=board")
    out["body"] = s.body_class()
    out["meta_refresh"] = s.page.evaluate("(() => { const m = document.querySelector('meta[http-equiv=refresh]'); return m ? m.content : null; })()")
    # D-27: 새로고침 주기는 이제 <body data-refresh-seconds> 로 온다(app.js 가 읽는다). meta 는 noscript 대체물이라 스크립트가 켜진 브라우저에는 없다
    out["refresh_setting"] = s.page.evaluate("parseInt(document.body.dataset.refreshSeconds || '0', 10) || null")
    # 현황판 채널의 오류 화면(404)을 다른 탭에 같이 띄워 둔다 — 그 화면도 조작 없이 다시 그려지는가 (DEF-QA3-004 의 뿌리)
    ep = s.ctx.new_page()
    ep_loads: list[float] = []
    ep.on("load", lambda _p: ep_loads.append(time.time()))
    ep_resp = ep.goto(BASE + "/sta/board/none?device=board")
    ep_t0 = time.time()
    ep_first = len(ep_loads)
    err = {"status": ep_resp.status if ep_resp else 0, "body": ep.evaluate("document.body.className"),
           "refresh_setting": ep.evaluate("parseInt(document.body.dataset.refreshSeconds || '0', 10) || null")}
    out["menu_visible"] = s.page.evaluate("(() => { const e = document.querySelector('nav.side'); return !!e && getComputedStyle(e).display !== 'none'; })()")
    out["body_font_px"] = px(s.page, "body")
    first = s.page.inner_text("#refreshed-at")
    out["first_stamp"] = first
    s.shot("ch-board-처음.png")
    t0 = time.time()
    changed_at, stamp = None, first
    while time.time() - t0 < max_wait:
        s.page.wait_for_timeout(1000)
        try:
            stamp = s.page.inner_text("#refreshed-at")
        except Exception:  # noqa: BLE001 — 새로고침 순간에는 요소가 잠깐 없다
            continue
        if stamp != first:
            changed_at = time.time() - t0
            break
    while time.time() - ep_t0 < max_wait and len(ep_loads) <= ep_first:      # 오류 화면 탭이 스스로 다시 적재될 때까지
        ep.wait_for_timeout(500)
    err.update({"reloaded": len(ep_loads) > ep_first, "loads": len(ep_loads),
                "seconds_until_reload": round(ep_loads[ep_first] - ep_t0, 1) if len(ep_loads) > ep_first else None,
                "waited_seconds": round(time.time() - ep_t0, 1), "url_after": ep.url.replace(BASE, "")})
    out["error_page"] = err
    ep.close()
    out["second_stamp"] = stamp
    out["refreshed"] = changed_at is not None
    out["seconds_until_refresh"] = round(changed_at, 1) if changed_at else None
    out["waited_seconds"] = round(time.time() - t0, 1)
    out["url_after"] = s.page.url.replace(BASE, "")
    out["body_after"] = s.body_class()
    s.shot("ch-board-새로고침뒤.png")
    s.close()
    return out


def probe_outputs(b, world: dict) -> dict:
    """출력물 5종 — 인쇄용 화면 · 인라인 SVG 바코드 · 외부 요청 0 · zbarimg 디코드 · 스캔칸에 넣으면 열리는가."""
    out: dict = {}
    specs = [
        ("작업지시서", "prod", world.get("job_no"), "/job/orders/{no}/print", "/pop/work", None),   # 작업지시서 바코드는 POP 작업 실적에서 스캔한다
        ("원재료 LOT 라벨", "field", world.get("lot_no"), "/mat/lots/{no}/label", "/mat/lots", None),
        ("인쇄 롤 라벨", "field", world.get("print_roll"), "/pop/roll-labels/{no}/print", "/pop/roll-labels", None),
        ("롤 라벨", "field", world.get("roll"), "/rll/history/{no}/label", "/rll/history", None),
        ("COA", "admin", world.get("shipment_no"), "/shp/coa/{no}/print", "/shp/shipments", None),
    ]
    for name, role, no, url, scan_path, _ in specs:
        if not no:
            out[name] = {"skipped": "world 에 번호 없음"}
            continue
        s = Session(b, role, viewport={"width": 1280, "height": 900})
        s.login()
        n0 = len(s.requests)
        st = s.goto(url.format(no=no))
        s.page.wait_for_load_state("networkidle")
        reqs = s.requests[n0:]
        ext = [u for u in reqs if not u.startswith(BASE) and not u.startswith("data:") and not u.startswith("about:")]
        dom = s.page.evaluate("""() => ({svg: document.querySelectorAll('svg').length,
            img: Array.from(document.images).map(i => i.src).filter(u => !u.startsWith(location.origin) && !u.startsWith('data:')).length,
            ext_tags: Array.from(document.querySelectorAll('script[src],link[href],iframe[src]')).map(e => e.src || e.href).filter(u => !u.startsWith(location.origin)).length,
            print_btn: Array.from(document.querySelectorAll('button, a')).some(e => /인쇄/.test(e.textContent))})""")
        shot = f"ch-출력물-{name.replace(' ', '')}.png"
        s.shot(shot)
        codes = zbar(OUT / shot)
        # 인쇄 매체로 바꿔: 메뉴·헤더·버튼이 빠지고 바코드가 남는가
        s.page.emulate_media(media="print")
        pr = s.page.evaluate("""() => { const vis = sel => { const e = document.querySelector(sel); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0; };
            return {menu: vis('nav.side'), header: vis('header.hdr'), contract_panel: vis('aside.desc, .desc'), svg: vis('svg'),
                    buttons: Array.from(document.querySelectorAll('button, a.btn')).filter(e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0).length}; }""")
        pshot = f"ch-출력물-{name.replace(' ', '')}-인쇄매체.png"
        s.shot(pshot)
        pcodes = zbar(OUT / pshot)
        s.page.emulate_media(media="screen")
        # 디코드한 값을 스캔칸에 넣으면 그 LOT/롤이 열리는가
        value = codes[0].split(":", 1)[1] if codes else None
        opened = None
        if value:
            s.goto(scan_path)
            r = s.scan(value)
            body = s.text()
            opened = {"focus_on_scan": r["focus_on_scan"], "navigated": r["navigated"], "url": s.page.url.replace(BASE, ""),
                      "number_shown": value in body, "http_ok": "찾을 수 없습니다" not in body and "없는" not in body}
        out[name] = {"http": st, "number": no, "decoded": codes, "decoded_print_media": pcodes, "decode_ok": f"CODE-128:{no}" in codes,
                     "requests": len(reqs), "external_requests": ext[:3], "external_count": len(ext), **dom, "print_media": pr, "scan_opens": opened}
        s.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="{}")
    ap.add_argument("--skip-board", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(OUT / "_probe.json"))
    a = ap.parse_args()
    world = json.loads(a.world)
    OUT.mkdir(parents=True, exist_ok=True)
    srv = start_server()
    result: dict = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "world": world, "errors": {}}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            result["browser"] = f"Playwright Chromium {b.version} (headless)"
            parts = [("pop", probe_pop), ("mobile", probe_mobile), ("outputs", probe_outputs), ("board", probe_board)]
            for name, fn in parts:
                if a.only and name not in a.only.split(","):
                    continue
                if name == "board" and a.skip_board:
                    continue
                try:
                    result[name] = fn(b, world)
                except Exception as exc:  # noqa: BLE001 — 재지 못한 것은 재지 못했다고 적는다
                    result["errors"][name] = f"{type(exc).__name__}: {str(exc)[:300]}"
            b.close()
    finally:
        if srv is not None:
            srv.terminate()
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
