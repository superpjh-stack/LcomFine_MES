"""QA1 — G-02 기능 94 + 6 의 1:1 · G-03 화면 32 + 공통 3.  (goal.md §2.1 · §3.3)

`check_trace`(라우트 표 대조) · `check_routes`(관리자로 화면 열기)와 다른 방법이다: 한 Job 을 **화면이 부르는 API 로** 끝까지 흘리고
기능 94개가 전부 불렸는지, 쓰기 54개가 계약의 「쓰는 테이블」 에 행을 남겼는지(SQL), 읽기 40개와 화면 32개에 그 값이 보이는지 본다.
기대값(12 · 32 · 94 · 대메뉴별 수)은 설계도를 이 테스트 쪽 파서로 읽은 것이다.
"""
import re

import pytest

from test_qa1_support import (BATCH_FNS, HTML, IA, SCREEN_FNS, SCREEN_PATHS, WRITE_FNS, anon, build_world, client, cs, drop_world,
                              failed_steps)


@pytest.fixture(scope="module")
def world():
    flow = build_world(batch=True)
    try:
        yield flow
    finally:
        drop_world(flow)


# ── 설계도 ↔ 계약 ───────────────────────────────────────────────────────
def test_design_doc_counts():
    """설계도 §5: 대메뉴 12 · 중메뉴 32 · 기능 94 (goal.md §9 의 정규식)."""
    assert (len(IA), sum(len(m["subs"]) for m in IA), sum(m["count"] for m in IA)) == (12, 32, 94)
    assert [m["count"] for m in IA] == [20, 12, 7, 8, 8, 5, 7, 6, 7, 3, 4, 7]


def test_contract_is_one_line_per_function():
    """계약 100줄 = 화면 94 + 배치 6. 대메뉴별 수와 중메뉴 이름이 설계도와 같다. ID·API 중복 0."""
    assert (len(SCREEN_FNS), len(BATCH_FNS)) == (94, 6)
    assert [sum(1 for f in SCREEN_FNS if f.menu == m["menu"]) for m in IA] == [m["count"] for m in IA]
    assert {(f.menu, f.screen) for f in SCREEN_FNS} == {(m["menu"], s) for m in IA for s in m["subs"]}
    ids, apis = [f.id for f in SCREEN_FNS + BATCH_FNS], [f.api for f in SCREEN_FNS + BATCH_FNS]
    assert len(set(ids)) == 100 and len(set(apis)) == 100
    assert sum(f.is_write for f in SCREEN_FNS) == 54 and len(SCREEN_PATHS) == 32


# ── 기능 94: 실제로 부르고, 쓰기는 쓰는 테이블을 확인한다 ────────────────
@pytest.mark.parametrize("fn", SCREEN_FNS, ids=lambda f: f.id)
def test_function_works_through_its_api(world, fn):
    steps = world.by_fn().get(fn.id, [])
    assert steps, f"{fn.id} {fn.name} 을(를) 부르지 못했다 — 앞 단계 오류 {world.stage_errors}"
    assert not [s for s in steps if s.status in (404, 405) and not s.call.startswith("SQL")], f"{fn.api} 가 등록되지 않았다"
    assert not failed_steps(world, fn.id), failed_steps(world, fn.id)
    if fn.is_write:      # 계약의 「쓰는 테이블」 을 SQL 로 다시 읽은 확인이 하나 이상 있어야 한다
        assert fn.tables and any(s.evidence for s in steps), f"{fn.id} 의 쓰기 확인이 없다"


@pytest.mark.parametrize("fn", WRITE_FNS, ids=lambda f: f.id)
def test_write_function_leaves_change_log(world, fn):
    """쓰기 기능 54 — 성공한 호출마다 접근 로그(구분 `변경`)에 그 기능 ID · 그 사용자로 한 줄이 남는다 (function-list §1 공통 규칙 · G-18)."""
    assert world.audit.get(fn.id), f"{fn.id} 의 성공한 쓰기가 없다"
    assert all(world.audit[fn.id]), f"{fn.id}: 성공한 호출 {len(world.audit[fn.id])} 건 중 로그 없는 것 {world.audit[fn.id].count(False)}"


def test_flow_has_no_stage_error(world):
    assert world.stage_errors == []


def test_flow_leaves_the_design_doc_genealogy(world):
    """설계도 §3 예시의 화살표 10개(투입 3 · splice 2 · 슬리팅 3 · 출하 2) + 1:1 후가공 롤 한 벌(투입 1 · 후가공 1)."""
    assert world.genealogy() == {"투입": 4, "splice": 2, "후가공": 1, "슬리팅": 3, "출하": 2}


@pytest.mark.parametrize("fn", BATCH_FNS, ids=lambda f: f.id)
def test_batch_command_runs(world, fn):
    """이관 배치 6 — `python -m lcomfine.migration <명령>` 을 Q1 사본 폴더로 실제로 돌린다."""
    assert fn.id in world.batch, f"{fn.id} 미도달 — {world.stage_errors}"
    ok, detail = world.batch[fn.id]
    assert ok, detail


# ── 화면 32 + 공통 3 ────────────────────────────────────────────────────
@pytest.mark.parametrize("path", list(SCREEN_PATHS), ids=lambda p: p)
def test_screen_is_200_and_shows_real_data(world, path):
    """브라우저처럼 열어 200 · placeholder 아님 · 방금 API 로 만든 값이 보인다."""
    params, needles = cs.screen_probes(world.v, world.tag)[path]
    assert all(x is not None for x in list(params.values()) + needles), f"앞 단계 실패로 값이 없다 — {world.stage_errors}"
    r = client("관리자").get(path, params=params, headers=HTML)
    assert r.status_code == 200, r.text[:300]
    assert not cs.is_placeholder(r.text), "placeholder(미구현) 화면이다"
    assert not [n for n in needles if str(n) not in r.text], f"화면에 없다: {[n for n in needles if str(n) not in r.text]}"


def test_common_screens():
    assert client("관리자").get("/", headers=HTML).status_code == 200
    assert anon().get("/login", headers=HTML).status_code == 200
    assert client("관리자").get("/error", headers=HTML).status_code == 200
    r = client("관리자").get("/q1-no-such-screen", headers=HTML)
    assert r.status_code == 404 and "대상을 찾을 수 없습니다" in r.text


@pytest.mark.parametrize("role", ["관리자", "생산", "품질", "현장"])
def test_every_role_opens_main(role):
    assert client(role).get("/", headers=HTML).status_code == 200


# ── 응답의 모양 (api-contract §2) ───────────────────────────────────────
def test_browser_write_success_is_303_with_one_time_flash(world):
    """브라우저 폼의 쓰기 성공 = 303 → 원래 화면 + 알림 **한 번**. 같은 화면을 다시 열면 알림이 없다."""
    import json
    import re

    A = client("관리자")
    r = A.post("/bas/customers", data={"customer_code": f"{world.tag}-FL", "customer_name": f"{world.tag} 알림 (예시)"},
               headers={**HTML, "referer": "http://testserver/bas/customers"})
    assert r.status_code == 303 and r.headers["location"] == "/bas/customers"

    def flash(html: str):
        m = re.search(r'id="flash-data">(.*?)</script>', html, re.S)
        return json.loads(m.group(1)) if m else None

    first, second = flash(A.get("/bas/customers", headers=HTML).text), flash(A.get("/bas/customers", headers=HTML).text)
    assert first and first["kind"] == "ok" and "등록" in first["message"]
    assert second is None


def test_scan_screens_have_a_focused_scan_box(world):
    """계약 문장이 「스캔칸이 포커스를 잡는다」 고 한 화면(F-POP-03 · F-MAT-08 · F-RLL-03 · F-SHP-04)과 그 밖의 스캔 화면 —
    POP 채널로 열면 `data-scan autofocus` 입력칸이 정확히 하나 있다(포커스를 두 곳이 다투지 않는다)."""
    v = world.v
    work = client("현장").post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]     # 투입 스캔은 진행 중 실적에 한다
    pages = {
        "/pop/work": {}, "/mat/inputs": {"work_id": work}, "/rll/finishing": {}, "/shp/shipments": {"no": v["ship1"]},
        "/pop/roll-labels": {}, "/mat/inspections": {}, "/mat/lots": {}, "/rll/slitting": {}, "/rll/history": {},
        "/qua/inspections": {},
    }
    bad = {}
    for path, params in pages.items():
        html = client("관리자").get(path, params={**params, "device": "pop"}, headers=HTML).text
        inputs = re.findall(r"<input[^>]*>", html)
        scan, focus = sum("data-scan" in i for i in inputs), sum(" autofocus" in i for i in inputs)
        if scan != 1 or focus != 1 or "ch-pop" not in html:
            bad[path] = {"data-scan": scan, "autofocus": focus, "ch-pop": "ch-pop" in html}
    assert bad == {}


def test_screens_render_with_sparse_data(world):
    """선택 항목을 전부 비운 Job(판사양·아니록스·잉크·설비 없음)과 길이·폭 없는 롤, 검사 없는 출하로도 화면·출력물이 열린다."""
    v, P, F, A = world.v, client("생산"), client("현장"), client("관리자")
    job = P.post("/job/orders", data={"item_id": str(v["item"]), "customer_id": str(v["customer"]), "order_qty": "10",
                                      "due_date": world.today}).json()["job_no"]
    assert "미수집" in A.get("/job/mapping", params={"no": job}, headers=HTML).text          # 롤이 없으면 미수집 (F-JOB-07)
    work = F.post("/pop/work/start", data={"job_no": job}).json()["work_id"]
    assert F.post("/mat/inputs", data={"work_id": str(work), "lot_no": v["lot2"]}).status_code == 200
    done = F.post(f"/pop/work/{work}/finish", data={"output_qty": "0"}).json()
    roll = done["roll_no"]
    ship = F.post("/shp/shipments", data={"job_no": job, "ship_date": world.today}).json()["shipment_no"]
    assert "미발행" in A.get("/shp/coa", params={"shipment_no": ship}, headers=HTML).text    # 미승인은 미발행 (F-SHP-06)
    assert F.post(f"/shp/shipments/{ship}/rolls", data={"roll_no": roll}).status_code == 200
    assert A.post(f"/shp/approvals/{ship}/approve").status_code == 200                       # 미검사 롤은 승인된다 (D-17)
    pages = {
        f"/job/orders?no={job}": job, f"/job/orders/{job}/print": "<svg", done["label_url"]: "<svg",
        f"/rll/history?no={roll}": roll, f"/rll/history/{roll}/label": "<svg", f"/shp/shipments?no={ship}": roll,
        f"/shp/coa/{ship}/print": "미수집", f"/trc/trace/backward?no={ship}": v["lot2"], f"/trc/trace/forward?no={roll}": ship,
        f"/qua/inspections?no={roll}": roll, "/pop/work": job, "/sta/board": "마지막 갱신",
    }
    bad = {}
    for url, needle in pages.items():
        r = A.get(url, headers=HTML)
        if r.status_code != 200 or needle not in r.text:
            bad[url] = (r.status_code, needle in r.text)
    assert bad == {}


# ── 화면 ↔ API 1:1 — 기능마다 그 API 로 가는 폼·링크가 화면에 있다 ──────
@pytest.fixture(scope="module")
def crawl(world) -> tuple[set[str], set[str]]:
    """네 역할로 화면들을 열어 (POST 폼의 action 경로들, GET 폼·링크의 경로들)을 모은다."""
    import html as htmlmod
    from urllib.parse import urlsplit

    v, F = world.v, client("현장")
    work = F.post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]                 # 진행 중 실적 (투입·종료·정지·폐기 폼)
    assert F.post("/mat/inputs", data={"work_id": str(work), "lot_no": v["lot1"]}).status_code == 200
    held = F.post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]                 # 정지 중 실적 (재개 폼)
    assert F.post("/pop/stops", data={"work_id": str(held), "stop_reason": "폼 확인 (예시)"}).status_code == 200
    spare = F.post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]                # 재고 롤 2개 (후가공·splice·슬리팅 폼)
    assert F.post("/mat/inputs", data={"work_id": str(spare), "lot_no": v["lot2"]}).status_code == 200
    stock1 = F.post(f"/pop/work/{spare}/finish", data={"output_qty": "1"}).json()["roll_no"]
    spare = F.post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]
    assert F.post("/mat/inputs", data={"work_id": str(spare), "lot_no": v["lot2"]}).status_code == 200
    stock2 = F.post(f"/pop/work/{spare}/finish", data={"output_qty": "1"}).json()["roll_no"]
    waiting = F.post("/mat/receipts", data={"item_code": v["raw_code"], "received_qty": "5"}).json()["lot_no"]   # 검사 대기 LOT
    ship = F.post("/shp/shipments", data={"job_no": v["job_no"], "ship_date": world.today}).json()["shipment_no"]  # 등록 출하 + 롤
    assert F.post(f"/shp/shipments/{ship}/rolls", data={"roll_no": v["fn2"]}).status_code == 200
    insp = cs.db1("select n.inspection_id from inspection n join roll r using (roll_id) where r.roll_no = %s", (v["s3"],))["inspection_id"]

    seeds = [(path, params) for path, (params, _) in cs.screen_probes(v, world.tag).items()]
    seeds += [(path, {"code": world.tag, "edit": v[key]}) for path, key in (
        ("/bas/items", "item"), ("/bas/customers", "customer"), ("/bas/processes", "process"), ("/bas/equipment", "equipment"),
        ("/bas/defect-codes", "defect"), ("/prt/plates", "plate"), ("/prt/anilox", "anilox"), ("/prt/inks", "ink"))]
    seeds += [
        ("/job/orders", {"no": v["job_no"]}), ("/job/mapping", {"no": v["job_no"]}), ("/pop/work", {"no": v["job_no"]}),
        ("/mat/inputs", {"work_id": work}), ("/pop/stops", {"work_id": work}), ("/pop/stops", {"work_id": held}),
        ("/mat/inspections", {"no": waiting}), ("/mat/lots", {"no": v["lot1"]}), ("/pop/roll-labels", {"no": v["p1"]}),
        ("/clr/records", {"job_no": v["job_no"], "edit": v["color"]}), ("/rll/finishing", {"rolls": stock1}),
        ("/rll/finishing", {"rolls": f"{stock1},{stock2}"}), ("/rll/slitting", {"no": stock1}), ("/rll/history", {"no": v["s1"]}),
        ("/qua/inspections", {"no": stock1}), ("/qua/inspections", {"edit": insp}), ("/qua/defect-stats", {}),
        ("/shp/shipments", {"no": ship}), ("/shp/approvals", {}), ("/shp/coa", {}), ("/trc/trace", {"q": v["lot1"]}),
        ("/sta/summary", {}), ("/sys/users", {"edit": v["user"]}),
    ]
    posts, gets = set(), set()
    for role in ("관리자", "생산", "품질", "현장"):
        for path, params in seeds:
            r = client(role).get(path, params=params, headers=HTML)
            if r.status_code != 200:
                continue
            for m in re.finditer(r"<form\b([^>]*)>", r.text):
                action = re.search(r'action="([^"]*)"', m.group(1))
                method = re.search(r'method="([^"]*)"', m.group(1))
                target = urlsplit(htmlmod.unescape(action.group(1))).path if action else path
                (posts if method and method.group(1).lower() == "post" else gets).add(target)
            for m in re.finditer(r'\b(href|formaction)="([^"]*)"', r.text):      # formaction 은 그 폼의 method 를 따른다(추적 화면은 GET)
                gets.add(urlsplit(htmlmod.unescape(m.group(2))).path)
                if m.group(1) == "formaction":
                    posts.add(urlsplit(htmlmod.unescape(m.group(2))).path)
    return posts, gets


def _matches(fn, paths: set[str]) -> bool:
    pattern = re.compile("^" + re.sub(r"\\\{\w+\\\}", "[^/?#]+", re.escape(fn.path)) + "$")
    return any(pattern.match(p) for p in paths)


def test_every_function_is_reachable_from_a_screen(crawl):
    """한 기능 = 화면/API 하나 (G-02). API 만 있고 화면에 그 폼·링크가 없으면 사용자는 그 기능을 쓸 수 없다(goal.md §1 「화면 조작만으로」).
    쓰기 54 는 그 API 로 보내는 POST 폼이, 읽기 40 은 그 주소로 가는 링크나 GET 폼이 화면에 있어야 한다."""
    posts, gets = crawl
    no_form = [f"{f.id} {f.api}" for f in WRITE_FNS if not _matches(f, posts)]
    no_link = [f"{f.id} {f.api}" for f in SCREEN_FNS if not f.is_write and not _matches(f, gets)]
    assert no_form == [] and no_link == []


def test_no_form_posts_outside_the_contract(crawl):
    """화면의 POST 폼은 전부 계약의 쓰기 기능으로 간다 (계약에 없는 쓰기 0). 로그아웃만 예외다."""
    posts, _ = crawl
    stray = sorted(p for p in posts if p != "/logout" and not any(_matches(f, {p}) for f in SCREEN_FNS))
    assert stray == []
