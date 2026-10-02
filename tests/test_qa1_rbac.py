"""QA1 — G-17 권한 48칸 전수.  기대값은 설계도 §6 표다 (goal.md §6 과 같은 표 · 입력 19 · 조회 24 · 없음 5).

역할 4 × 대메뉴 12 마다
    없음 = 메뉴 숨김 + 화면 403 + 읽기 403 + 쓰기 403
    조회 = 화면 200 + 그 대메뉴의 **모든** 쓰기 기능 403
    입력 = 쓰기 허용 (없는 키·빈 본문으로 두드려 404·422 가 나오면 권한은 통과한 것이다 — 아무것도 쓰지 않는다)
    괄호 조건 2개 — 자재·입고의 품질은 입고검사만 · 출하의 관리자는 승인만
`contracts/function-list.md` 의 기능 94개 전부(쓰기 54 · 읽기 40)를 역할 4개로 두드린다 — 표본이 아니라 전수.

권한 표를 바꿔 보는 검사는 **검사 전용 역할**(`sys_role` 한 행)로 한다. 시드 역할의 48칸은 건드리지 않고, 끝에 48칸이 그대로인지 확인한다.
"""
import pytest

from test_qa1_support import (ACCESS, FN, HTML, READ_FNS, ROLES, SCREEN_FNS, SCREEN_PATHS, WRITE_FNS, anon, build_world, client, cs,
                              drop_world, err, http)

CELLS = [(menu, role, cell) for menu, row in ACCESS["cells"].items() for role, cell in row.items()]
#: 괄호 없는 `입력` 칸의 역할이 다른 역할의 괄호 기능을 부르는 4건 — 설계도 문장으로는 정해지지 않고 D-14 가 403 으로 정했다
D14 = [(role, f) for role in ROLES for f in WRITE_FNS if cs.expected(ACCESS, role, f) == "d14"]


@pytest.fixture(scope="module")
def world():
    flow = build_world()
    try:
        yield flow
    finally:
        drop_world(flow)


# ── 기대값 자체 ─────────────────────────────────────────────────────────
def test_design_doc_is_48_cells():
    assert cs.access_counts(ACCESS) == {"전체": 48, "입력": 19, "조회": 24, "없음": 5}
    assert ROLES == ["관리자", "생산", "품질", "현장"] and len(ACCESS["cells"]) == 12


def test_expected_matrix_shape():
    """설계도에서 만든 기대값: 쓰기 54 × 역할 4 = 216 쌍 가운데 허용 84 · 403 128 · D-14 해석 4."""
    kinds = [cs.expected(ACCESS, role, f) for role in ROLES for f in WRITE_FNS]
    assert (len(kinds), kinds.count("allow"), kinds.count("deny"), kinds.count("d14")) == (216, 84, 128, 4)
    assert sorted((r, f.id) for r, f in D14) == [("생산", "F-MAT-03"), ("생산", "F-SHP-05"), ("현장", "F-MAT-03"), ("현장", "F-SHP-05")]


@pytest.mark.parametrize("menu,role,cell", CELLS, ids=[f"{m}×{r}" for m, r, _ in CELLS])
def test_db_cell_equals_design_doc(menu, role, cell):
    """DB `sys_permission` 의 그 칸 = 설계도 칸 (등급과 괄호)."""
    code = cs.role_logins()[role]["code"]
    menu_code = next(f.menu_code for f in SCREEN_FNS if f.menu == menu)
    row = cs.db1("select level, write_scope from sys_permission where role_code = %s and menu_code = %s", (code, menu_code))
    word = cell[cell.index("(") + 1: cell.rindex(")")].strip() if "(" in cell else ("일반" if cell.startswith("입력") else "")
    assert row == {"level": cell.split(" ")[0], "write_scope": word}


# ── 화면 · 메뉴 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", list(SCREEN_PATHS), ids=lambda p: p)
def test_screen_get(role, path):
    """없음 = 403 `접근 권한이 없습니다`, 그 밖 = 200."""
    r = client(role).get(path, headers=HTML)
    if ACCESS["cells"][SCREEN_PATHS[path]][role] == "없음":
        assert r.status_code == 403 and "접근 권한이 없습니다" in r.text
        err(client(role).get(path), 403, "forbidden")
    else:
        assert r.status_code == 200, r.text[:200]


@pytest.mark.parametrize("menu,role,cell", CELLS, ids=[f"{m}×{r}" for m, r, _ in CELLS])
def test_menu_hidden_only_when_none(menu, role, cell):
    """메인의 메뉴·바로가기 — `없음` 대메뉴의 화면 링크는 하나도 없고, 그 밖은 전부 있다."""
    home = client(role).get("/", headers=HTML).text
    mine = [p for p, m in SCREEN_PATHS.items() if m == menu]
    shown = [p for p in mine if f'href="{p}"' in home]
    assert shown == ([] if cell == "없음" else mine)


@pytest.mark.parametrize("menu,role,cell", [c for c in CELLS if c[2] != "없음"], ids=lambda x: str(x))
def test_menu_of_other_screens_also_hides_none(menu, role, cell):
    """메인만이 아니라 화면 안의 좌측 메뉴에서도 `없음` 대메뉴가 안 보인다 (그 역할이 열 수 있는 화면 하나에서 본다)."""
    path = next(p for p, m in SCREEN_PATHS.items() if m == menu)
    page = client(role).get(path, headers=HTML).text
    none_menus = [m for m, row in ACCESS["cells"].items() if row[role] == "없음"]
    leaked = [p for p, m in SCREEN_PATHS.items() if m in none_menus and f'href="{p}"' in page]
    assert leaked == []


# ── 기능 94 × 역할 4 ────────────────────────────────────────────────────
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("fn", READ_FNS, ids=lambda f: f.id)
def test_read_function(role, fn):
    r = client(role).request(fn.method, cs.sweep_path(fn))
    if cs.expected(ACCESS, role, fn) == "deny":
        err(r, 403, "forbidden")
    else:
        assert r.status_code in (200, 404, 422), f"{role} {fn.api} → {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("fn", WRITE_FNS, ids=lambda f: f.id)
def test_write_function(role, fn):
    """조회·없음 칸 = 403. 입력 칸 = 권한 통과(없는 키·빈 본문이라 404·422). 괄호 칸 = 그 기능만."""
    want = cs.expected(ACCESS, role, fn)
    r = client(role).request(fn.method, cs.sweep_path(fn))
    if want == "allow":
        assert r.status_code in (404, 422), f"{role} {fn.api} → {r.status_code} {r.text[:200]}"
    else:          # deny · d14 (D-14 가 403 으로 정했다 — 리포트의 「확인 필요」)
        body = err(r, 403, "forbidden")
        assert body["message"] == "접근 권한이 없습니다"


def test_bracket_conditions():
    """괄호 조건 2개 (goal.md G-17): 자재·입고의 품질은 **입고검사만** 입력 · 출하의 관리자는 **승인**."""
    mat = {f.id: cs.expected(ACCESS, "품질", f) for f in WRITE_FNS if f.menu == "자재 · 입고"}
    shp = {f.id: cs.expected(ACCESS, "관리자", f) for f in WRITE_FNS if f.menu == "출하"}
    assert mat == {"F-MAT-01": "deny", "F-MAT-03": "allow", "F-MAT-07": "deny"}
    assert shp == {"F-SHP-01": "deny", "F-SHP-02": "deny", "F-SHP-03": "deny", "F-SHP-05": "allow"}
    for fid, want in {**mat, **shp}.items():
        role = "품질" if fid.startswith("F-MAT") else "관리자"
        r = client(role).request("POST", cs.sweep_path(FN[fid]))
        assert (r.status_code == 403) == (want == "deny"), f"{role} {fid} → {r.status_code}"


@pytest.mark.parametrize("fn", SCREEN_FNS, ids=lambda f: f.id)
def test_anonymous_is_401(fn):
    """미로그인 = 401 `로그인이 필요합니다`. 브라우저 GET 은 `/login` 303. 순서는 401 → 403 → 422."""
    c = anon()
    body = err(c.request(fn.method, cs.sweep_path(fn)), 401, "unauthorized")
    assert body["message"] == "로그인이 필요합니다"
    r = c.request(fn.method, cs.sweep_path(fn), headers=HTML)
    if fn.method == "GET":
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    else:
        assert r.status_code == 401 and "로그인이 필요합니다" in r.text


# ── 실제 대상에 유효한 본문으로 — 403 이고 아무것도 바뀌지 않는다 ────────
def test_denied_writes_change_nothing(world):
    v = world.v
    today = world.today
    lot = client("현장").post("/mat/receipts", data={"item_code": v["raw_code"], "received_qty": "10"}).json()["lot_no"]
    work = client("현장").post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]
    ship = client("현장").post("/shp/shipments", data={"job_no": v["job_no"], "ship_date": today}).json()["shipment_no"]
    assert client("현장").post(f"/shp/shipments/{ship}/rolls", data={"roll_no": v["fn2"]}).status_code == 200

    def n(sql, params=()):
        return cs.db1(sql, params)["n"]

    cases = [
        ("품질", f"/job/orders/{v['job_no']}/cancel", {}, lambda: cs.db1("select status from job where job_no = %s", (v["job_no"],))["status"] == "등록"),
        ("현장", "/bas/items", {"item_code": f"{world.tag}-NO", "item_name": "x (예시)", "item_type": "제품"},
         lambda: n("select count(*) as n from item where item_code = %s", (f"{world.tag}-NO",)) == 0),
        ("관리자", "/mat/receipts", {"item_code": v["raw_code"], "received_qty": "7777"},
         lambda: n("select count(*) as n from material_lot where item_id = %s and received_qty = 7777", (v["raw"],)) == 0),
        ("생산", "/mat/inspections", {"lot_no": lot, "result": "합격"},      # D-14 — 생산·현장은 입고검사를 등록하지 못한다
         lambda: cs.db1("select insp_status from material_lot where lot_no = %s", (lot,))["insp_status"] == "대기"),
        ("현장", "/mat/inspections", {"lot_no": lot, "result": "불합격"},
         lambda: cs.db1("select insp_status from material_lot where lot_no = %s", (lot,))["insp_status"] == "대기"),
        ("관리자", "/mat/inputs", {"work_id": str(work), "lot_no": v["lot1"]},
         lambda: n("select count(*) as n from material_input where work_result_id = %s", (work,)) == 0),
        ("품질", "/pop/stops", {"work_id": str(work), "stop_reason": "x"},
         lambda: cs.db1("select status from work_result where work_result_id = %s", (work,))["status"] == "진행"),
        ("관리자", f"/pop/work/{work}/finish", {"output_qty": "1"},
         lambda: cs.db1("select status from work_result where work_result_id = %s", (work,))["status"] == "진행"),
        ("생산", "/clr/records", {"job_no": v["job_no"], "color_name": f"{world.tag} 금지"},
         lambda: n("select count(*) as n from color_record where color_name = %s", (f"{world.tag} 금지",)) == 0),
        ("품질", "/rll/slitting", {"roll_no": v["fn2"], "count": "2"},
         lambda: n("select count(*) as n from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id where r.roll_no = %s and g.relation = '슬리팅'", (v["fn2"],)) == 0),
        ("생산", "/qua/inspections", {"roll_no": v["fn2"], "result": "합격"},
         lambda: n("select count(*) as n from inspection n join roll r using (roll_id) where r.roll_no = %s", (v["fn2"],)) == 0),
        ("품질", f"/shp/shipments/{ship}/rolls", {"roll_no": v["s3"]},
         lambda: n("select count(*) as n from roll_genealogy g join shipment s on s.shipment_id = g.child_shipment_id where s.shipment_no = %s", (ship,)) == 1),
        ("관리자", "/shp/shipments", {"job_no": v["job_no"], "ship_date": "2099-01-01"},
         lambda: n("select count(*) as n from shipment s join job j using (job_id) where j.job_no = %s and s.ship_date = '2099-01-01'", (v["job_no"],)) == 0),
        ("관리자", f"/shp/shipments/{ship}/cancel", {},
         lambda: cs.db1("select status from shipment where shipment_no = %s", (ship,))["status"] == "등록"),
        ("생산", f"/shp/approvals/{ship}/approve", {},                       # D-14 — 승인은 관리자만
         lambda: cs.db1("select status from shipment where shipment_no = %s", (ship,))["status"] == "등록"),
        ("현장", f"/shp/approvals/{ship}/approve", {},
         lambda: cs.db1("select status from shipment where shipment_no = %s", (ship,))["status"] == "등록"),
        ("생산", "/sys/permissions", {"role_code": world.role_code, "menu_code": "BAS", "level": "입력"},
         lambda: n("select count(*) as n from sys_permission where role_code = %s and menu_code = 'BAS'", (world.role_code,)) == 0),
        ("품질", f"/sys/users/{v['user']}/delete", {},
         lambda: cs.db1("select status from sys_user where login_id = %s", (v["user"],))["status"] == "정상"),
    ]
    bad = []
    for role, path, data, unchanged in cases:
        r = client(role).post(path, data=data)
        if r.status_code != 403 or not unchanged():
            bad.append(f"{role} POST {path} → {r.status_code} · 그대로 {unchanged()}")
    assert bad == []
    # 같은 요청을 권한이 있는 역할이 하면 된다 — 403 이 본문 때문이 아니라 권한 때문이었다
    assert client("품질").post("/mat/inspections", data={"lot_no": lot, "result": "합격"}).status_code == 200
    assert client("관리자").post(f"/shp/approvals/{ship}/approve").status_code == 200


def test_forbidden_comes_before_validation():
    """권한이 없는 사람에게 입력값 오류를 먼저 알려 주지 않는다 (api-contract §4: 401 → 403 → 422).

    재검(웨이브 D 뒤) 정리: 품질 계정의 `POST /qua/inspections/abc/delete` 기대값을 422 → **404** 로 맞췄다. 같은 요청에
    `test_qa1_errors.py::test_404_non_numeric_path_key`(DEF-QA1-007 — QA1 이 낸 결함)는 404 를 기대해 두 테스트가 동시에 참일 수 없었다.
    이 테스트가 재는 것은 「순서」 다 — 권한이 있으면 권한 판정을 지나 **그 요청 자체의 오류**(숫자가 아닌 경로 키 = 404)를 받고,
    권한이 없으면 같은 요청에 403 을, 미로그인은 401 을 먼저 받는다. 「403 이 422 보다 먼저」 의 422 쪽은 같은 본문을
    권한 있는 역할이 보내는 줄(관리자 → 422)로 따로 남긴다."""
    err(client("현장").post("/bas/items", data={"item_code": ""}), 403, "forbidden")           # 권한 없음 → 본문 오류보다 403 이 먼저
    err(client("관리자").post("/bas/items", data={"item_code": ""}), 422, "validation_error")  # 같은 본문 · 권한 있음 → 입력값 오류
    err(client("품질").post("/qua/inspections/abc/delete"), 404, "not_found")                # 권한 있음 → 경로 키 오류 (DEF-QA1-007: 404)
    err(client("현장").post("/qua/inspections/abc/delete"), 403, "forbidden")               # 권한 없음 → 403 이 먼저
    err(anon().post("/qua/inspections/abc/delete"), 401, "unauthorized")


# ── 권한 표는 데이터다 ──────────────────────────────────────────────────
def test_permission_table_is_data(world):
    """검사 전용 역할(`sys_role` 한 행 — 코드에 없는 역할)에 칸을 주고 빼면 코드 수정 없이 그대로 반영된다.
    화면 기능(F-SYS-06)으로 바꾼 것은 다음 요청부터, SQL 로 직접 바꾼 것은 캐시(5초) 안에."""
    ok, detail = cs.role_as_data(http(), world)
    assert ok, detail


def test_new_role_is_not_in_code(world):
    """그 역할 코드는 `src/` 어디에도 없다 — 역할을 늘려도 코드를 고치지 않았다는 뜻이다."""
    hits = [p for p in (cs.SRC / "lcomfine").rglob("*.py") if world.role_code in p.read_text(encoding="utf-8")]
    assert hits == []


def test_seed_permission_table_untouched_at_end():
    """이 모듈이 끝날 때 시드 역할의 48칸이 그대로다 (검사 전용 역할의 칸은 모듈 뒷정리가 지운다)."""
    seed = cs.db("""select p.level, count(*) as n from sys_permission p join sys_role r using (role_code)
                     where r.use_yn = 'Y' group by p.level""")
    assert {x["level"]: x["n"] for x in seed} == {"입력": 19, "조회": 24, "없음": 5}


# ── 검사기 자신 — 권한 판정이 뚫리면 전수 검사가 그것을 잡는가 ───────────
def test_sweep_detects_a_broken_permission_check(monkeypatch):
    """`rbac.can_do` 가 무엇이든 허용하게 바꾸면(이 프로세스 안에서만 — DB 는 그대로) 전수 검사가 위반을 낸다.
    쓰기 403 이어야 할 128 + D-14 4 쌍과 읽기 403 이어야 할 쌍이 전부 드러나야 한다 — 검사가 헐겁지 않다는 확인이다."""
    from lcomfine.app import rbac

    monkeypatch.setattr(rbac, "can_do", lambda role_code, function_id: True)
    sweep = cs.Rbac(http(), ACCESS, SCREEN_FNS)
    sweep.functions(write=True)
    sweep.functions(write=False)
    denied_reads = sum(1 for role in ROLES for f in READ_FNS if cs.expected(ACCESS, role, f) == "deny")
    assert sweep.detail["쓰기"] == (216, 132)
    assert sweep.detail["읽기"] == (160, denied_reads) and denied_reads > 0
