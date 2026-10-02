"""QA3 E2E 공용 — 실제 브라우저(Playwright Chromium)로 로그인·스캔·캡처를 한다.

    uv run --with playwright python tools/e2e/run_e2e.py

- 스캔은 **키보드 입력**이다(D-04): 지금 포커스를 가진 요소에 글자를 치고 Enter. 스캔칸을 셀렉터로 찾아 채우지 않는다
  — 포커스가 스캔칸에 없으면 그 사실이 결함이다(`scan()` 이 적는다).
- 비밀번호는 `.env` 의 `LCOMFINE_SEED_PASSWORD` 에서만 읽고 어디에도 적지 않는다. 로그인 화면 캡처는 입력 전에 찍는다.
- 서버는 포트 8023 (QA3 전용).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lcomfine.app.settings import get_settings  # noqa: E402
from lcomfine.db import conn  # noqa: E402

BASE = "http://localhost:8023"
OUT = ROOT / "outputs" / "e2e"
PREFIX = "Q3E-"            # E2E 가 만든 기준정보의 코드 접두
MARK = "(예시) Q3"         # 이름에 붙는 표시


class Session:
    """한 역할로 로그인한 브라우저 컨텍스트. 역할을 바꿀 때마다 새 컨텍스트 = 새 로그인."""

    def __init__(self, browser, role: str, device: str | None = None, viewport: dict | None = None,
                 is_mobile: bool = False):
        self.role, self.device = role, device
        opts = {"viewport": viewport or {"width": 1280, "height": 900}, "locale": "ko-KR"}
        if is_mobile:
            opts.update({"is_mobile": True, "has_touch": True, "device_scale_factor": 2})
        self.ctx = browser.new_context(**opts)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(10000)
        self.console: list[str] = []
        self.requests: list[str] = []
        self.dialogs: list[str] = []
        self.page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        self.page.on("request", lambda r: self.requests.append(r.url))
        self.page.on("dialog", self._dialog)
        self.login_status = None

    def _dialog(self, d):
        self.dialogs.append(f"{d.type}: {d.message}")
        d.accept()

    def login(self, shot_before: str | None = None) -> str:
        """로그인 폼에 실제로 타이핑하고 버튼을 누른다. 로그인 뒤 도착한 주소를 돌려준다."""
        p = self.page
        p.goto(BASE + "/login" + (f"?device={self.device}" if self.device else ""))
        if shot_before:
            p.screenshot(path=str(OUT / shot_before), full_page=True)
        p.fill("input[name=login_id]", self.role)
        p.fill("input[name=password]", get_settings().seed_password)
        with p.expect_navigation():
            p.click("form[action='/login'] button[type=submit], form button")
        return p.url

    def close(self):
        self.ctx.close()

    # ── 관찰 ──
    def active(self) -> dict:
        return self.page.evaluate("""() => { const a = document.activeElement; return {
            tag: a ? a.tagName : '', name: a ? (a.name || '') : '', scan: !!(a && a.hasAttribute && a.hasAttribute('data-scan')),
            html: a ? a.outerHTML.slice(0, 100) : '' }; }""")

    def popup(self) -> dict | None:
        """떠 있는 알림 팝업의 제목·본문 (없으면 None)."""
        return self.page.evaluate("""() => { const l = document.getElementById('popup-layer');
            if (!l || l.hidden) return null;
            return {title: document.getElementById('popup-title').textContent.trim(),
                    body: document.getElementById('popup-body').innerText.trim(),
                    warn: l.querySelector('.popup').classList.contains('warn')}; }""")

    def close_popup(self) -> dict | None:
        pop = self.popup()
        if pop:
            self.page.click("#popup-layer [data-popup-close]")
            self.page.wait_for_timeout(150)   # 화면 스크립트가 포커스를 되돌릴 틈(setTimeout 0)을 준다
        return pop

    def body_class(self) -> str:
        return self.page.evaluate("document.body.className")

    def text(self) -> str:
        return self.page.inner_text("body")

    def shot(self, name: str, full: bool = True) -> str:
        self.page.screenshot(path=str(OUT / name), full_page=full)
        return name

    def goto(self, path: str) -> int:
        r = self.page.goto(BASE + path)
        return r.status if r else 0

    # ── 스캔 (D-04: 스캐너 = 키보드 입력) ──
    def scan(self, value: str) -> dict:
        """지금 포커스를 가진 곳에 글자를 치고 Enter. 포커스가 스캔칸이 아니면 그 사실을 돌려준다(고치지 않는다)."""
        before = self.active()
        self.page.keyboard.type(value, delay=5)
        try:
            with self.page.expect_navigation(timeout=4000):
                self.page.keyboard.press("Enter")
            navigated = True
        except Exception:  # noqa: BLE001 — 화면이 안 넘어간 것이 관찰 결과다
            navigated = False
        return {"focus_on_scan": before["scan"], "focus": before["html"], "navigated": navigated, "url": self.page.url}

    def submit(self, form_selector: str, button_text: str | None = None) -> dict:
        """폼의 제출 버튼을 실제로 누른다. 응답 상태·도착 주소·알림을 돌려준다."""
        p = self.page
        # 제출 버튼은 폼 밖에 `form=` 속성으로 붙어 있기도 하다 → form.elements 에서 찾아 **실제로 클릭**한다
        handle = p.evaluate_handle(
            """([sel, text]) => { const f = document.querySelector(sel); if (!f) return null;
                 const bs = Array.from(f.elements).filter(e => e.tagName === 'BUTTON' && e.type === 'submit'
                                                           && (!text || e.textContent.trim().includes(text)));
                 return bs[0] || null; }""", [form_selector, button_text or ""])
        btn = handle.as_element()
        if btn is None:
            return {"navigated": False, "chain": [("제출 버튼 없음", 0)], "url": p.url, "popup": self.popup(), "no_button": True}
        if btn.is_disabled():
            return {"navigated": False, "chain": [("제출 버튼 비활성", 0)], "url": p.url, "popup": self.popup(), "disabled": True}
        statuses: list[tuple[str, int]] = []
        handler = lambda r: statuses.append((r.request.method + " " + r.url.replace(BASE, ""), r.status)) if r.request.is_navigation_request() else None  # noqa: E731
        p.on("response", handler)
        try:
            with p.expect_navigation(timeout=8000):
                btn.click()
            navigated = True
        except Exception as exc:  # noqa: BLE001
            navigated = False
            statuses.append((f"no navigation: {str(exc)[:80]}", 0))
        p.remove_listener("response", handler)
        return {"navigated": navigated, "chain": statuses, "url": p.url, "popup": self.popup()}


# ── 상태 파일 · 결과 ──
class Journal:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"state": {}, "steps": [], "findings": []}

    @property
    def state(self) -> dict:
        return self.data["state"]

    def step(self, no: str, name: str, role: str, did: str, result: str, shots: list[str], how: str = "브라우저", note: str = ""):
        self.data["steps"] = [s for s in self.data["steps"] if s["no"] != no]
        self.data["steps"].append({"no": no, "name": name, "role": role, "did": did, "result": result, "shots": shots,
                                   "how": how, "note": note})
        self.data["steps"].sort(key=lambda s: s["no"])
        print(f"[{no}] {name} ({role}) — {result} · {how} · {note}")
        self.save()

    def finding(self, key: str, text: str):
        if not any(f["key"] == key and f["text"] == text for f in self.data["findings"]):
            self.data["findings"].append({"key": key, "text": text})
        print(f"  !! {key}: {text}")
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def zbar(png: Path) -> list[str]:
    """캡처 PNG 의 바코드를 실제 디코더(zbarimg)로 읽는다 → ['CODE-128:R261003-0001', …]."""
    r = subprocess.run(["zbarimg", "-q", str(png)], capture_output=True, text=True)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


# ── 뒷정리 (E2E 가 만든 행 — 접두 Q3E- 의 품목으로 식별) ──
def cleanup(prefix: str = PREFIX) -> dict:
    like = f"{prefix}%"
    out: dict[str, int] = {}
    with conn.tx() as cur:
        def ids(sql: str, params: tuple) -> list:
            cur.execute(sql, params)
            return [next(iter(r.values())) for r in cur.fetchall()]

        def dele(name: str, sql: str, params: tuple) -> None:
            cur.execute(sql, params)
            out[name] = out.get(name, 0) + cur.rowcount

        items = ids("select item_id from item where item_code like %s", (like,))
        jobs = ids("select job_id from job where item_id = any(%s)", (items,))
        lots = ids("select material_lot_id from material_lot where item_id = any(%s)", (items,))
        rolls = ids("select roll_id from roll where job_id = any(%s)", (jobs,))
        ships = ids("select shipment_id from shipment where job_id = any(%s)", (jobs,))
        works = ids("select work_result_id from work_result where job_id = any(%s)", (jobs,))
        dele("roll_genealogy", """delete from roll_genealogy where child_roll_id = any(%s) or parent_roll_id = any(%s)
                                    or parent_material_lot_id = any(%s) or child_shipment_id = any(%s)""",
             (rolls, rolls, lots, ships))
        dele("inspection_defect", "delete from inspection_defect where inspection_id in (select inspection_id from inspection where roll_id = any(%s))", (rolls,))
        dele("inspection", "delete from inspection where roll_id = any(%s) or job_id = any(%s)", (rolls, jobs))
        dele("shipment", "delete from shipment where shipment_id = any(%s)", (ships,))
        dele("roll", "delete from roll where roll_id = any(%s)", (rolls,))
        dele("material_input", "delete from material_input where work_result_id = any(%s) or material_lot_id = any(%s)", (works, lots))
        dele("work_stop", "delete from work_stop where work_result_id = any(%s)", (works,))
        dele("work_scrap", "delete from work_scrap where work_result_id = any(%s)", (works,))
        dele("work_result", "delete from work_result where work_result_id = any(%s)", (works,))
        dele("color_record_mix", "delete from color_record_mix where color_record_id in (select color_record_id from color_record where job_id = any(%s))", (jobs,))
        dele("color_record", "delete from color_record where job_id = any(%s)", (jobs,))
        dele("material_lot", "delete from material_lot where material_lot_id = any(%s)", (lots,))
        dele("job_lot", "delete from job_lot where job_id = any(%s)", (jobs,))
        dele("job", "delete from job where job_id = any(%s)", (jobs,))
        dele("plate_spec", "delete from plate_spec where plate_code like %s", (like,))
        dele("anilox", "delete from anilox where anilox_code like %s", (like,))
        dele("ink_formula", "delete from ink_formula where ink_code like %s", (like,))
        dele("equipment", "delete from equipment where equipment_code like %s", (like,))
        dele("process", "delete from process where process_code like %s", (like,))
        dele("defect_code", "delete from defect_code where defect_code like %s", (like,))
        dele("customer", "delete from customer where customer_code like %s", (like,))
        dele("item", "delete from item where item_code like %s", (like,))
    return {k: v for k, v in out.items() if v}


if __name__ == "__main__":
    if sys.argv[1:] == ["cleanup"]:
        print("지운 행:", cleanup())
