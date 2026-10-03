"""홍보·시연 영상 — 실제 브라우저(Playwright Chromium)로 시스템을 조작하는 모습을 녹화해 mp4 로 만든다.

    uv run --with playwright --with imageio-ffmpeg python tools/e2e/promo_video.py          # 전체 (끝에 VID- 데이터를 지운다)
    uv run --with playwright --with imageio-ffmpeg python tools/e2e/promo_video.py --keep   # 데이터를 남긴다(확인용)
  (`--with imageio-ffmpeg` 는 /opt/homebrew/bin/ffmpeg 가 안 돌 때의 대체 바이너리 — 돌면 homebrew 것을 쓴다)

- 포트 8020 에 떠 있는 개발 서버를 쓴다(새로 띄우지 않는다). 계정 admin / prod / qc / field, 비밀번호는 `.env` 에서만 읽는다
  (`lib.Session.login` 이 type=password 칸에 넣는다 — 화면에 보이지 않는다).
- 로그인·스캔(타이핑+Enter)·팝업 처리는 `tools/e2e/lib.py` 를 그대로 쓴다. 템플릿·src 는 건드리지 않는다 —
  자막 띠·가짜 마우스 커서는 `context.add_init_script` 로 그 페이지에만 끼운다.
- 영상에서 새로 만드는 데이터는 품목 코드 접두 `VID-` 로 묶이고 끝에 `lib.cleanup("VID-")` 가 지운다(시드·SMP- 샘플은 건드리지 않는다).
- 결과: outputs/video/엘컴화인_MES_시연.mp4 (1280×720 · H.264 · 30fps) + 구간별 mp4 + _work/ 작업 파일.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib  # noqa: E402
from lib import ROOT, MARK as _MARK, Session, cleanup, conn  # noqa: E402,F401
from playwright.sync_api import sync_playwright  # noqa: E402

lib.BASE = "http://127.0.0.1:8020"          # lib 의 기본값은 QA3 전용 포트(8023) — 영상은 떠 있는 개발 서버를 쓴다
BASE = lib.BASE
PREFIX = "VID-"
MARK = "(예시)"
OUT = ROOT / "outputs" / "video"
WORK = OUT / "_work"
RAW = WORK / "raw"
CARDS = WORK / "cards"
W, H = 1280, 720


def find_ffmpeg() -> tuple[str, str]:
    """/opt/homebrew/bin/ffmpeg 를 먼저 쓴다. 그것이 안 돌면(라이브러리 깨짐) imageio-ffmpeg 의 정적 바이너리로 대신한다
    (`uv run --with playwright --with imageio-ffmpeg …`). 어느 쪽을 썼는지 보고에 적는다."""
    brew = "/opt/homebrew/bin/ffmpeg"
    try:
        subprocess.run([brew, "-version"], capture_output=True, check=True, timeout=10)
        return brew, "homebrew"
    except Exception as exc:  # noqa: BLE001
        why = f"{type(exc).__name__}"
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe(), f"imageio-ffmpeg (homebrew ffmpeg 실행 실패: {why})"
    except ImportError:
        raise SystemExit(f"ffmpeg 를 쓸 수 없다 — {brew} 실행 실패({why}) · imageio-ffmpeg 없음. "
                         "`uv run --with playwright --with imageio-ffmpeg python tools/e2e/promo_video.py` 로 다시 실행") from None


FFMPEG, FFMPEG_SOURCE = find_ffmpeg()
SLOW_MO = 120
KEEP = "--keep" in sys.argv

# progress.md 「최종 보고」 의 값 — 그대로 쓴다(지어내지 않는다)
GATE = {"gate": "PASS 22/22", "pytest": "1612 passed", "defects": "결함 22건 전부 해결 · 치명 0"}
SCALE = {"channels": 4, "menus": 32, "functions": 94, "tables": 30}

S: dict = {}            # 구간 사이에 넘기는 번호(Job · 롤 · 출하 LOT)
SEGMENTS: list[dict] = []
BLOCKED: list[str] = []

# ── 페이지에 끼우는 것: 자막 띠 + 보이는 마우스 커서 (템플릿을 고치지 않는다) ──
INIT_JS = """
(() => {
  function ensure() {
    if (document.getElementById('vid-caption')) return;
    const c = document.createElement('div'); c.id = 'vid-caption';
    c.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483646;padding:12px 24px;font:18px/1.4 "Apple SD Gothic Neo","Malgun Gothic",sans-serif;'
      + 'color:#fff;background:rgba(15,23,42,.82);letter-spacing:.2px;text-align:left;pointer-events:none;box-shadow:0 -2px 8px rgba(0,0,0,.25)';
    (document.body || document.documentElement).appendChild(c);
    const m = document.createElement('div'); m.id = 'vid-cursor';
    m.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;pointer-events:none;transform:translate(-3px,-2px);'
      + 'background:url("data:image/svg+xml;utf8,<svg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 24 24%27><path d=%27M4 2l16 11-7 1 4 7-3 1.5-4-7-5 5z%27 fill=%27%23111%27 stroke=%27%23fff%27 stroke-width=%271.5%27/></svg>") no-repeat;left:-50px;top:-50px';
    (document.body || document.documentElement).appendChild(m);
    let t; try { t = sessionStorage.getItem('vidcap'); } catch (e) {}
    if (t) c.textContent = t; else c.style.display = 'none';
  }
  window.__vidcap = function (t) { ensure(); const c = document.getElementById('vid-caption'); c.textContent = t; c.style.display = t ? '' : 'none';
    try { sessionStorage.setItem('vidcap', t || ''); } catch (e) {} };
  document.addEventListener('mousemove', e => { ensure(); const m = document.getElementById('vid-cursor'); m.style.left = e.clientX + 'px'; m.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', () => { const m = document.getElementById('vid-cursor'); if (m) { m.style.transform = 'translate(-3px,-2px) scale(.8)'; setTimeout(() => m.style.transform = 'translate(-3px,-2px)', 160); } }, true);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ensure); else ensure();
})();
"""


class Vid(Session):
    """lib.Session 과 같은 로그인·스캔 흐름 + 영상 녹화 컨텍스트(1280×720)."""

    def __init__(self, browser, role: str, device: str | None = None, viewport: dict | None = None, is_mobile: bool = False,
                 video_dir: Path | None = None):
        self.role, self.device = role, device
        vp = viewport or {"width": W, "height": H}
        opts = {"viewport": vp, "locale": "ko-KR", "record_video_dir": str(video_dir), "record_video_size": vp}
        if is_mobile:
            opts.update({"is_mobile": True, "has_touch": True, "device_scale_factor": 2})
        self.ctx = browser.new_context(**opts)
        self.ctx.add_init_script(INIT_JS)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.console, self.requests, self.dialogs = [], [], []
        self.page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        self.page.on("dialog", self._dialog)
        self.login_status = None

    # ── 사람 속도 ──
    def pause(self, sec: float = 1.0):
        self.page.wait_for_timeout(int(sec * 1000))

    def dwell(self, sec: float = 2.0):
        self.pause(sec)

    def cap(self, text: str):
        self.page.evaluate("t => window.__vidcap && window.__vidcap(t)", text)

    def move_to(self, locator):
        box = locator.first.bounding_box()
        if not box:
            locator.first.scroll_into_view_if_needed()
            box = locator.first.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(box["height"] / 2, 20), steps=18)
            self.pause(0.35)
        return box

    def click(self, selector_or_loc, nav: bool = False, pause: float = 1.0):
        loc = self.page.locator(selector_or_loc) if isinstance(selector_or_loc, str) else selector_or_loc
        loc.first.scroll_into_view_if_needed()
        self.move_to(loc)
        if nav:
            with self.page.expect_navigation():
                loc.first.click()
            self.page.wait_for_load_state()
        else:
            loc.first.click()
        self.pause(pause)

    def type_in(self, selector: str, text: str, pause: float = 0.6):
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        self.move_to(loc)
        loc.click()
        loc.fill("")
        self.page.keyboard.type(text, delay=35)
        self.pause(pause)

    def select(self, selector: str, value: str, pause: float = 0.6):
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        self.move_to(loc)
        loc.select_option(value)
        self.pause(pause)

    def go(self, path: str, dwell: float = 2.0) -> int:
        r = self.page.goto(BASE + path)
        self.page.wait_for_load_state()
        self.dwell(dwell)
        return r.status if r else 0

    def menu(self, path: str, dwell: float = 2.0):
        """왼쪽 메뉴의 링크를 눌러 이동한다(마우스가 보인다). 메뉴에 없으면 주소로 연다."""
        link = self.page.locator(f"nav.side a[href='{path}']")
        if link.count():
            if not link.first.is_visible():               # 접힌 대메뉴 — 제목을 눌러 편다 (사람이 하는 대로)
                self.click(link.first.locator("xpath=ancestor::div[contains(@class,'menu-group')]/div[contains(@class,'menu-head')]"), pause=0.7)
            self.click(link, nav=True, pause=0)
        else:
            self.page.goto(BASE + path)
            self.page.wait_for_load_state()
        self.dwell(dwell)

    def scan_slow(self, value: str) -> dict:
        """스캔 = 키보드 타이핑 + Enter (lib.Session.scan 과 같은 규칙, 글자가 보이는 속도)."""
        before = self.active()
        self.page.keyboard.type(value, delay=35)
        self.pause(0.4)
        try:
            with self.page.expect_navigation(timeout=6000):
                self.page.keyboard.press("Enter")
            navigated = True
        except Exception:  # noqa: BLE001
            navigated = False
        self.page.wait_for_load_state()
        return {"focus_on_scan": before["scan"], "navigated": navigated, "url": self.page.url}

    def submit_slow(self, form_selector: str, button_text: str | None = None) -> dict:
        """lib.Session.submit 과 같은 버튼 찾기 + 마우스 이동이 보이게 누른다."""
        handle = self.page.evaluate_handle(
            """([sel, text]) => { const f = document.querySelector(sel); if (!f) return null;
                 const bs = Array.from(f.elements).filter(e => e.tagName === 'BUTTON' && e.type === 'submit'
                                                           && (!text || e.textContent.trim().includes(text)));
                 return bs[0] || null; }""", [form_selector, button_text or ""])
        btn = handle.as_element()
        if btn is None:
            return {"navigated": False, "popup": None, "no_button": True}
        btn.scroll_into_view_if_needed()
        box = btn.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
            self.pause(0.35)
        try:
            with self.page.expect_navigation(timeout=10000):
                btn.click()
            navigated = True
        except Exception:  # noqa: BLE001
            navigated = False
        self.page.wait_for_load_state()
        self.pause(1.2)
        return {"navigated": navigated, "popup": self.popup(), "url": self.page.url}

    def ok(self, pause: float = 0.8):
        """알림의 「확인」 을 마우스로 누른다."""
        if self.popup():
            self.click("#popup-layer [data-popup-close]", pause=pause)

    def finish(self) -> Path | None:
        page_video = self.page.video
        self.ctx.close()
        return Path(page_video.path()) if page_video else None


# ── 구간 실행 틀 ──
def segment(no: str, name: str):
    def deco(fn):
        fn.seg = (no, name)
        return fn
    return deco


def run_segment(browser, fn):
    no, name = fn.seg
    d = RAW / f"{no}-{name}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    t0 = time.time()
    status, note = "OK", ""
    try:
        fn(browser, d)
    except Exception as exc:  # noqa: BLE001 — 막힌 것도 결과다. 가짜 화면을 만들지 않는다
        traceback.print_exc()
        status, note = "BLOCKED", f"{type(exc).__name__}: {str(exc)[:200]}"
        BLOCKED.append(f"{no} {name}: {note}")
    webms = sorted(d.glob("*.webm"), key=lambda p: p.stat().st_mtime)
    SEGMENTS.append({"no": no, "name": name, "status": status, "note": note, "webms": [str(p) for p in webms], "wall": round(time.time() - t0, 1)})
    print(f"[{no}] {name} — {status} {note} · webm {len(webms)} · {round(time.time() - t0, 1)}s")


def card(name: str, title: str, sub: str = "", lines: list[str] | None = None, foot: str = "") -> Path:
    """로컬 HTML 카드(타이틀·검증 요약·마무리). file:// 로 띄운다."""
    CARDS.mkdir(parents=True, exist_ok=True)
    li = "".join(f"<li>{x}</li>" for x in (lines or []))
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<style>html,body{{margin:0;height:100%;background:#0f172a;color:#fff;font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
.wrap{{height:100%;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:0 80px;box-sizing:border-box}}
h1{{font-size:46px;margin:0 0 18px;letter-spacing:-.5px}} h2{{font-size:26px;font-weight:400;color:#cbd5e1;margin:0 0 30px}}
ul{{list-style:none;padding:0;margin:0;font-size:28px;line-height:1.9}} li b{{color:#7dd3fc}} .foot{{margin-top:34px;font-size:18px;color:#94a3b8}}
.tag{{display:inline-block;background:#1d4ed8;border-radius:999px;padding:6px 18px;font-size:18px;margin-bottom:26px}}</style></head>
<body><div class="wrap"><div class="tag">엘컴화인 MES</div><h1>{title}</h1>{f'<h2>{sub}</h2>' if sub else ''}<ul>{li}</ul>{f'<div class="foot">{foot}</div>' if foot else ''}</div></body></html>"""
    p = CARDS / f"{name}.html"
    p.write_text(html, encoding="utf-8")
    return p


def show_card(browser, d: Path, path: Path, sec: float):
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(d), record_video_size={"width": W, "height": H})
    page = ctx.new_page()
    page.goto(path.as_uri())
    page.wait_for_timeout(int(sec * 1000))
    ctx.close()


# ── 구간들 ─────────────────────────────────────────────────────────────
@segment("00", "타이틀")
def seg00(b, d):
    show_card(b, d, card("title", "엘컴화인 MES", "Job · Lot · Roll 계보 기반 생산관리",
                         ["출하 롤 하나에서 원재료 LOT 까지"], "시연 영상 · 화면의 데이터는 전부 (예시)"), 3.5)


@segment("01", "로그인")
def seg01(b, d):
    s = Vid(b, "admin", video_dir=d)
    s.page.goto(BASE + "/login")
    s.page.wait_for_load_state()
    s.cap("① 로그인 — 관리자 계정 · Web 채널. 역할과 상태는 요청마다 DB 에서 읽는다 (쿠키에 담지 않는다)")
    s.dwell(1.5)
    s.type_in("input[name=login_id]", "admin")
    pw = s.page.locator("input[name=password]")
    assert pw.get_attribute("type") == "password", "비밀번호 칸이 type=password 가 아니다"
    s.move_to(pw)
    pw.click()
    pw.fill(lib.get_settings().seed_password)          # 가려진 칸 — 값은 영상에 보이지 않는다
    s.pause(0.8)
    s.submit_slow("form#login-form", "로그인")
    s.cap("① 메인 — 묶음 4 · 대메뉴 12 · 중메뉴 32. 왼쪽 메뉴는 이 역할의 권한 표(DB)로 그려진다")
    s.dwell(3)
    S["seg01_url"] = s.page.url
    s.finish()


@segment("02", "기준정보")
def seg02(b, d):
    s = Vid(b, "admin", video_dir=d)
    s.login()
    s.cap("② 기준정보 관리 — 품목 · 고객 · 공정 · 설비 · 불량코드")
    s.menu("/bas/items", 2)
    # 시연용 제품 품목 하나 — 뒤의 작업지시가 이 품목을 가리킨다(끝에 지운다)
    form = "form.form-grid[action='/bas/items']"
    s.cap("② 품목 등록 — 시연용 제품 하나 (코드 VID-FG-01 · 이름에 (예시))")
    s.type_in(f"{form} [name=item_code]", f"{PREFIX}FG-01")
    s.type_in(f"{form} [name=item_name]", f"시연 제품 {MARK}")
    s.select(f"{form} [name=item_type]", "제품")
    s.type_in(f"{form} [name=spec]", "600mm (예시)")
    s.type_in(f"{form} [name=unit]", "m")
    res = s.submit_slow(form)
    assert res["popup"] and not res["popup"]["warn"], f"품목 등록 실패: {res}"
    s.dwell(1.2)
    s.ok()
    s.cap("② 인쇄 기준 관리 — 판사양 · 아니록스 · 잉크조성 (조성 행과 목표 Lab 값)")
    s.menu("/prt/plates", 2.5)
    s.page.mouse.wheel(0, 300); s.pause(1.2)
    s.menu("/prt/anilox", 2.5)
    s.menu("/prt/inks", 2.5)
    s.page.mouse.wheel(0, 300); s.pause(1.5)
    s.finish()


@segment("03", "작업지시")
def seg03(b, d):
    s = Vid(b, "admin", video_dir=d)
    s.login()
    s.cap("③ 작업지시 등록 — Job 번호는 채번 규칙(sys_number_rule)이 저장할 때 자동으로 만든다")
    s.menu("/job/orders", 2)
    form = "form.form-grid[action='/job/orders']"
    s.page.locator(form).scroll_into_view_if_needed(); s.pause(0.8)

    def opt(name, text):
        return s.page.locator(f"{form} select[name={name}] option", has_text=text).first.get_attribute("value")

    s.select(f"{form} [name=item_id]", opt("item_id", f"{PREFIX}FG-01"))
    s.select(f"{form} [name=customer_id]", opt("customer_id", "EX-CU-01"))
    s.select(f"{form} [name=plate_spec_id]", opt("plate_spec_id", "EX-PL-01"))
    s.select(f"{form} [name=anilox_id]", opt("anilox_id", "EX-AN-01"))
    s.select(f"{form} [name=ink_formula_id]", opt("ink_formula_id", "EX-INK-01"))
    s.select(f"{form} [name=equipment_id]", opt("equipment_id", "EX-EQ-01"))
    s.type_in(f"{form} [name=order_qty]", "3000")
    s.page.locator(f"{form} [name=due_date]").fill((date.today() + timedelta(days=7)).isoformat()); s.pause(0.5)
    s.type_in(f"{form} [name=note]", f"시연 {MARK}")
    res = s.submit_slow(form)
    row = conn.q1("select job_no from job j join item i on i.item_id = j.item_id where i.item_code = %s order by job_id desc", (f"{PREFIX}FG-01",))
    assert row and res["popup"] and not res["popup"]["warn"], f"작업지시 등록 실패: {res}"
    S["job_no"] = row["job_no"]
    s.cap(f"③ 등록 완료 — Job {S['job_no']} (J + 날짜 + 일련번호). 같은 트랜잭션에서 번호와 행이 함께 만들어진다")
    s.dwell(2)
    s.ok()
    s.page.mouse.wheel(0, -2000); s.pause(1)
    s.cap("③ 작업지시서 출력 — 바코드(Code128)는 인라인 SVG. 현장은 이 바코드를 스캔해 작업을 시작한다")
    s.click("a:has-text('작업지시서 출력')", nav=True)
    s.dwell(3)
    s.finish()


@segment("04", "POP-인쇄")
def seg04(b, d):
    s = Vid(b, "field", device="pop", video_dir=d)
    s.login()
    s.cap("④ 현장 POP 채널 — 현장 계정. 큰 글씨 · 스캔칸이 포커스를 가진다 (스캐너 = 키보드 입력 + Enter)")
    s.go("/pop/work", 2)
    s.cap(f"④ 작업지시서 바코드 스캔 → Job {S['job_no']} 의 시작 칸이 열린다")
    r = s.scan_slow(S["job_no"])
    assert r["focus_on_scan"], f"작업 실적 화면의 포커스가 스캔칸이 아님 {r}"
    s.dwell(1.5)
    start = "form[action='/pop/work/start']"
    assert s.page.locator(start).count(), "작업 시작 폼이 없음"
    s.cap("④ 작업 시작 — 실적(work_result) 한 줄이 '진행' 으로 생긴다")
    res = s.submit_slow(start)
    w = conn.q1("select work_result_id from work_result w join job j on j.job_id = w.job_id where j.job_no = %s and w.status = '진행' order by 1 desc", (S["job_no"],))
    assert w and res["popup"] and not res["popup"]["warn"], f"작업 시작 실패: {res}"
    S["work_id"] = w["work_result_id"]
    s.dwell(1.5)
    s.ok()
    s.cap("④ 자재 투입 — 원재료 LOT 라벨을 스캔한다. 입고검사 '합격' LOT 만 받는다")
    s.click(f".work-card:has-text('실적 {S['work_id']}') a:has-text('자재 투입')", nav=True)
    s.dwell(1.5)
    lot = conn.q1("select lot_no from material_lot where insp_status = '합격' and lot_no like 'M%%' order by material_lot_id desc limit 1")["lot_no"]
    S["lot_no"] = lot
    r = s.scan_slow(lot)
    k = conn.q1("select count(*) as n from material_input mi join material_lot l on l.material_lot_id = mi.material_lot_id where mi.work_result_id = %s and l.lot_no = %s", (S["work_id"], lot))["n"]
    assert k == 1, f"투입 스캔이 DB 에 없음 {r}"
    s.cap(f"④ 투입 LOT {lot} 기록 — 작업 종료 때 이 LOT 마다 계보 '투입' 한 줄이 생긴다")
    s.dwell(2)
    s.ok()
    s.click("a:has-text('작업 실적으로')", nav=True)
    fin = f"form[action='/pop/work/{S['work_id']}/finish']"
    s.cap("④ 작업 종료 — 실적 수량·길이·폭을 넣으면 인쇄 롤 1개 + 계보 '투입' 행이 한 트랜잭션으로 만들어진다")
    s.page.locator(fin).scroll_into_view_if_needed(); s.pause(0.6)
    s.type_in(f"{fin} [name=output_qty]", "1500")
    s.type_in(f"{fin} [name=length_m]", "1500")
    s.type_in(f"{fin} [name=width_mm]", "600")
    res = s.submit_slow(fin)
    roll = conn.q1("select roll_no from roll where work_result_id = %s", (S["work_id"],))
    assert roll and res["popup"] and not res["popup"]["warn"], f"작업 종료 실패: {res}"
    S["print_roll"] = roll["roll_no"]
    s.cap(f"④ 인쇄 롤 {S['print_roll']} 생성 — 롤 번호도 채번 규칙(R + 날짜 + 일련)")
    s.dwell(2)
    s.ok()
    s.cap("④ 롤 라벨 — 롤마다 Code128 바코드. 다음 공정은 이 라벨을 스캔한다")
    s.click("a:has-text('라벨 인쇄')", nav=True)
    s.dwell(3)
    s.finish()


@segment("05", "슬리팅")
def seg05(b, d):
    s = Vid(b, "field", device="pop", video_dir=d)
    s.login()
    s.cap("⑤ 슬리팅 (1 → N) — 인쇄 롤 라벨을 스캔해 3개로 나눈다. 계보에는 부모 → 자식 한 줄씩만 남는다")
    s.go("/rll/slitting", 2)
    r = s.scan_slow(S["print_roll"])
    assert r["focus_on_scan"] and s.page.locator("form#slit-form").count(), f"슬리팅 폼이 안 열림 {r}"
    s.dwell(1.2)
    s.type_in("form#slit-form [name=count]", "3")
    s.type_in("form#slit-form [name=widths_mm]", "200,200,200")
    res = s.submit_slow("form#slit-form")
    rows = conn.q("""select c.roll_no from roll_genealogy g join roll c on c.roll_id = g.child_roll_id join roll p on p.roll_id = g.parent_roll_id
                      where p.roll_no = %s and g.relation = '슬리팅' order by c.roll_id""", (S["print_roll"],))
    S["slit_rolls"] = [x["roll_no"] for x in rows]
    assert len(S["slit_rolls"]) == 3 and res["popup"] and not res["popup"]["warn"], f"슬리팅 실패 {res} {S['slit_rolls']}"
    s.cap(f"⑤ 슬리팅 롤 3개 {' · '.join(S['slit_rolls'])} — 라벨 3장이 바로 나온다. 부모 롤은 '소진' 으로 바뀐다")
    s.dwell(1.5)
    s.ok()
    s.page.locator("#made").scroll_into_view_if_needed(); s.dwell(3)
    s.finish()


@segment("06", "품질검사")
def seg06(b, d):
    s = Vid(b, "qc", video_dir=d)
    s.login()
    s.cap("⑥ 품질 검사 — 품질 계정. 슬리팅 롤을 스캔해 ΔE · 판정을 등록한다 (최신 판정이 그 롤의 판정)")
    s.go("/qua/inspections", 2)
    form = "form#inspection-form"
    for i, (no, de) in enumerate(zip(S["slit_rolls"][:2], ("0.8", "1.1")), 1):
        r = s.scan_slow(no)
        opened = s.page.locator(f"{form} [name=roll_no]").count() and s.page.locator(f"{form} [name=roll_no]").input_value() == no
        assert opened, f"롤 {no} 스캔 뒤 검사 폼이 안 열림 {r}"
        s.cap(f"⑥ 롤 {no} — ΔE {de} · 합격")
        s.dwell(0.8)
        s.type_in(f"{form} [name=delta_e]", de)
        s.select(f"{form} [name=result]", "합격")
        s.type_in(f"{form} [name=note]", f"시연 {MARK}")
        res = s.submit_slow(form)
        got = conn.q1("select i.result from inspection i join roll r on r.roll_id = i.roll_id where r.roll_no = %s order by inspection_id desc", (no,))
        assert got and got["result"] == "합격" and res["popup"] and not res["popup"]["warn"], f"검사 등록 실패 {res}"
        s.dwell(1.2)
        if i == 1:
            s.ok()
            s.cap("⑥ 알림을 닫으면 포커스는 스캔칸으로 돌아온다 — 두 번째 롤을 바로 스캔")
            s.dwell(1)
    s.cap("⑥ 검사 결과 2건 등록 — 불합격 롤은 출하 스캔에서 422 로 막힌다 (D-17)")
    s.ok()
    s.page.mouse.wheel(0, 500); s.dwell(2.5)
    s.finish()


@segment("07a", "출하등록")
def seg07a(b, d):
    # 출하 등록·롤 스캔은 생산·현장 역할의 입력이다(관리자의 SHP 권한은 '입력 (승인)' = 승인만). 생산 계정으로 Web 채널에서 한다
    s = Vid(b, "prod", video_dir=d)
    s.login()
    s.cap("⑦ 출하 등록 — 생산 계정. 출하 LOT 하나는 한 Job 의 롤만 담는다 (관리자는 승인만 한다)")
    s.go("/shp/shipments", 2)
    form = "form#shipment-form"
    s.page.locator(form).scroll_into_view_if_needed(); s.pause(0.6)
    s.type_in(f"{form} [name=job_no]", S["job_no"])
    s.type_in(f"{form} [name=note]", f"시연 {MARK}")
    res = s.submit_slow(form)
    row = conn.q1("select shipment_no from shipment s join job j on j.job_id = s.job_id where j.job_no = %s order by shipment_id desc", (S["job_no"],))
    assert row and res["popup"] and not res["popup"]["warn"], f"출하 등록 실패 {res}"
    S["shipment_no"] = row["shipment_no"]
    s.cap(f"⑦ 출하 LOT {S['shipment_no']} 등록 — 이제 롤 라벨을 스캔해 담는다")
    s.dwell(1.5)
    s.ok()
    s.page.mouse.wheel(0, -2000); s.pause(0.8)
    for i, no in enumerate(S["slit_rolls"][:2], 1):
        r = s.scan_slow(no)
        n = conn.q1("""select count(*) as n from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id join shipment sh on sh.shipment_id = g.child_shipment_id
                        where r.roll_no = %s and sh.shipment_no = %s""", (no, S["shipment_no"]))["n"]
        assert n == 1, f"출하 롤 스캔 {no} 계보 {n}행 {r}"
        s.cap(f"⑦ 롤 {no} 담김 — 계보에 롤 → 출하 LOT '출하' 한 줄" + (" (알림이 떠 있어도 다음 스캔을 받는다)" if i == 1 else ""))
        s.dwell(1.8)
    s.ok()
    s.dwell(2)
    s.finish()


@segment("07b", "출하승인-COA")
def seg07b(b, d):
    s = Vid(b, "admin", video_dir=d)
    s.login()
    s.cap("⑦ 출하 승인 — 관리자만. 승인하면 COA 번호가 채번되고 그 뒤에는 바꿀 수 없다")
    s.go("/shp/approvals", 2)
    form = f"form[action='/shp/approvals/{S['shipment_no']}/approve']"
    assert s.page.locator(form).count(), "승인 대기 목록에 출하 LOT 이 없음"
    res = s.submit_slow(form)
    row = conn.q1("select status, coa_no from shipment where shipment_no = %s", (S["shipment_no"],))
    assert row["status"] == "승인" and row["coa_no"] and res["popup"] and not res["popup"]["warn"], f"승인 실패 {res} {row}"
    S["coa_no"] = row["coa_no"]
    s.cap(f"⑦ 승인 완료 — COA {S['coa_no']}")
    s.dwell(2)
    s.ok()
    s.cap("⑦ COA — 담긴 롤과 검사값(ΔE·판정)이 그대로 들어간다. 검사가 없는 롤은 '미수집' 으로 적는다")
    s.menu("/shp/coa", 1.5)
    s.click(f"tr:has-text('{S['shipment_no']}') a:has-text('COA 출력')", nav=True)
    s.dwell(3.5)
    s.finish()


@segment("08", "LOT추적")
def seg08(b, d):
    s = Vid(b, "admin", video_dir=d)
    s.login()
    s.cap("⑧ LOT 추적 — 출하 LOT 번호에서 역방향으로. roll_genealogy 를 거슬러 올라가는 조회일 뿐, 아무 테이블에도 쓰지 않는다")
    s.go("/trc/trace", 2)
    assert s.active()["scan"], "추적 화면의 포커스가 번호칸이 아님"
    s.page.keyboard.type(S["shipment_no"], delay=35); s.pause(0.6)
    s.click("button:has-text('역방향 추적')", nav=True)
    txt = s.text()
    need = [S["lot_no"], S["print_roll"], *S["slit_rolls"][:2]]
    miss = [x for x in need if x not in txt]
    assert not miss, f"역방향 추적 화면에 없는 번호 {miss}"
    s.cap(f"⑧ 출하 {S['shipment_no']} ← 슬리팅 롤 ← 인쇄 롤 {S['print_roll']} ← 원재료 LOT {S['lot_no']} — 출하 롤 하나에서 원재료 LOT 까지")
    s.dwell(3.5)
    s.page.mouse.wheel(0, 400); s.dwell(2.5)
    s.cap(f"⑧ 정방향 — 원재료 LOT {S['lot_no']} 에서 내려가면 그 LOT 이 들어간 롤과 출하가 전부 나온다")
    s.go("/trc/trace", 1)
    s.page.keyboard.type(S["lot_no"], delay=35); s.pause(0.6)
    s.click("button:has-text('정방향 추적')", nav=True)
    assert S["shipment_no"] in s.text(), "정방향 추적에 출하 LOT 이 없음"
    s.dwell(3)
    s.page.mouse.wheel(0, 500); s.dwell(2)
    s.finish()


@segment("09a", "실적현황")
def seg09a(b, d):
    s = Vid(b, "admin", video_dir=d)
    s.login()
    s.cap("⑨ 실적 현황 — 생산 · 품질 · 납기 집계. 집계 SQL 은 stats 한 곳, 캐시 테이블 없음")
    s.menu("/sta/summary", 3)
    s.page.mouse.wheel(0, 450); s.dwell(2.5)
    s.finish()


@segment("09b", "현황판")
def seg09b(b, d):
    s = Vid(b, "admin", device="board", video_dir=d)
    s.login()
    s.cap("⑨ 현황판 채널 — 메뉴 없음 · 큰 글씨 · 자동 새로고침 (헤더에 마지막 갱신)")
    s.go("/sta/board", 4)
    s.page.mouse.wheel(0, 300); s.dwell(2)
    s.finish()


@segment("09c", "모바일")
def seg09c(b, d):
    s = Vid(b, "qc", device="mobile", viewport={"width": 390, "height": 720}, is_mobile=True, video_dir=d)
    s.login()
    s.cap("⑨ 모바일 채널 (폭 390) — 한 단 · 본문이 메뉴보다 먼저. 같은 추적을 손안에서")
    s.go(f"/trc/trace/backward?no={S['shipment_no']}", 3)
    s.page.mouse.wheel(0, 500); s.dwell(2.5)
    s.finish()


@segment("10a", "테스트-422")
def seg10a(b, d):
    s = Vid(b, "field", device="pop", video_dir=d)
    s.login()
    s.cap("⑩ 테스트 ① — 없는 번호를 스캔하면? 화면이 사라지지 않고 422 로 같은 화면이 다시 그려져야 한다")
    s.go("/pop/work", 2)
    statuses = []
    s.page.on("response", lambda r: statuses.append(r.status) if r.request.is_navigation_request() else None)
    r = s.scan_slow("VID-NOPE-0000")
    st = statuses[-1] if statuses else None
    has_scan = s.page.locator("[data-scan]").count()
    assert st == 422 and has_scan and "/pop/work" in s.page.url, f"없는 번호 스캔: HTTP {st} · 스캔칸 {has_scan} · {r}"
    s.cap(f"⑩ 결과 — HTTP {st} · 주소 {s.page.url.replace(BASE, '')} · 스캔칸 유지, 오류는 큰 글씨 → 다음 스캔을 막지 않는다 ✔")
    s.dwell(4)
    s.finish()


@segment("10b", "테스트-403")
def seg10b(b, d):
    s = Vid(b, "field", video_dir=d)
    s.login()
    s.cap("⑩ 테스트 ② — 현장 계정이 출하 승인을 시도하면? 승인 버튼은 비활성, 요청을 억지로 보내도 서버가 403 으로 막아야 한다")
    s.go("/shp/approvals", 2.5)
    btn = s.page.locator(f"form[action='/shp/approvals/{S['shipment_no']}/approve'] button, form[action$='/approve'] button").first
    if btn.count():
        s.move_to(btn)
        assert btn.is_disabled(), "현장 계정에 승인 버튼이 활성이다"
        s.cap("⑩ 승인 버튼이 비활성(권한 표: 현장의 출하 = 입력이지만 승인 F-SHP-05 는 관리자만). 이제 요청을 직접 보내 본다")
        s.dwell(2.5)
    target = conn.q1("select shipment_no from shipment where status = '등록' order by shipment_id desc limit 1")["shipment_no"]
    statuses = []
    s.page.on("response", lambda r: statuses.append(r.status) if r.request.is_navigation_request() else None)
    with s.page.expect_navigation():
        s.page.evaluate("""(no) => { const f = document.createElement('form'); f.method = 'post'; f.action = '/shp/approvals/' + no + '/approve';
                             document.body.appendChild(f); f.submit(); }""", target)
    s.page.wait_for_load_state()
    st = statuses[-1] if statuses else None
    still = conn.q1("select status from shipment where shipment_no = %s", (target,))["status"]
    assert st == 403 and still == "등록", f"현장 계정의 승인 POST: HTTP {st} · 출하 상태 {still}"
    s.cap(f"⑩ 결과 — POST /shp/approvals/{target}/approve → HTTP {st} · 출하 상태 그대로 '{still}' ✔ (권한은 쓰기 엔드포인트마다 require_fn)")
    s.dwell(4)
    s.finish()


@segment("10c", "테스트-요약")
def seg10c(b, d):
    show_card(b, d, card("tests", "자동 검증 결과", "progress.md 최종 보고 (2026-10-03)",
                         [f"<b>make gate-full</b> — 수용 게이트 G-01 ~ G-22 {GATE['gate']}",
                          f"<b>pytest</b> — {GATE['pytest']}",
                          f"<b>QA 리포트 3종</b> — {GATE['defects']}",
                          "<b>브라우저 한 바퀴(G-22)</b> — 16단계 · 스캔 22회 · 우회 0 · 유실 0"],
                         "검사 도구는 기대값을 설계도에서 직접 읽는다 (tools/design_doc.py)"), 6)


@segment("11", "마무리")
def seg11(b, d):
    show_card(b, d, card("end", "엘컴화인 MES", "출하 롤 하나에서 원재료 LOT 까지",
                         [f"채널 <b>{SCALE['channels']}</b> · 중메뉴 <b>{SCALE['menus']}</b> · 기능 <b>{SCALE['functions']}</b> · 테이블 <b>{SCALE['tables']}</b>",
                          "계보는 roll_genealogy 한 테이블 — 부모 → 자식 한 줄씩"],
                         "PostgreSQL 17 · FastAPI · 관리자 Web / 현장 POP / 모바일 / 현황판"), 3.5)


SEGS = [seg00, seg01, seg02, seg03, seg04, seg05, seg06, seg07a, seg07b, seg08, seg09a, seg09b, seg09c, seg10a, seg10b, seg10c, seg11]


# ── ffmpeg ──
def probe(path: Path) -> dict:
    """길이·해상도·코덱 — `ffmpeg -i` 의 머리말에서 읽는다(ffprobe 가 없는 정적 바이너리에서도 된다)."""
    import re
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    txt = r.stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", txt)
    dur = round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), 2) if m else None
    v = re.search(r"Video: (\w+).*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", txt)
    return {"format": {"duration": dur, "size": path.stat().st_size},
            "video": {"codec": v[1], "width": int(v[2]), "height": int(v[3]), "fps": float(v[4])} if v else None}


def encode_segment(webms: list[Path], out: Path) -> None:
    """구간의 webm(들)을 1280×720 · H.264 · 30fps mp4 로. 모바일처럼 작은 화면은 가운데에 두고 어두운 여백."""
    vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0f172a,fps=30,format=yuv420p"
    if len(webms) == 1:
        inputs = ["-i", str(webms[0])]
        filt = ["-vf", vf]
    else:
        inputs = sum((["-i", str(p)] for p in webms), [])
        chain = "".join(f"[{i}:v]{vf}[v{i}];" for i in range(len(webms))) + "".join(f"[v{i}]" for i in range(len(webms))) + f"concat=n={len(webms)}:v=1:a=0[v]"
        filt = ["-filter_complex", chain, "-map", "[v]"]
    cmd = [FFMPEG, "-y", "-v", "error", *inputs, *filt, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30", "-pix_fmt", "yuv420p", "-an", str(out)]
    subprocess.run(cmd, check=True)


def assemble() -> dict:
    parts: list[Path] = []
    for seg in SEGMENTS:
        webms = [Path(p) for p in seg["webms"]]
        if not webms:
            continue
        out = OUT / f"{seg['no']}-{seg['name']}.mp4"
        encode_segment(webms, out)
        seg["mp4"] = str(out)
        seg["seconds"] = round(float(probe(out)["format"]["duration"]), 1)
        parts.append(out)
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    final = OUT / "엘컴화인_MES_시연.mp4"
    subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-r", "30", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(final)], check=True)
    return {"final": str(final), **probe(final)}


def leftovers() -> dict:
    return {
        "item": conn.q1("select count(*) as n from item where item_code like 'VID-%'")["n"],
        "job": conn.q1("select count(*) as n from job j join item i on i.item_id = j.item_id where i.item_code like 'VID-%'")["n"],
        "roll": conn.q1("select count(*) as n from roll r join job j on j.job_id = r.job_id join item i on i.item_id = j.item_id where i.item_code like 'VID-%'")["n"],
        "shipment": conn.q1("select count(*) as n from shipment s join job j on j.job_id = s.job_id join item i on i.item_id = j.item_id where i.item_code like 'VID-%'")["n"],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True)
    print("시작 전 VID- 잔여 정리:", cleanup(PREFIX))
    with sync_playwright() as p:
        b = p.chromium.launch(slow_mo=SLOW_MO)
        for fn in SEGS:
            run_segment(b, fn)
            if BLOCKED and fn.seg[0] in ("02", "03", "04", "05") :
                print("앞 구간이 막혀 뒤 흐름을 이어갈 수 없다 — 남은 구간은 건너뛴다(가짜 화면을 만들지 않는다)")
                break
        b.close()
    report = {"segments": SEGMENTS, "blocked": BLOCKED, "state": S, "ffmpeg": FFMPEG_SOURCE}
    try:
        report["video"] = assemble()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        report["video_error"] = f"{type(exc).__name__}: {exc}"
    if not KEEP:
        report["cleanup"] = cleanup(PREFIX)
        report["leftovers"] = leftovers()
    (WORK / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "segments"}, ensure_ascii=False, indent=1))
    for seg in SEGMENTS:
        print(f"  {seg['no']:>3} {seg['name']:<10} {seg['status']:<8} {seg.get('seconds', '-'):>6}s {seg['note']}")


if __name__ == "__main__":
    main()
