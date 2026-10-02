"""QA3 — G-22 브라우저 한 바퀴. 실제 브라우저에서 역할을 바꿔 로그인하며 한 Job 을 끝까지 조작한다.

    uv run --with playwright python tools/e2e/run_e2e.py            # 처음부터 끝까지 (먼저 Q3E- 잔여를 지운다)
    uv run --with playwright python tools/e2e/run_e2e.py 05 07      # 05~07 단계만 (상태는 outputs/e2e/_journal.json)
    uv run python tools/e2e/lib.py cleanup                          # E2E 가 만든 행 지우기

단계가 화면에서 막히면 **우회하지 않고 적은 뒤**(journal.finding), 다음 단계가 이어지도록 그 상태만 API 로 만든다.
그 단계의 `how` 는 `API 대체` 로 남는다. 캡처는 outputs/e2e/NN-단계명.png.

G-22 판정(재검 · 웨이브 D 뒤): 16단계 전부 PASS **이고** 우회 0(스캔칸을 손으로 누름 · 주소로 직접 엶 — `lib.BYPASSES`)
**이고** 유실 0(`lib.LOST_SCANS`) **이고** API 대체 0 일 때만 PASS. 우회가 한 번이라도 있으면 그 단계는 `결함(우회)` 이고 판정은 FAIL 이다.
끝에 `_journal.json` 의 `state.verdict` 와 표준 출력에 그 수를 적는다.
"""

from __future__ import annotations

import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from lib import BASE, BYPASSES, LOST_SCANS, MARK, OUT, PREFIX, SCANS, Journal, Session, cleanup, conn, get_settings, zbar  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

J = Journal(OUT / "_journal.json")
S = J.state


def api(role: str) -> httpx.Client:
    """API 대체용 — 화면이 부르는 것과 같은 엔드포인트를 JSON 으로 부른다."""
    c = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)
    r = c.post("/login", data={"login_id": role, "password": get_settings().seed_password})
    assert r.status_code == 303, r.status_code
    return c


def fill(page, form: str, values: dict) -> None:
    for name, v in values.items():
        loc = page.locator(f"{form} [name='{name}']").first
        tag = loc.evaluate("e => e.tagName")
        if tag == "SELECT":
            loc.select_option(str(v))
        else:
            loc.fill(str(v))


def ok_popup(res: dict, must: str = "") -> bool:
    pop = res.get("popup")
    return bool(pop) and not pop["warn"] and (must in pop["body"])


# ─────────────────────────────────────────────────────────────────────────
def step01_login(b):
    s = Session(b, "admin")
    url = s.login(shot_before="01-로그인.png")
    ok = url.rstrip("/") == BASE and "관리자" in s.text()
    s.shot("01-메인-관리자.png")
    J.step("01", "로그인", "admin", "로그인 화면에 ID·비밀번호를 치고 「로그인」 클릭", "PASS" if ok else "FAIL",
           ["01-로그인.png", "01-메인-관리자.png"], note=f"도착 {url} · body {s.body_class()}")
    s.close()


def step02_master(b):
    """기준정보 — 관리자: 품목 3(제품 1 · 원재료 2) · 고객 1 · 공정 1 · 설비 1 · 불량코드 1."""
    s = Session(b, "admin")
    s.login()
    made, bad = [], []
    plan = [
        ("/bas/items", {"item_code": f"{PREFIX}FG-01", "item_name": f"제품 {MARK}", "item_type": "제품", "spec": "(예시)", "unit": "m"}),
        ("/bas/items", {"item_code": f"{PREFIX}RM-01", "item_name": f"원단 1 {MARK}", "item_type": "원재료", "unit": "m"}),
        ("/bas/items", {"item_code": f"{PREFIX}RM-02", "item_name": f"원단 2 {MARK}", "item_type": "원재료", "unit": "m"}),
        ("/bas/customers", {"customer_code": f"{PREFIX}CU-01", "customer_name": f"고객 {MARK}"}),
        ("/bas/processes", {"process_code": f"{PREFIX}PR-01", "process_name": f"인쇄 {MARK}", "process_type": "인쇄", "sort_no": "91"}),
        ("/bas/equipment", {"equipment_code": f"{PREFIX}EQ-01", "equipment_name": f"인쇄기 {MARK}"}),
        ("/bas/defect-codes", {"defect_code": f"{PREFIX}DF-01", "defect_name": f"색차 {MARK}", "defect_group": "(예시)"}),
    ]
    shots = []
    for path, vals in plan:
        s.goto(path)
        form = f"form.form-grid[action='{path}']"
        fill(s.page, form, vals)
        res = s.submit(form)
        code = next(iter(vals.values()))
        row = code in s.text()
        if ok_popup(res) and row:
            made.append(code)
        else:
            bad.append(f"{path} {code}: {res}")
        if path != "/bas/items" or code.endswith("FG-01"):
            shots.append(s.shot(f"02-기준정보-{path.split('/')[-1]}.png"))
        s.close_popup()
    # 설비에 공정을 붙여 수정 (수정 화면이 실제로 열리고 저장되는가)
    s.goto("/bas/equipment")
    s.page.locator(f"tr:has-text('{PREFIX}EQ-01') a:has-text('수정')").click()
    s.page.wait_for_load_state()
    edit_form = "form.form-grid"
    opt = s.page.locator(f"{edit_form} select[name=process_id] option", has_text=f"{PREFIX}PR-01").get_attribute("value")
    s.page.locator(f"{edit_form} select[name=process_id]").select_option(opt)
    res = s.submit(edit_form)
    edit_ok = ok_popup(res)
    shots.append(s.shot("02-기준정보-설비수정.png"))
    s.close_popup()
    # 중복 코드 422 가 알림으로 보이는가
    s.goto("/bas/customers")
    fill(s.page, "form.form-grid[action='/bas/customers']", {"customer_code": f"{PREFIX}CU-01", "customer_name": f"중복 {MARK}"})
    res = s.submit("form.form-grid[action='/bas/customers']")
    dup_ok = bool(res["popup"]) and res["popup"]["warn"]
    shots.append(s.shot("02-기준정보-중복422.png"))
    ok = not bad and edit_ok and dup_ok
    for x in bad:
        J.finding("02", x)
    if not dup_ok:
        J.finding("02", f"중복 코드 등록에 경고 알림이 안 뜸: {res}")
    J.step("02", "기준정보 등록", "admin", "품목 3 · 고객 · 공정 · 설비 · 불량코드 등록, 설비 수정, 중복 코드 재등록",
           "PASS" if ok else "FAIL", shots, note=f"등록 {len(made)}/7 · 수정 {'OK' if edit_ok else 'X'} · 중복 422 알림 {'OK' if dup_ok else 'X'} · 콘솔 {len(s.console)}")
    s.close()


def step03_print_std(b):
    """인쇄 기준 — 생산: 판사양 · 아니록스 · 잉크조성(조성 행 2)."""
    s = Session(b, "prod")
    s.login()
    shots, bad = [], []
    s.goto("/prt/plates")
    form = "form.form-grid[action='/prt/plates']"
    item_opt = s.page.locator(f"{form} select[name=item_id] option", has_text=f"{PREFIX}FG-01").get_attribute("value")
    fill(s.page, form, {"plate_code": f"{PREFIX}PL-01", "plate_name": f"판 {MARK}", "item_id": item_opt, "color_count": "4", "spec_note": "(예시)"})
    res = s.submit(form)
    if not (ok_popup(res) and f"{PREFIX}PL-01" in s.text()):
        bad.append(f"판사양: {res}")
    shots.append(s.shot("03-인쇄기준-판사양.png")); s.close_popup()

    s.goto("/prt/anilox")
    form = "form.form-grid[action='/prt/anilox']"
    fill(s.page, form, {"anilox_code": f"{PREFIX}AN-01", "anilox_name": f"아니록스 {MARK}", "line_count": "400", "cell_volume": "5"})
    res = s.submit(form)
    if not (ok_popup(res) and f"{PREFIX}AN-01" in s.text()):
        bad.append(f"아니록스: {res}")
    shots.append(s.shot("03-인쇄기준-아니록스.png")); s.close_popup()

    s.goto("/prt/inks")
    form = "form.form-grid[action='/prt/inks']"
    fill(s.page, form, {"ink_code": f"{PREFIX}INK-01", "ink_name": f"잉크 {MARK}", "color_name": "청 (예시)",
                        "target_l": "50", "target_a": "-10", "target_b": "-30"})
    comp, ratio = s.page.locator(f"{form} [name=component_name]"), s.page.locator(f"{form} [name=ratio_pct]")
    comp.nth(0).fill("안료 (예시)"); ratio.nth(0).fill("60")
    comp.nth(1).fill("용제 (예시)"); ratio.nth(1).fill("40")
    res = s.submit(form)
    if not (ok_popup(res) and f"{PREFIX}INK-01" in s.text()):
        bad.append(f"잉크조성: {res}")
    shots.append(s.shot("03-인쇄기준-잉크조성.png")); s.close_popup()
    for x in bad:
        J.finding("03", x)
    J.step("03", "인쇄 기준 등록", "prod", "판사양 · 아니록스 · 잉크조성(조성 2행) 등록", "PASS" if not bad else "FAIL", shots,
           note=f"실패 {len(bad)} · 콘솔 {len(s.console)}")
    s.close()


def step04_job(b):
    """작업지시 — 생산: 등록 → Job-Lot-Roll 매핑 → 작업지시서 출력(바코드 디코드)."""
    s = Session(b, "prod")
    s.login()
    shots, bad = [], []
    s.goto("/job/orders")
    form = "form.form-grid[action='/job/orders']"

    def opt(name, text):
        return s.page.locator(f"{form} select[name={name}] option", has_text=text).first.get_attribute("value")

    fill(s.page, form, {"item_id": opt("item_id", f"{PREFIX}FG-01"), "customer_id": opt("customer_id", f"{PREFIX}CU-01"),
                        "plate_spec_id": opt("plate_spec_id", f"{PREFIX}PL-01"), "anilox_id": opt("anilox_id", f"{PREFIX}AN-01"),
                        "ink_formula_id": opt("ink_formula_id", f"{PREFIX}INK-01"), "equipment_id": opt("equipment_id", f"{PREFIX}EQ-01"),
                        "order_qty": "3000", "qty_unit": "m", "due_date": (date.today() + timedelta(days=7)).isoformat(),
                        "note": f"E2E {MARK}"})
    res = s.submit(form)
    row = conn.q1("select job_no from job j join item i on i.item_id = j.item_id where i.item_code = %s order by job_id desc", (f"{PREFIX}FG-01",))
    job_no = row["job_no"] if row else None
    S["job_no"] = job_no
    if not (ok_popup(res) and job_no and job_no in s.text()):
        bad.append(f"작업지시 등록: {res} · DB job_no={job_no}")
    shots.append(s.shot("04-작업지시-등록.png")); s.close_popup()
    J.save()
    if not job_no:
        J.step("04", "작업지시 등록·매핑·작업지시서", "prod", "작업지시 등록", "FAIL", shots, note="Job 이 만들어지지 않음")
        s.close()
        return

    # Job-Lot-Roll 매핑
    s.goto("/job/mapping")
    s.page.fill("form.search-form input[name=no]", job_no)
    with s.page.expect_navigation():
        s.page.click("form.search-form button[type=submit]")
    S["mapping_forms"] = s.page.evaluate("""() => Array.from(document.forms).map(f => (f.method + ' ' + f.getAttribute('action') + ': ' +
        Array.from(f.elements).map(e => e.tagName + ':' + (e.name || e.textContent.trim()) + (e.disabled ? '(disabled)' : '')).join(', ')))""")
    mform = "form[action='/job/mapping'][method=post]"
    if s.page.locator(mform).count():
        vals = {}
        for name, v in (("planned_roll_count", "2"), ("planned_length_m", "3000"), ("note", f"E2E {MARK}")):
            if s.page.locator(f"{mform} [name={name}]").count():
                vals[name] = v
        fill(s.page, mform, vals)
        res = s.submit(mform)
        lot = conn.q1("select lot_no from job_lot l join job j on j.job_id = l.job_id where j.job_no = %s order by job_lot_id desc", (job_no,))
        S["job_lot_no"] = lot["lot_no"] if lot else None
        if not (ok_popup(res) and lot and lot["lot_no"] in s.text()):
            bad.append(f"매핑 등록: {res} · lot={lot}")
    else:
        bad.append("매핑 등록 폼이 화면에 없음")
    shots.append(s.shot("04-작업지시-매핑.png")); s.close_popup()

    # 작업지시서 출력
    st = s.goto(f"/job/orders/{job_no}/print")
    ext = [u for u in s.requests if not u.startswith(BASE) and not u.startswith("data:")]
    shot = s.shot("04-작업지시서.png")
    shots.append(shot)
    codes = zbar(OUT / shot)
    S["job_barcode"] = codes
    svg = s.page.locator("svg").count()
    if st != 200 or f"CODE-128:{job_no}" not in codes:
        bad.append(f"작업지시서: HTTP {st} · 디코드 {codes}")
    for x in bad:
        J.finding("04", x)
    J.step("04", "작업지시 등록·매핑·작업지시서", "prod", "작업지시 등록 → Job 번호로 매핑 화면 열어 생산 LOT 등록 → 작업지시서 출력",
           "PASS" if not bad else "FAIL", shots,
           note=f"Job {job_no} · 생산 LOT {S.get('job_lot_no')} · 작업지시서 바코드 디코드 {codes} · SVG {svg} · 외부 요청 {len(ext)}")
    s.close()


FORMS_JS = """() => Array.from(document.forms).filter(f => f.getAttribute('action') !== '/logout').map(f => (f.method + ' ' + f.getAttribute('action') + ' #' + f.id + ': ' +
    Array.from(f.elements).map(e => e.tagName.toLowerCase() + ':' + (e.name || '') + (e.tagName === 'BUTTON' ? '[' + e.textContent.trim() + ']' : '') + (e.type === 'hidden' ? '=' + e.value : '') + (e.disabled ? '(disabled)' : '')).join(', ')))"""


def forms(s) -> list[str]:
    return s.page.evaluate(FORMS_JS)


def lots_of(code: str) -> list[str]:
    return [r["lot_no"] for r in conn.q("""select lot_no from material_lot l join item i on i.item_id = l.item_id
                                            where i.item_code = %s order by material_lot_id""", (code,))]


def step05_receipt(b):
    """자재 입고 — 현장(POP 채널): 원재료 LOT 2개 입고 + LOT 라벨."""
    s = Session(b, "field", device="pop", viewport={"width": 1280, "height": 800})
    url = s.login()
    S["pop_login_landing"] = url
    shots, bad = [], []
    shots.append(s.shot("05-POP-로그인직후.png"))
    s.goto("/mat/receipts")
    cls = s.body_class()
    if "ch-pop" not in cls:
        bad.append(f"POP 로 로그인했는데 입고 화면이 {cls}")
    form = "form.form-grid[action='/mat/receipts']"
    for i, code in enumerate((f"{PREFIX}RM-01", f"{PREFIX}RM-02"), 1):
        fill(s.page, form, {"item_code": code, "supplier_name": f"공급처 {MARK}", "supplier_lot_no": f"SUP-{i} (예시)",
                            "received_qty": "5000", "qty_unit": "m", "note": f"E2E {MARK}"})
        res = s.submit(form)
        got = lots_of(code)
        if not (got and res["popup"] and not res["popup"]["warn"] and got[-1] in s.text()):
            bad.append(f"입고 {code}: {res} · DB {got}")
        if i == 2:
            shots.append(s.shot("05-입고-등록.png"))
        s.close_popup()
        s.goto("/mat/receipts")
    lot1, lot2 = (lots_of(f"{PREFIX}RM-01") or [None])[-1], (lots_of(f"{PREFIX}RM-02") or [None])[-1]
    S["lot1"], S["lot2"] = lot1, lot2
    J.save()
    # 원재료 LOT 라벨 (출력물 2/5)
    if lot1:
        s.page.locator(f"tr:has-text('{lot1}') a:has-text('라벨')").first.click()
        s.page.wait_for_load_state()
        n0 = len(s.requests)
        shot = s.shot("05-원재료LOT-라벨.png"); shots.append(shot)
        codes = zbar(OUT / shot)
        S["lot_label_barcode"] = codes
        if f"CODE-128:{lot1}" not in codes:
            bad.append(f"원재료 LOT 라벨 디코드 {codes} ≠ {lot1}")
    for x in bad:
        J.finding("05", x)
    J.step("05", "자재 입고", "field (POP)", "POP 채널로 로그인 → 입고 2건 등록 → 원재료 LOT 라벨 열기", "PASS" if not bad else "FAIL", shots,
           note=f"LOT① {lot1} · LOT② {lot2} · 라벨 디코드 {S.get('lot_label_barcode')} · 로그인 뒤 도착 {url} · body {cls}")
    s.close()


def step06_incoming_inspection(b):
    """입고검사 — 품질: LOT 스캔 → 합격. (현장 계정에는 판정 버튼이 어떻게 보이는지도 본다)"""
    shots, bad = [], []
    # 현장 계정: 입고검사는 품질만 (괄호 권한)
    f = Session(b, "field", device="pop")
    f.login()
    f.goto(f"/mat/inspections?no={S['lot1']}")
    S["insp_forms_field"] = forms(f)
    shots.append(f.shot("06-입고검사-현장계정.png"))
    f.close()

    s = Session(b, "qc")
    s.login()
    s.goto("/mat/inspections")
    for i, lot in enumerate((S["lot1"], S["lot2"]), 1):
        r = s.scan(lot)                      # 스캔칸에 포커스가 있어야 한다
        if not r["focus_on_scan"]:
            bad.append(f"입고검사 화면이 열렸을 때 포커스가 스캔칸이 아님: {r['focus']}")
            s.bypass_goto(f"06 입고검사 LOT {i}", f"/mat/inspections?no={lot}")
        form = "form.form-grid[action='/mat/inspections']"
        if not s.page.locator(form).count():
            bad.append(f"LOT {lot} 스캔 뒤 판정 폼이 안 열림 ({r})")
            continue
        s.page.fill(f"{form} [name=note]", f"E2E {MARK}")
        if i == 1:
            shots.append(s.shot("06-입고검사-스캔.png"))
        res = s.submit(form, "합격")
        st = conn.q1("select insp_status from material_lot where lot_no = %s", (lot,))["insp_status"]
        if st != "합격" or not res["popup"] or res["popup"]["warn"]:
            bad.append(f"LOT {lot} 판정: DB {st} · {res}")
        if i == 2:
            shots.append(s.shot("06-입고검사-합격.png"))
        s.close_popup()
        S[f"insp_focus_after_popup_{i}"] = s.active()["html"]
    for x in bad:
        J.finding("06", x)
    J.step("06", "입고검사", "qc", "LOT 번호를 스캔칸에 타이핑+Enter → 판정 폼 → 「합격」 클릭 ×2", "PASS" if not bad else "FAIL", shots,
           note=f"두 LOT 합격 · 알림 닫은 뒤 포커스 {S.get('insp_focus_after_popup_2')}")
    s.close()


def step07_color(b):
    """조색 기록 — 품질: 조색 기록 등록 + 배합비."""
    s = Session(b, "qc")
    s.login()
    shots, bad = [], []
    s.goto("/clr/records")
    form = "form.form-grid[action='/clr/records']"
    fill(s.page, form, {"job_no": S["job_no"], "color_name": "청 (예시) Q3", "color_l": "50.5", "color_a": "-9.8", "color_b": "-29.5",
                        "ink_code": f"{PREFIX}INK-01", "note": f"E2E {MARK}"})
    res = s.submit(form)
    rec = conn.q1("select color_record_id from color_record c join job j on j.job_id = c.job_id where j.job_no = %s", (S["job_no"],))
    if not (rec and res["popup"] and not res["popup"]["warn"]):
        bad.append(f"조색 기록 등록: {res} · DB {rec}")
    shots.append(s.shot("07-조색-등록.png")); s.close_popup()
    S["clr_forms"] = forms(s)
    S["clr_links"] = s.page.evaluate("() => Array.from(document.querySelectorAll('table a, .panel a')).map(a => a.textContent.trim() + ' -> ' + a.getAttribute('href')).slice(0, 12)")
    J.save()
    if rec:
        rid = rec["color_record_id"]
        mix = f"form[action='/clr/records/{rid}/mix']"
        if not s.page.locator(mix).count():
            # 배합비 폼이 목록 화면에 없으면 「수정」/「배합비」 링크로 연다
            link = s.page.locator(f"a[href*='edit={rid}']").first
            if link.count():
                link.click(); s.page.wait_for_load_state()
        if s.page.locator(mix).count():
            comp, ratio = s.page.locator(f"{mix} [name=component_name]"), s.page.locator(f"{mix} [name=ratio_pct]")
            comp.nth(0).fill("안료 (예시)"); ratio.nth(0).fill("55")
            comp.nth(1).fill("용제 (예시)"); ratio.nth(1).fill("45")
            res = s.submit(mix)
            n = conn.q1("select count(*) as n from color_record_mix where color_record_id = %s", (rid,))["n"]
            if n != 2 or not res["popup"] or res["popup"]["warn"]:
                bad.append(f"배합비: DB {n}행 · {res}")
            shots.append(s.shot("07-조색-배합비.png")); s.close_popup()
        else:
            bad.append("배합비 폼을 화면에서 찾지 못함")
            S["clr_forms_after"] = forms(s)
    for x in bad:
        J.finding("07", x)
    J.step("07", "조색 기록", "qc", "조색 기록 등록(Job·색·Lab·기준 잉크) → 배합비 2행(합 100)", "PASS" if not bad else "FAIL", shots,
           note=f"실패 {len(bad)}")
    s.close()


def step08_print(b):
    """POP 인쇄 ×2 — 현장(POP): 작업지시서 스캔 → 작업 시작 → 자재 투입 스캔 → 종료 → 인쇄 롤 + 라벨."""
    s = Session(b, "field", device="pop", viewport={"width": 1280, "height": 800})
    s.login()
    shots, bad, obs = [], [], {}
    rolls = []
    for n, lots in ((1, [S["lot1"]]), (2, [S["lot1"], S["lot2"]])):
        s.goto("/pop/work")
        if n == 1:
            obs["pop_font_px"] = s.page.evaluate("parseFloat(getComputedStyle(document.body).fontSize)")
            obs["scan_h_px"] = s.page.evaluate("document.querySelector('[data-scan]').getBoundingClientRect().height")
            obs["btn_h_px"] = s.page.evaluate("document.querySelector('.scan-box button').getBoundingClientRect().height")
        r = s.scan(S["job_no"])                         # 작업지시서 바코드
        if not r["focus_on_scan"]:
            bad.append(f"작업 실적 화면: 포커스가 스캔칸이 아님 ({r['focus']})")
            s.bypass_goto(f"08 작업지시서 스캔 {n}", f"/pop/work?no={S['job_no']}")
        if "ch-pop" not in s.body_class():
            bad.append(f"스캔 뒤 화면이 {s.body_class()} (POP 유지 안 됨) url={s.page.url}")
        start = "form[action='/pop/work/start']"
        if not s.page.locator(start).count():
            bad.append(f"Job 스캔 뒤 작업 시작 폼 없음: {r}")
            break
        s.page.locator(f"{start} [name=lot_no]").select_option(S["job_lot_no"])
        if n == 1:
            shots.append(s.shot("08-POP-작업지시서스캔.png"))
        res = s.submit(start)
        w = conn.q1("""select work_result_id from work_result w join job j on j.job_id = w.job_id
                        where j.job_no = %s and w.status = '진행' order by work_result_id desc""", (S["job_no"],))
        if not w:
            bad.append(f"작업 시작: 진행 실적 없음 · {res}")
            break
        wid = w["work_result_id"]
        if n == 1:
            shots.append(s.shot("08-POP-작업시작.png"))
        obs[f"start_popup_{n}"] = res["popup"]
        # 알림을 닫지 않고 「자재 투입」으로 — 사람이 하듯 알림을 닫고 링크를 누른다
        s.close_popup()
        s.page.locator(f".work-card:has-text('실적 {wid}') a:has-text('자재 투입')").click()
        s.page.wait_for_load_state()
        if n == 1:
            # 오류 스캔: 없는 LOT → 큰 글씨 + 다음 스캔을 막지 않는가
            r = s.scan("NOPE-0000")
            obs["bad_scan"] = {"focus_on_scan": r["focus_on_scan"], "popup": s.popup(), "url": s.page.url,
                               "banner": s.page.evaluate("(() => { const e = document.querySelector('.scan-result'); return e ? {text: e.innerText.trim().slice(0, 120), px: parseFloat(getComputedStyle(e).fontSize)} : null; })()"),
                               "active_after": s.active()["html"]}
            shots.append(s.shot("08-POP-없는LOT스캔-422.png"))
            # 알림을 닫지 않고 곧바로 다음 스캔 (스캐너는 기다려 주지 않는다)
        for lot in lots:
            a = s.active()
            r = s.scan(lot)
            k = conn.q1("""select count(*) as n from material_input mi join material_lot l on l.material_lot_id = mi.material_lot_id
                            where mi.work_result_id = %s and l.lot_no = %s""", (wid, lot))["n"]
            if k != 1:
                bad.append(f"실적 {wid} 투입 스캔 {lot}: DB {k}건 (포커스 {a['html']} · {r})")
                LOST_SCANS.append({"where": f"08 자재 투입 실적 {wid}", "value": lot})
                # API 대체 없이 한 번 더: 스캔칸을 눌러 포커스를 주고 다시
                s.close_popup()
                s.bypass_click_scan(f"08 자재 투입 {lot}")
                r = s.scan(lot)
        if n == 2:
            # 같은 LOT 중복 스캔 → 422, 건수 그대로
            r = s.scan(S["lot2"])
            k = conn.q1("select count(*) as n from material_input where work_result_id = %s", (wid,))["n"]
            obs["dup_scan"] = {"count_after": k, "popup": s.popup(), "focus_on_scan_before": r["focus_on_scan"]}
            if k != 2:
                bad.append(f"중복 스캔 뒤 투입 {k}건 (기대 2)")
            shots.append(s.shot("08-POP-자재투입스캔.png"))
        s.close_popup()
        # 작업 실적으로 돌아가 종료
        s.page.locator("a:has-text('작업 실적으로')").click()
        s.page.wait_for_load_state()
        fin = f"form[action='/pop/work/{wid}/finish']"
        fill(s.page, fin, {"output_qty": "1500", "length_m": "1500", "width_mm": "600"})
        res = s.submit(fin)
        roll = conn.q1("select roll_no from roll where work_result_id = %s", (wid,))
        if not roll:
            bad.append(f"작업 종료: 롤 없음 · {res}")
            break
        rolls.append(roll["roll_no"])
        obs[f"finish_popup_{n}"] = res["popup"]
        shots.append(s.shot(f"08-POP-작업종료-인쇄롤{n}.png"))
        s.close_popup()
        # 인쇄 롤 라벨 (출력물 3/5)
        s.goto(f"/pop/roll-labels/{roll['roll_no']}/print")
        shot = s.shot(f"08-인쇄롤{n}-라벨.png"); shots.append(shot)
        codes = zbar(OUT / shot)
        obs[f"print_label_{n}"] = codes
        if f"CODE-128:{roll['roll_no']}" not in codes:
            bad.append(f"인쇄 롤 라벨 디코드 {codes} ≠ {roll['roll_no']}")
    S["print_rolls"] = rolls
    S["pop_obs"] = obs
    S["pop_console"] = s.console[:10]
    for x in bad:
        J.finding("08", x)
    J.step("08", "POP 인쇄 ×2", "field (POP)", "작업지시서 스캔 → 작업 시작 → 자재 투입 스캔(롤1: LOT① / 롤2: LOT①②) → 작업 종료 → 인쇄 롤 + 라벨",
           "PASS" if (not bad and len(rolls) == 2) else "FAIL", shots,
           note=f"인쇄 롤 {rolls} · 없는 LOT 스캔 {obs.get('bad_scan')} · 중복 스캔 {obs.get('dup_scan')}")
    s.close()



def roll_state(no: str) -> str:
    r = conn.q1("select s.state from v_roll_state s join roll r on r.roll_id = s.roll_id where r.roll_no = %s", (no,))
    return r["state"] if r else "없음"


def step09_splice(b):
    """후가공 splice (2→1) — 생산(POP): 인쇄 롤 2개 스캔 → splice 등록 → 후가공 롤 + 라벨."""
    s = Session(b, "prod", device="pop", viewport={"width": 1280, "height": 800})
    s.login()
    shots, bad = [], []
    s.goto("/rll/finishing")
    r1, r2 = S["print_rolls"]
    # D-208: 후가공 롤의 Job 은 글자 입력칸이 아니다 — 부모들의 Job 이 다를 때만 **선택칸**이 나온다(한 Job 흐름에서는 없다)
    for i, no in enumerate((r1, r2)):
        r = s.scan(no)
        if not r["focus_on_scan"]:
            bad.append(f"후가공 화면 스캔 {i + 1}번째: 포커스가 스캔칸이 아님 ({r['focus']})")
            s.bypass_click_scan(f"09 후가공 부모 롤 {i + 1}"); s.scan(no)
    pending = s.page.locator(".pending-rolls li").count()
    if pending != 2:
        bad.append(f"스캔 2번 뒤 쌓인 롤 {pending}개")
    shots.append(s.shot("09-후가공-롤2개스캔.png"))
    form = "form#finish-form"
    S["finishing_job_field"] = s.page.evaluate("""() => { const e = document.querySelector("form#finish-form [name=job_no]");
        return e ? e.tagName.toLowerCase() : "없음 (부모 롤이 전부 같은 Job)"; }""")
    if S["finishing_job_field"] == "input":
        bad.append("후가공 화면의 Job 칸이 글자 입력칸이다 (D-208 은 선택칸)")
    fill(s.page, form, {"length_m": "3000", "width_mm": "600"})
    res = s.submit(form, "splice")
    row = conn.q1("""select c.roll_no from roll_genealogy g join roll c on c.roll_id = g.child_roll_id join roll p on p.roll_id = g.parent_roll_id
                      where p.roll_no = %s and g.relation = 'splice'""", (r1,))
    fin = row["roll_no"] if row else None
    S["finishing_roll"] = fin
    if not fin or not res["popup"] or res["popup"]["warn"]:
        bad.append(f"splice 등록: {res} · DB {fin}")
    shots.append(s.shot("09-후가공-splice등록.png")); s.close_popup()
    if fin:
        # 소진된 부모 롤을 다시 스캔 → 422, 다음 스캔 가능
        s.goto("/rll/finishing")
        r = s.scan(r1)
        S["splice_reuse"] = {"popup": s.popup(), "banner": s.page.evaluate("(() => { const e = document.querySelector('#scan-result'); return e ? e.innerText.trim().slice(0, 100) : null; })()"),
                             "status_class": s.body_class(), "scan_present": s.page.locator("[data-scan]").count(), "active": s.active()["html"]}
        shots.append(s.shot("09-후가공-소진롤재스캔-422.png"))
        if not s.page.locator("[data-scan]").count():
            bad.append("소진 롤 재스캔 뒤 스캔칸이 사라짐")
    for x in bad:
        J.finding("09", x)
    J.step("09", "후가공 splice (2→1)", "prod (POP)", "인쇄 롤 2개를 차례로 스캔 → 「splice 등록」 → 후가공 롤. 소진된 롤 재스캔 422",
           "PASS" if not bad else "FAIL", shots, note=f"후가공 롤 {fin} · 부모 상태 {roll_state(r1)}/{roll_state(r2)} · 재스캔 {S.get('splice_reuse')}")
    s.close()


def step10_slit(b):
    """슬리팅 (1→3) — 현장(POP): 후가공 롤 스캔 → 3분할 → 라벨 3장 → 롤 이력."""
    s = Session(b, "field", device="pop", viewport={"width": 1280, "height": 800})
    s.login()
    shots, bad = [], []
    s.goto("/rll/slitting")
    r = s.scan(S["finishing_roll"])
    if not r["focus_on_scan"]:
        bad.append(f"슬리팅 화면: 포커스가 스캔칸이 아님 ({r['focus']})")
        s.bypass_goto("10 슬리팅 부모 롤", f"/rll/slitting?no={S['finishing_roll']}&device=pop")
    form = "form#slit-form"
    if not s.page.locator(form).count():
        bad.append(f"롤 스캔 뒤 분할 폼 없음 {r}")
    else:
        fill(s.page, form, {"count": "3", "widths_mm": "200,200,200"})
        shots.append(s.shot("10-슬리팅-스캔.png"))
        res = s.submit(form)
        rows = conn.q("""select c.roll_no from roll_genealogy g join roll c on c.roll_id = g.child_roll_id join roll p on p.roll_id = g.parent_roll_id
                          where p.roll_no = %s and g.relation = '슬리팅' order by c.roll_id""", (S["finishing_roll"],))
        slit = [x["roll_no"] for x in rows]
        S["slit_rolls"] = slit
        if len(slit) != 3 or not res["popup"] or res["popup"]["warn"]:
            bad.append(f"슬리팅 등록: {res} · DB {slit}")
        s.close_popup()
        shot = s.shot("10-슬리팅-라벨3장.png"); shots.append(shot)
        codes = zbar(OUT / shot)
        S["slit_label_barcodes"] = codes
        miss = [x for x in slit if f"CODE-128:{x}" not in codes]
        if miss:
            bad.append(f"슬리팅 화면의 라벨에서 디코드 안 된 롤 {miss} (읽힌 것 {codes})")
        # 롤 라벨 (출력물 4/5) — 단독 인쇄 화면
        if slit:
            s.goto(f"/rll/history/{slit[0]}/label")
            shot = s.shot("10-롤-라벨.png"); shots.append(shot)
            codes = zbar(OUT / shot)
            S["roll_label_barcode"] = codes
            if f"CODE-128:{slit[0]}" not in codes:
                bad.append(f"롤 라벨 디코드 {codes} ≠ {slit[0]}")
            # 그 바코드 값을 롤 이력 스캔칸에 넣으면 그 롤이 열리는가
            s.goto("/rll/history")
            r = s.scan(codes[0].split(":", 1)[1] if codes else slit[0])
            opened = slit[0] in s.text() and S["finishing_roll"] in s.text()
            if not (r["focus_on_scan"] and opened):
                bad.append(f"롤 이력 스캔: {r} · 열림 {opened}")
            shots.append(s.shot("10-롤이력.png"))
    for x in bad:
        J.finding("10", x)
    J.step("10", "슬리팅 (1→3)", "field (POP)", "후가공 롤 스캔 → 분할 수 3 → 「슬리팅 분할 등록」 → 라벨 3장 → 라벨 바코드 값을 롤 이력 스캔칸에",
           "PASS" if not bad else "FAIL", shots, note=f"슬리팅 롤 {S.get('slit_rolls')} · 라벨 디코드 {S.get('slit_label_barcodes')}")
    s.close()


def step11_quality(b):
    """품질 검사 — 품질: 슬리팅 롤 ①② 합격(ΔE) · ③ 불합격(불량 유형·위치).

    스캔 세 번을 서로 다른 상태에서 쏜다(지난번 결함 DEF-QA3-001 의 두 증상을 둘 다 지난다):
      ① 화면을 막 연 상태  ② 앞 검사의 저장 알림을 「확인」 으로 **닫은 뒤**(포커스가 스캔칸으로 돌아와야 한다)
      ③ 앞 검사의 저장 알림이 **떠 있는 채로**(글자가 스캔칸에 들어가야 한다 — 스캐너는 기다려 주지 않는다)."""
    s = Session(b, "qc")
    s.login()
    shots, bad, wk, modes = [], [], [], []
    slit = S["slit_rolls"]
    plan = [(slit[0], "0.8", "합격", None), (slit[1], "1.2", "합격", None), (slit[2], "4.5", "불합격", f"{PREFIX}DF-01")]
    s.goto("/qua/inspections")
    form = "form#inspection-form"

    def opened(no):
        return bool(s.page.locator(f"{form} [name=roll_no]").count()) and s.page.locator(f"{form} [name=roll_no]").input_value() == no

    for i, (no, de, verdict, defect) in enumerate(plan, 1):
        pop_open = bool(s.popup())
        r = s.scan(no)
        modes.append({"roll": i, "popup_open": pop_open, "focus_on_scan": r["focus_on_scan"], "opened": opened(no)})
        if not opened(no):
            LOST_SCANS.append({"where": f"11 품질 검사 롤 {i}", "value": no})
            wk.append(f"검사 결과 화면 {i}번째 롤: 스캔(타이핑+Enter)만으로 검사 폼이 열리지 않음 — 알림 {'떠 있음' if pop_open else '없음'} · "
                      f"포커스 {r['focus'][:40]!r} → 스캔칸을 눌러 다시 스캔")
            if s.popup():
                s.close_popup()
            s.bypass_click_scan(f"11 품질 검사 롤 {i}"); s.scan(no)
        if not opened(no):
            bad.append(f"롤 {no}: 스캔칸을 누르고 다시 스캔해도 검사 폼이 안 열림")
            continue
        fill(s.page, form, {"delta_e": de, "result": verdict, "note": f"E2E {MARK}"})
        if defect:
            s.page.locator(f"{form} [name=defect_code]").first.select_option(defect)
            s.page.locator(f"{form} [name=position]").first.fill("끝단 10m (예시)")
        if i == 1:
            shots.append(s.shot("11-품질검사-스캔.png"))
        res = s.submit(form)
        got = conn.q1("""select i.result, i.delta_e from inspection i join roll r on r.roll_id = i.roll_id where r.roll_no = %s
                          order by inspection_id desc""", (no,))
        if not got or got["result"] != verdict or not res["popup"] or res["popup"]["warn"]:
            bad.append(f"검사 {no}: DB {got} · {res}")
        if i == 3:
            shots.append(s.shot("11-품질검사-등록.png"))
        if i != 2:
            s.close_popup()             # ① 뒤: 「확인」 으로 닫는다 → ② 는 닫은 뒤의 포커스로 스캔 / ② 뒤: 닫지 않는다 → ③ 은 알림이 뜬 채로 스캔
        S[f"qua_focus_after_close_{i}"] = s.active()["html"]
    S["qua_scan_modes"] = modes
    s.goto("/qua/defect-stats")
    shots.append(s.shot("11-불량집계.png"))
    if f"{PREFIX}DF-01" not in s.text():
        bad.append("불량 유형별 집계에 방금 등록한 불량이 안 보임")
    for x in bad + wk:
        J.finding("11", x)
    J.step("11", "품질 검사", "qc", "슬리팅 롤 3개를 차례로 스캔(① 새 화면 · ② 알림을 닫은 뒤 · ③ 알림이 뜬 채로) → ΔE·판정(③은 불합격 + 불량 유형·위치) 등록 → 불량 집계",
           "FAIL" if bad else ("결함(우회)" if wk else "PASS"), shots,
           note=f"우회 {len(wk)}건 · 스캔 {modes} · 알림 닫은 뒤 포커스: {S.get('qua_focus_after_close_1', '')[:60]}")
    s.close()


def step12_shipment(b):
    """출하 등록·롤 스캔 — 현장(POP): 출하 등록 → 롤 ①② 스캔, ③(불합격)·①(재출하) 422.

    로그인은 주소(`?device=pop`)가 아니라 로그인 화면의 **채널 라디오**로 POP 을 고른다(D-30).
    롤 ① 은 등록 알림을 「확인」 으로 닫은 뒤, 롤 ②·③·① 재스캔은 **앞 스캔의 알림이 떠 있는 채로** 연달아 쏜다(손을 대지 않는다)."""
    s = Session(b, "field", device="pop", viewport={"width": 1280, "height": 800})
    s.login(pick_channel=True)
    shots, bad, wk, obs = [], [], [], {}
    slit = S["slit_rolls"]
    s.goto("/shp/shipments")
    obs["body"] = s.body_class()
    if "ch-pop" not in obs["body"]:
        bad.append(f"로그인 화면의 채널 라디오로 POP 을 골랐는데 출하 화면이 {obs['body']}")
    form = "form.form-grid[action='/shp/shipments']"
    fill(s.page, form, {"job_no": S["job_no"], "ship_date": date.today().isoformat(), "note": f"E2E {MARK}"})
    res = s.submit(form)
    row = conn.q1("select shipment_no from shipment s join job j on j.job_id = s.job_id where j.job_no = %s order by shipment_id desc", (S["job_no"],))
    ship = row["shipment_no"] if row else None
    S["shipment_no"] = ship
    J.save()
    if not ship or not res["popup"] or res["popup"]["warn"]:
        bad.append(f"출하 등록: {res} · DB {ship}")
    obs["after_register_url"] = s.page.url
    obs["after_register_body"] = s.body_class()
    shots.append(s.shot("12-출하-등록.png"))
    s.close_popup()
    obs["focus_after_register_popup"] = s.active()["html"]
    if ship:
        scan_action = f"form.scan-box[action='/shp/shipments/{ship}/rolls']"
        if not s.page.locator(scan_action).count():
            obs["opened_after_register"] = False
            # 등록 뒤 그 출하가 열려 있지 않으면 출하 LOT 번호를 스캔해 연다
            if not s.active()["scan"]:
                wk.append("출하 등록 알림을 닫은 뒤 포커스가 스캔칸이 아님")
                s.bypass_click_scan("12 출하 LOT 열기")
            s.scan(ship)

        def shipped(no):
            return conn.q1("""select count(*) as n from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id join shipment s on s.shipment_id = g.child_shipment_id
                               where r.roll_no = %s and s.shipment_no = %s""", (no, ship))["n"]

        def rescue(no, label):
            """스캔만으로 안 됐을 때 사람이 하는 일(= 우회): 알림을 닫고 스캔칸을 눌러 다시 스캔. 부를 때마다 우회 1건."""
            if s.popup():
                s.close_popup()
            s.bypass_click_scan(label)
            return s.scan(no)

        # 롤 ①: 등록 알림을 「확인」 으로 닫은 뒤 — 포커스가 스캔칸에 돌아와 있어야 한다
        if not s.active()["scan"]:
            wk.append(f"출하 롤 ① 스캔: 알림을 닫은 뒤 포커스가 스캔칸으로 돌아오지 않음 (포커스 {s.active()['html'][:40]!r}) → 스캔칸을 눌러야 한다")
            s.bypass_click_scan("12 출하 롤 ①")
        s.scan(slit[0])
        if shipped(slit[0]) != 1:
            LOST_SCANS.append({"where": "12 출하 롤 ①", "value": slit[0]})
            bad.append(f"출하 롤 스캔 {slit[0]}: 계보 {shipped(slit[0])}행")
        obs["scan1"] = {"popup": s.popup(), "body": s.body_class(), "url": s.page.url}
        # 롤 ②: 스캐너는 기다리지 않는다 — 방금 스캔의 알림이 떠 있는 채로 다음 바코드를 쏜다
        pop_open = bool(s.popup())
        r = s.scan(slit[1])
        obs["scan2_while_popup"] = {"popup_was_open": pop_open, "focus_before": r["focus"][:60], "shipped": shipped(slit[1]), "popup_after": s.popup()}
        if not pop_open:
            bad.append("롤 ① 스캔 뒤 알림이 뜨지 않아 「알림이 뜬 채 스캔」 을 재지 못함")
        if shipped(slit[1]) != 1:
            LOST_SCANS.append({"where": "12 출하 롤 ② (알림이 뜬 채)", "value": slit[1]})
            wk.append(f"출하 롤 ② 스캔: 앞 스캔의 알림이 떠 있는 동안 쏜 바코드가 버려짐 (계보 {shipped(slit[1])}행) → 다시 스캔")
            rescue(slit[1], "12 출하 롤 ② 재스캔")
            if shipped(slit[1]) != 1:
                bad.append(f"출하 롤 스캔 {slit[1]}: 다시 스캔해도 계보 {shipped(slit[1])}행")
        shots.append(s.shot("12-출하-롤스캔.png"))
        # 불합격 롤 ③: 롤 ② 의 알림이 떠 있는 채로 — 422 경고가 나와야 하고(조용히 버려지면 안 된다) 롤은 재고로 남는다
        pop_open = bool(s.popup())
        r = s.scan(slit[2])
        obs["fail_roll"] = {"popup_was_open": pop_open, "popup": s.popup(), "state": roll_state(slit[2]), "scan_present": s.page.locator("[data-scan]").count(),
                            "banner": s.page.evaluate("(() => { const e = document.querySelector('#scan-result'); return e ? {text: e.innerText.trim().slice(0, 120), px: parseFloat(getComputedStyle(e.querySelector('.big') || e).fontSize)} : null; })()"),
                            "err_px": s.page.evaluate("(() => { const e = document.querySelector('#popup-body p'); return e ? parseFloat(getComputedStyle(e).fontSize) : null; })()")}
        shots.append(s.shot("12-출하-불합격롤-422.png"))
        if roll_state(slit[2]) != "재고":
            bad.append(f"불합격 롤이 출하됨: {slit[2]}")
        if not (obs["fail_roll"]["popup"] and obs["fail_roll"]["popup"]["warn"] and slit[2] in obs["fail_roll"]["popup"]["body"]):
            LOST_SCANS.append({"where": "12 불합격 롤 ③ (알림이 뜬 채) — 422 경고가 안 보임", "value": slit[2]})
            wk.append(f"불합격 롤 ③ 스캔: 알림이 뜬 채 쏜 바코드에 422 경고가 안 뜸 ({obs['fail_roll']}) → 다시 스캔")
            rescue(slit[2], "12 불합격 롤 ③ 재스캔")
            if not (s.popup() and s.popup()["warn"]):
                bad.append(f"불합격 롤 스캔에 경고가 안 뜸: {s.popup()}")
        # 이미 출하된 롤 ① 재스캔: 422 경고가 떠 있는 채로
        pop_open = bool(s.popup())
        r = s.scan(slit[0])
        obs["reship"] = {"popup_was_open": pop_open, "popup": s.popup(), "scan_present": s.page.locator("[data-scan]").count()}
        shots.append(s.shot("12-출하-재출하-422.png"))
        if not (obs["reship"]["popup"] and obs["reship"]["popup"]["warn"] and slit[0] in obs["reship"]["popup"]["body"]):
            LOST_SCANS.append({"where": "12 재출하 스캔 (알림이 뜬 채) — 422 경고가 안 보임", "value": slit[0]})
            wk.append(f"재출하 스캔: 알림이 뜬 채 쏜 바코드에 422 경고가 안 뜸 ({obs['reship']})")
            rescue(slit[0], "12 재출하 재스캔")
        s.close_popup()
        obs["focus_after_last_close"] = s.active()["scan"]
        if not obs["focus_after_last_close"]:
            wk.append("마지막 알림을 「확인」 으로 닫은 뒤 포커스가 스캔칸이 아님")
        n = conn.q1("select count(*) as n from roll_genealogy g join shipment s on s.shipment_id = g.child_shipment_id where s.shipment_no = %s", (ship,))["n"]
        if n != 2:
            bad.append(f"출하 계보 {n}행 (기대 2)")
    S["shp_obs"] = obs
    for x in bad + wk:
        J.finding("12", x)
    J.step("12", "출하 등록·롤 스캔", "field (POP · 채널 라디오로 로그인)", "출하 등록 → 슬리팅 롤 ① 스캔(알림 닫은 뒤) → ② · 불합격 ③(422) · ① 재스캔(422)을 알림이 뜬 채 연달아 스캔",
           "FAIL" if bad else ("결함(우회)" if wk else "PASS"), shots, note=f"출하 LOT {ship} · 우회 {len(wk)}건 · 재출하 {obs.get('reship')}")
    s.close()


def step13_approve(b):
    """출하 승인 — 관리자: 승인 화면에서 「승인」 → COA 번호. (현장 계정에는 승인 버튼이 비활성인가)"""
    shots, bad = [], []
    f = Session(b, "field")
    f.login()
    st = f.goto("/shp/approvals")
    S["approve_forms_field"] = forms(f)
    shots.append(f.shot("13-출하승인-현장계정.png"))
    f.close()
    s = Session(b, "admin")
    s.login()
    s.goto("/shp/approvals")
    form = f"form[action='/shp/approvals/{S['shipment_no']}/approve']"
    if not s.page.locator(form).count():
        bad.append("승인 대기 목록에 출하 LOT 이 없음")
    else:
        shots.append(s.shot("13-출하승인-대기.png"))
        res = s.submit(form)
        row = conn.q1("select status, coa_no, approved_by from shipment where shipment_no = %s", (S["shipment_no"],))
        S["coa_no"] = row["coa_no"]
        S["approve_dialogs"] = s.dialogs
        if row["status"] != "승인" or not row["coa_no"] or not res["popup"] or res["popup"]["warn"]:
            bad.append(f"승인: DB {row} · {res} · 확인창 {s.dialogs}")
        shots.append(s.shot("13-출하승인-완료.png")); s.close_popup()
    for x in bad:
        J.finding("13", x)
    J.step("13", "출하 승인", "admin", "출하 승인 화면 → 「승인」(확인창 수락) → 상태 승인 + COA 채번", "PASS" if not bad else "FAIL", shots,
           note=f"COA {S.get('coa_no')} · 확인창 {S.get('approve_dialogs')} · 현장 계정 화면 HTTP {st}")
    s.close()


def step14_coa(b):
    """COA — 관리자: COA 목록 → 「COA 출력」 → 인쇄용 화면 + 바코드."""
    s = Session(b, "admin")
    s.login()
    shots, bad = [], []
    s.goto("/shp/coa")
    link = s.page.locator(f"tr:has-text('{S['shipment_no']}') a:has-text('COA 출력')")
    shots.append(s.shot("14-COA-목록.png"))
    if not link.count():
        bad.append("COA 목록에 출력 링크 없음")
    else:
        n0 = len(s.requests)
        link.first.click(); s.page.wait_for_load_state()
        shot = s.shot("14-COA-출력.png"); shots.append(shot)
        codes = zbar(OUT / shot)
        S["coa_barcode"] = codes
        txt = s.text()
        ext = [u for u in s.requests[n0:] if not u.startswith(BASE)]
        miss = [x for x in S["slit_rolls"][:2] if x not in txt]
        if miss or S["coa_no"] not in txt:
            bad.append(f"COA 본문에 없는 것: 롤 {miss} · COA 번호 {S['coa_no'] in txt}")
        if not codes:
            bad.append("COA 바코드가 디코더로 읽히지 않음")
        if ext:
            bad.append(f"COA 화면의 외부 요청 {ext[:3]}")
        S["coa_has_delta_e"] = ("0.8" in txt and "1.2" in txt)
    for x in bad:
        J.finding("14", x)
    J.step("14", "COA", "admin", "COA 목록 → 「COA 출력」 → 인쇄용 화면", "PASS" if not bad else "FAIL", shots,
           note=f"COA 바코드 디코드 {S.get('coa_barcode')} · ΔE 표시 {S.get('coa_has_delta_e')}")
    s.close()


def step15_trace(b):
    """LOT 역추적 — 품질: 출하 LOT → 원재료 LOT ①② (역방향) · LOT① → 출하 LOT (정방향)."""
    s = Session(b, "qc")
    s.login()
    shots, bad = [], []
    s.goto("/trc/trace")
    a = s.active()
    if not a["scan"]:
        bad.append(f"LOT 추적 화면: 포커스가 번호칸이 아님 ({a['html']})")
        s.bypass_click_scan("15 LOT 추적 번호칸")
    s.page.keyboard.type(S["shipment_no"])
    with s.page.expect_navigation():
        s.page.click("button:has-text('역방향 추적')")
    txt = s.text()
    need = [S["lot1"], S["lot2"], *S["print_rolls"], S["finishing_roll"], *S["slit_rolls"][:2]]
    miss = [x for x in need if x not in txt]
    if miss:
        bad.append(f"역방향 추적 화면에 없는 번호 {miss}")
    shots.append(s.shot("15-역추적-출하LOT→원재료LOT.png"))
    # 정방향: LOT① 을 스캔칸에 치고 「정방향 추적」
    s.goto("/trc/trace")
    s.page.keyboard.type(S["lot1"])
    with s.page.expect_navigation():
        s.page.click("button:has-text('정방향 추적')")
    txt = s.text()
    miss = [x for x in (S["shipment_no"], S["slit_rolls"][2], "재고") if x not in txt]
    if miss:
        bad.append(f"정방향 추적 화면에 없는 것 {miss}")
    shots.append(s.shot("15-정방향-원재료LOT→출하.png"))
    # LOT 검색: 번호 일부 + Enter (Enter = 기본 버튼 = LOT 검색)
    s.goto("/trc/trace")
    r = s.scan(S["shipment_no"][:8])
    found = S["shipment_no"] in s.text()
    S["trace_search"] = {"url": s.page.url, "found": found}
    if not found:
        bad.append(f"LOT 검색(번호 일부 + Enter)에 출하 LOT 이 안 나옴 — {s.page.url}")
    shots.append(s.shot("15-LOT검색.png"))
    # 계보 10행 (설계도 §3 의 화살표 10개)
    g = conn.q("""select g.relation, count(*) as n from roll_genealogy g
                   left join roll c on c.roll_id = g.child_roll_id left join shipment sh on sh.shipment_id = g.child_shipment_id
                   left join job j on j.job_id = coalesce(c.job_id, sh.job_id)
                  where j.job_no = %s group by g.relation order by 1""", (S["job_no"],))
    S["genealogy"] = {x["relation"]: x["n"] for x in g}
    total = sum(S["genealogy"].values())
    if total != 10:
        bad.append(f"이 Job 의 계보 {total}행 {S['genealogy']} (기대 10 = 투입 3 · splice 2 · 슬리팅 3 · 출하 2)")
    s.close()
    # 현장 계정은 LOT 추적 권한 없음 → 403 화면
    f = Session(b, "field")
    f.login()
    st = f.goto("/trc/trace")
    S["trace_field_status"] = st
    f.close()
    for x in bad:
        J.finding("15", x)
    J.step("15", "LOT 역추적", "qc", "출하 LOT 번호 입력 → 「역방향 추적」 · LOT① → 「정방향 추적」 · 번호 일부로 LOT 검색",
           "PASS" if not bad else "FAIL", shots, note=f"계보 {S.get('genealogy')} = {total}행 · 현장 계정 /trc/trace HTTP {st}")


def step16_status(b):
    """실적 현황·매핑 — 관리자: 집계에 이 Job 이 보이는가, Job-Lot-Roll 매핑에 롤·출하 LOT 이 이어지는가, 로그 화면에 변경이 남았는가."""
    s = Session(b, "admin")
    s.login()
    shots, bad = [], []
    s.goto("/sta/summary")
    shots.append(s.shot("16-실적현황-집계.png"))
    if f"{PREFIX}FG-01" not in s.text():
        bad.append("실적 현황 집계에 이 Job 의 품목이 안 보임")
    s.goto(f"/job/mapping?no={S['job_no']}")
    txt = s.text()
    miss = [x for x in [*S["print_rolls"], S["finishing_roll"], *S["slit_rolls"], S["shipment_no"]] if x not in txt]
    if miss:
        bad.append(f"Job-Lot-Roll 매핑 화면에 없는 번호 {miss}")
    shots.append(s.shot("16-매핑-롤과출하.png"))
    s.goto("/sys/logs")
    s.page.select_option("form.search-form select[name=log_type]", "변경")
    with s.page.expect_navigation():
        s.page.click("form.search-form button[type=submit]")
    shots.append(s.shot("16-로그-변경.png"))
    if "F-SHP-05" not in s.text():
        bad.append("로그 화면(변경)에 출하 승인(F-SHP-05)이 안 보임")
    for x in bad:
        J.finding("16", x)
    J.step("16", "실적 현황 · 매핑 · 로그", "admin", "집계 화면 · Job-Lot-Roll 매핑 조회 · 로그(변경) 조회", "PASS" if not bad else "FAIL", shots,
           note=f"실패 {len(bad)}")
    s.close()


STEPS = [step01_login, step02_master, step03_print_std, step04_job, step05_receipt, step06_incoming_inspection, step07_color, step08_print,
         step09_splice, step10_slit, step11_quality, step12_shipment, step13_approve, step14_coa, step15_trace, step16_status]


def main():
    args = sys.argv[1:]
    lo, hi = (args[0], args[-1]) if args else ("00", "99")
    if not args:
        print("잔여 정리:", cleanup())
        J.data.update({"state": {}, "steps": [], "findings": []})
        global S
        S = J.state
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        S["browser"] = f"Playwright Chromium {b.version} (headless)"
        for fn in STEPS:
            no = fn.__name__[4:6]
            if lo <= no <= hi:
                try:
                    fn(b)
                except Exception as exc:  # noqa: BLE001 — 단계가 터진 것도 결과다
                    traceback.print_exc()
                    J.finding(no, f"단계 실행 중 예외: {type(exc).__name__}: {str(exc)[:300]}")
                    J.step(no, fn.__doc__.split("—")[0].strip() if fn.__doc__ else fn.__name__, "-", "-", "FAIL", [], note="예외로 중단")
        b.close()
    steps = J.data["steps"]
    api_sub = [x["no"] for x in steps if x["how"] != "브라우저"]
    not_pass = [x["no"] for x in steps if x["result"] != "PASS"]
    full = not args and len(steps) == len(STEPS)
    ok = full and not not_pass and not BYPASSES and not LOST_SCANS and not api_sub
    S["bypasses"], S["lost_scans"] = BYPASSES, LOST_SCANS
    S["scans"] = {"count": len(SCANS), "focus_not_on_scan": [x for x in SCANS if not x["focus_on_scan"]],
                  "while_popup_open": len([x for x in SCANS if x["popup_open"]])}
    S["verdict"] = {"G-22": "PASS" if ok else ("FAIL" if full else "부분 실행 — 판정 없음"), "steps": len(steps), "browser_steps": len(steps) - len(api_sub),
                    "api_substituted": api_sub, "not_pass": not_pass, "bypass_count": len(BYPASSES), "lost_scan_count": len(LOST_SCANS),
                    "shots": sorted({x for st in steps for x in st["shots"]})}
    print(f"G-22 {S['verdict']['G-22']} — 단계 {len(steps)} · 브라우저 {len(steps) - len(api_sub)} · API 대체 {len(api_sub)} · PASS 아닌 단계 {not_pass} · "
          f"우회(스캔칸 직접 누름·주소로 직접 엶) {len(BYPASSES)} · 유실 {len(LOST_SCANS)} · 스캔 {len(SCANS)}회"
          f"(알림이 뜬 채 {S['scans']['while_popup_open']} · 포커스가 스캔칸이 아니었던 것 {len(S['scans']['focus_not_on_scan'])}) · 캡처 {len(S['verdict']['shots'])}장")
    J.save()


if __name__ == "__main__":
    main()
