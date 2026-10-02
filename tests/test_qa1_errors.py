"""QA1 — 오류 계약 (goal.md §2.5) 전 행.  개발의 테스트가 아니라 goal.md 의 표에서 기대값을 끌어온다.

| 상황 | HTTP |
|---|---|
| 필수값 누락 · 코드 중복 · 없는 LOT/롤 스캔 · 이미 출하된 롤 재출하 · 자기 자신을 부모로 하는 계보 | 422 (POP 은 다음 스캔을 막지 않는다) |
| 인증 실패 | 401 (브라우저 GET 은 /login 303) |
| 권한 없음 | 403 `접근 권한이 없습니다` |
| DB 연결 실패 | 503 `서비스 일시 중단` |
| ERP 연계 · 미확정 연계 | 501 `미확정 (D-nn)` |
| 처리되지 않은 예외 | 500 `예상하지 못한 오류` + 로그 |

결함을 드러내는 테스트는 실패하는 채로 둔다(`skip`·`xfail` 을 쓰지 않는다). 어느 테스트가 어느 결함인지는 `outputs/qa1-기능계약.md` §3.
DB 연결 실패는 PostgreSQL 을 멈추지 않고 **이 프로세스의 접속 문자열만** 없는 소켓으로 바꿔서 만든다.
"""
import json
import re
import secrets

import pytest

from test_qa1_support import (ACCESS, HTML, ROLES, SCREEN_FNS, SCREEN_PATHS, WRITE_FNS, anon, build_world, client, cs, drop_world,
                              err, http, invalid)

NONE = "Q1-NONE"


def allowed_role(fn) -> str:
    return next(r for r in ROLES if cs.expected(ACCESS, r, fn) == "allow")


@pytest.fixture(scope="module")
def world():
    flow = build_world()
    try:
        v, F, P, Q = flow.v, client("현장"), client("생산"), client("품질")
        v["lot_wait"] = F.post("/mat/receipts", data={"item_code": v["raw_code"], "received_qty": "10"}).json()["lot_no"]
        v["lot_fail"] = F.post("/mat/receipts", data={"item_code": v["raw_code"], "received_qty": "10"}).json()["lot_no"]
        assert Q.post("/mat/inspections", data={"lot_no": v["lot_fail"], "result": "불합격"}).status_code == 200
        v["work_open"] = F.post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]
        v["ship_open"] = F.post("/shp/shipments", data={"job_no": v["job_no"], "ship_date": flow.today}).json()["shipment_no"]
        # 다른 Job 의 롤 (D-16) — Job B 를 화면 API 로 만들고 인쇄 롤 하나를 낸다
        v["job_b"] = P.post("/job/orders", data={"item_id": str(v["item"]), "customer_id": str(v["customer"]), "order_qty": "10",
                                                 "due_date": flow.today}).json()["job_no"]
        wb = F.post("/pop/work/start", data={"job_no": v["job_b"]}).json()["work_id"]
        assert F.post("/mat/inputs", data={"work_id": str(wb), "lot_no": v["lot2"]}).status_code == 200
        v["roll_b"] = F.post(f"/pop/work/{wb}/finish", data={"output_qty": "1"}).json()["roll_no"]
        # 로그인 실패를 재는 계정 — 시드 계정의 실패 횟수를 건드리지 않는다. 역할은 검사 전용 역할(실적 현황 조회 칸 하나)
        v["login_user"], v["login_pw"] = f"{flow.tag.lower()}-u5", secrets.token_urlsafe(12)
        assert client("관리자").post("/sys/users", data={"login_id": v["login_user"], "user_name": f"{flow.tag} 로그인 (예시)",
                                                       "role_code": flow.role_code, "password": v["login_pw"]}).status_code == 200
        yield flow
    finally:
        drop_world(flow)


def roll_id(roll_no: str) -> int:
    return cs.db1("select roll_id from roll where roll_no = %s", (roll_no,))["roll_id"]


# ════════════════════════════════════════════════════════════════════════
# 422 — 필수값 누락
# ════════════════════════════════════════════════════════════════════════
NO_KEY_WRITES = [f for f in WRITE_FNS if "{" not in f.path]


def test_no_key_write_functions_are_24():
    assert len(NO_KEY_WRITES) == 24


@pytest.mark.parametrize("fn", NO_KEY_WRITES, ids=lambda f: f.id)
def test_422_missing_required(fn):
    """경로에 키가 없는 쓰기 기능 24개 — 빈 본문은 422 이고 어느 항목이 빠졌는지 알려 준다."""
    body = invalid(client(allowed_role(fn)).post(fn.path))
    assert body["fields"], body


KEYED = [f for f in SCREEN_FNS if "{" in f.path]


@pytest.mark.parametrize("fn", KEYED, ids=lambda f: f.id)
def test_404_missing_path_key(fn):
    """경로에 박힌 키가 없으면 404 `대상을 찾을 수 없습니다` (api-contract §1 — 422 와의 경계)."""
    data = {"F-POP-02": {"output_qty": "1"}}.get(fn.id)      # 작업 종료는 본문(실적 수량)을 먼저 본다 — 유효한 본문으로 잰다
    body = err(client(allowed_role(fn)).request(fn.method, cs.sweep_path(fn), data=data), 404, "not_found")
    assert body["message"] == "대상을 찾을 수 없습니다"


NON_NUMERIC_KEYS = [   # (역할, 경로, 본문) — 숫자 키 자리에 글자
    ("관리자", "/bas/items/abc", {"item_name": "x"}), ("관리자", "/bas/items/abc/delete", None),
    ("생산", "/prt/inks/abc/delete", None), ("현장", "/pop/work/abc/finish", {"output_qty": "1"}),
    ("현장", "/pop/stops/abc/resume", None), ("품질", "/clr/records/abc/delete", None), ("품질", "/clr/records/abc/mix", None),
    ("품질", "/qua/inspections/abc", {"result": "합격"}), ("품질", "/qua/inspections/abc/delete", None),
]


@pytest.mark.parametrize("role,path,data", NON_NUMERIC_KEYS, ids=[p for _, p, _ in NON_NUMERIC_KEYS])
def test_404_non_numeric_path_key(role, path, data):
    """경로의 키 자리에 숫자가 아닌 글자 — 그런 대상은 없다(404). 화면마다 같아야 한다.  → DEF-QA1-007 (검사 결과만 422 + 영문 문구)"""
    err(client(role).post(path, data=data), 404, "not_found")


# ════════════════════════════════════════════════════════════════════════
# 422 — 코드 중복
# ════════════════════════════════════════════════════════════════════════
MASTERS = [  # (기능, 경로, 코드 칸, 이름 칸, world 키, 그 밖의 필수값)
    ("F-BAS-01", "/bas/items", "item_code", "item_name", "item_code", {"item_type": "제품"}),
    ("F-BAS-05", "/bas/customers", "customer_code", "customer_name", "customer_code", {}),
    ("F-BAS-09", "/bas/processes", "process_code", "process_name", "process_code", {"process_type": "인쇄"}),
    ("F-BAS-13", "/bas/equipment", "equipment_code", "equipment_name", "equipment_code", {}),
    ("F-BAS-17", "/bas/defect-codes", "defect_code", "defect_name", "defect_code", {}),
    ("F-PRT-01", "/prt/plates", "plate_code", "plate_name", "plate_code", {}),
    ("F-PRT-05", "/prt/anilox", "anilox_code", "anilox_name", "anilox_code", {}),
    ("F-PRT-09", "/prt/inks", "ink_code", "ink_name", "ink_code", {}),
]


@pytest.mark.parametrize("fid,path,code_col,name_col,key,extra", MASTERS, ids=[m[0] for m in MASTERS])
def test_422_duplicate_code(world, fid, path, code_col, name_col, key, extra):
    code = world.v[key]
    table = next(f for f in WRITE_FNS if f.id == fid).tables[0]
    body = invalid(client("관리자").post(path, data={code_col: code, name_col: "중복 (예시)", **extra}))
    assert code in json.dumps(body, ensure_ascii=False)
    assert cs.db1(f"select count(*) as n from {table} where {code_col} = %s", (code,))["n"] == 1


def test_422_duplicate_login_id(world):
    r = client("관리자").post("/sys/users", data={"login_id": world.v["login_user"], "user_name": "중복 (예시)",
                                                "role_code": world.role_code, "password": secrets.token_urlsafe(8)})
    invalid(r)
    assert cs.db1("select count(*) as n from sys_user where login_id = %s", (world.v["login_user"],))["n"] == 1


# ════════════════════════════════════════════════════════════════════════
# 422 — 없는 LOT/롤 스캔
# ════════════════════════════════════════════════════════════════════════
def scan_posts(v) -> list[tuple[str, str, dict]]:
    return [
        ("현장", "/mat/inputs", {"work_id": str(v["work_open"]), "lot_no": NONE}),
        ("품질", "/mat/inspections", {"lot_no": NONE, "result": "합격"}),
        ("현장", "/pop/work/start", {"job_no": NONE}),
        ("현장", "/rll/finishing", {"roll_no": NONE}),
        ("현장", "/rll/finishing/splice", {"roll_no": [NONE, v["fn2"]]}),
        ("현장", "/rll/slitting", {"roll_no": NONE, "count": "2"}),
        ("품질", "/qua/inspections", {"roll_no": NONE, "result": "합격"}),
        ("현장", f"/shp/shipments/{v['ship_open']}/rolls", {"roll_no": NONE}),
        ("현장", "/shp/shipments", {"job_no": NONE, "ship_date": "2026-10-03"}),
        ("품질", "/clr/records", {"job_no": NONE, "color_name": "x"}),
        ("생산", "/job/mapping", {"job_no": NONE}),
    ]


def test_422_scan_of_unknown_number_post(world):
    bad = []
    for role, path, data in scan_posts(world.v):
        r = client(role).post(path, data=data)
        if r.status_code != 422 or r.json().get("code") != "validation_error" or NONE not in r.text:
            bad.append(f"{role} POST {path} → {r.status_code} {r.text[:120]}")
    assert bad == []


SCAN_GETS = [  # (역할, 경로, 스캔값이 들어가는 인자)
    ("현장", "/pop/work", "no"), ("현장", "/pop/roll-labels", "no"), ("현장", "/mat/inspections", "no"), ("현장", "/mat/lots", "no"),
    ("현장", "/rll/finishing", "add"), ("현장", "/rll/slitting", "no"), ("현장", "/rll/history", "no"),
    ("품질", "/qua/inspections", "no"), ("현장", "/shp/shipments", "no"),
    ("관리자", "/trc/trace/forward", "no"), ("관리자", "/trc/trace/backward", "no"), ("관리자", "/job/orders", "no"),
    ("관리자", "/job/mapping", "no"),
]


@pytest.mark.parametrize("role,path,arg", SCAN_GETS, ids=[f"{p}?{a}" for _, p, a in SCAN_GETS])
def test_422_scan_of_unknown_number_get(role, path, arg):
    """스캔으로 여는 화면(`?no=`)에 없는 번호 — JSON 은 422 `validation_error`."""
    body = invalid(client(role).get(path, params={arg: NONE}))
    assert NONE in json.dumps(body, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════════
# 422 — 이미 출하된 롤 재출하 · 소진된 롤 재사용
# ════════════════════════════════════════════════════════════════════════
def test_422_reship_of_shipped_roll(world):
    v, F = world.v, client("현장")
    invalid(F.post(f"/shp/shipments/{v['ship_open']}/rolls", data={"roll_no": v["s1"]}))        # 다른 출하에 다시
    invalid(F.post(f"/shp/shipments/{v['ship1']}/rolls", data={"roll_no": v["s1"]}))            # 같은(승인된) 출하에 다시
    n = cs.db1("""select count(*) as n from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id
                   where r.roll_no = %s and g.relation = '출하'""", (v["s1"],))["n"]
    assert n == 1, "출하된 롤의 출하 화살표는 하나뿐이어야 한다"


def test_422_shipped_or_consumed_roll_cannot_be_reused(world):
    v, F = world.v, client("현장")
    invalid(F.post("/rll/finishing", data={"roll_no": v["s1"]}))                                 # 출하된 롤을 후가공에
    invalid(F.post("/rll/slitting", data={"roll_no": v["s1"], "count": "2"}))                    # 출하된 롤을 슬리팅에
    invalid(F.post("/rll/finishing", data={"roll_no": v["p1"]}))                                 # 소진된 롤을 후가공에
    invalid(F.post("/rll/slitting", data={"roll_no": v["fn1"], "count": "2"}))                   # 소진된 롤을 슬리팅에
    invalid(F.post("/rll/finishing/splice", data={"roll_no": [v["p1"], v["fn2"]]}))              # 소진된 롤을 splice 에
    invalid(F.post(f"/shp/shipments/{v['ship_open']}/rolls", data={"roll_no": v["fn1"]}))        # 소진된 롤을 출하에
    assert cs.db1("select count(*) as n from roll_genealogy g join roll r on r.roll_id = g.parent_roll_id where r.roll_no = %s",
                  (v["s1"],))["n"] == 1


def test_422_shipment_rules(world):
    """출하 스캔·승인·취소·COA 의 계약 문장 (F-SHP-02·03·05·07 · D-16 · D-17)."""
    v, F, A = world.v, client("현장"), client("관리자")
    invalid(F.post(f"/shp/shipments/{v['ship_open']}/rolls", data={"roll_no": v["roll_b"]}))     # 다른 Job 의 롤
    invalid(F.post(f"/shp/shipments/{v['ship_open']}/rolls", data={"roll_no": v["s3"]}))         # 최신 검사 불합격
    invalid(F.post(f"/shp/shipments/{v['ship_open']}/rolls", data={"roll_no": v["lot1"]}))       # 롤이 아닌 번호
    invalid(F.post(f"/shp/shipments/{v['ship1']}/rolls", data={"roll_no": v["fn2"]}))            # 승인된 출하에 담기
    invalid(A.post(f"/shp/approvals/{v['ship_open']}/approve"))                                  # 롤 0개 승인
    invalid(A.post(f"/shp/approvals/{v['ship1']}/approve"))                                      # 이미 승인
    invalid(F.post(f"/shp/shipments/{v['ship1']}/cancel"))                                       # 승인된 출하 취소
    invalid(F.post(f"/shp/shipments/{v['ship2']}/cancel"))                                       # 이미 취소
    invalid(A.get(f"/shp/coa/{v['ship_open']}/print"))                                           # 미승인 COA
    invalid(F.post("/shp/shipments", data={"job_no": v["job_cancel"], "ship_date": world.today}))  # 취소된 Job
    assert cs.db1("select status, coa_no from shipment where shipment_no = %s", (v["ship_open"],)) == {"status": "등록", "coa_no": None}


# ════════════════════════════════════════════════════════════════════════
# 422 — 자기 자신을 부모로 하는 계보 · 순환
# ════════════════════════════════════════════════════════════════════════
def test_422_self_parent_via_screen_api(world):
    """화면으로 낼 수 있는 가장 가까운 경우 — 같은 롤을 두 번 넣은 splice."""
    v = world.v
    invalid(client("현장").post("/rll/finishing/splice", data={"roll_no": [v["fn2"], v["fn2"]]}))
    assert cs.db1("select state from v_roll_state where roll_no = %s", (v["fn2"],))["state"] == "재고"


def test_422_self_parent_and_cycle_via_lineage(world):
    """`lineage.link` — 자기 자신을 부모로 · 자손을 부모로(순환)는 422 이고 행이 생기지 않는다."""
    from fastapi import HTTPException

    from lcomfine.app import lineage
    from lcomfine.db import conn

    v = world.v
    fn1, s3 = roll_id(v["fn1"]), roll_id(v["s3"])
    before = cs.db1("select count(*) as n from roll_genealogy where child_roll_id = %s", (fn1,))["n"]
    for parent, child in ((fn1, fn1), (s3, fn1)):
        with pytest.raises(HTTPException) as e:
            with conn.tx() as cur:
                lineage.link(cur, (lineage.ROLL, parent), (lineage.ROLL, child), lineage.SPLICE, by="q1-test")
        assert e.value.status_code == 422, e.value.detail
    assert cs.db1("select count(*) as n from roll_genealogy where child_roll_id = %s", (fn1,))["n"] == before


def private_app():
    """오류 핸들러만 따로 재는 앱 — `create_app()` 으로 **새 인스턴스**를 만들어 시험용 경로를 붙인다(공용 `app` 은 건드리지 않는다)."""
    from fastapi.testclient import TestClient

    from lcomfine.app.main import create_app
    from lcomfine.db import conn

    app = create_app()

    @app.post("/q1-self-parent/{rid}")
    def self_parent(rid: int):
        conn.x("""insert into roll_genealogy (parent_roll_id, child_roll_id, relation, created_by)
                  values (%s, %s, 'splice', 'q1-test')""", (rid, rid))
        return {"ok": True}

    @app.get("/q1-boom")
    def boom():
        raise RuntimeError("Q1 의도한 예외")

    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def test_422_self_parent_blocked_by_db_and_mapped_to_422(world):
    """`lineage` 를 거치지 않은 쓰기도 DB 제약이 막고(마지막 방어선), 그 위반은 500 이 아니라 422 로 나온다 (api-contract §3)."""
    rid = roll_id(world.v["fn1"])
    body = invalid(private_app().post(f"/q1-self-parent/{rid}"))
    assert body["fields"], body
    assert cs.db1("select count(*) as n from roll_genealogy where parent_roll_id = %s and child_roll_id = %s", (rid, rid))["n"] == 0


# ════════════════════════════════════════════════════════════════════════
# 422 — 기능별 계약 문장 (function-list.md 의 「계약」 열)
# ════════════════════════════════════════════════════════════════════════
def test_422_master_delete_in_use(world):
    v, A = world.v, client("관리자")
    for path, key in (("/bas/items", "item"), ("/bas/customers", "customer"), ("/bas/processes", "process"),
                      ("/bas/equipment", "equipment"), ("/bas/defect-codes", "defect"), ("/prt/plates", "plate"),
                      ("/prt/anilox", "anilox"), ("/prt/inks", "ink")):
        body = invalid(A.post(f"{path}/{v[key]}/delete"))
        assert body["message"] == "사용 중이라 삭제할 수 없습니다", (path, body)
    assert cs.db1("select count(*) as n from item where item_id = %s", (v["item"],))["n"] == 1


def test_422_master_code_cannot_change(world):
    v = world.v
    invalid(client("관리자").post(f"/bas/items/{v['item']}", data={"item_code": v["item_code"] + "Z", "item_name": "x"}))
    assert cs.db1("select item_code from item where item_id = %s", (v["item"],))["item_code"] == v["item_code"]


def test_422_job_rules(world):
    v, P = world.v, client("생산")
    invalid(P.post(f"/job/orders/{v['job_no']}/cancel"))                                         # 실적·롤이 있는 Job 취소
    invalid(P.post(f"/job/orders/{v['job_no']}", data={"order_qty": "5"}))                       # 실적이 생긴 뒤 수량 변경
    invalid(P.post(f"/job/orders/{v['job_cancel']}", data={"note": "x"}))                        # 취소된 Job 수정
    invalid(P.post("/job/orders", data={"item_id": str(v["raw"]), "customer_id": str(v["customer"]), "order_qty": "1",
                                        "due_date": world.today}))                               # 원재료 품목으로 지시
    invalid(P.post("/job/orders", data={"item_id": str(v["item"]), "customer_id": str(v["customer"]), "order_qty": "0",
                                        "due_date": world.today}))                               # 수량 0
    invalid(P.post("/job/mapping", data={"job_no": v["job_cancel"]}))                            # 취소된 Job 에 생산 LOT
    assert cs.db1("select status, order_qty from job where job_no = %s", (v["job_no"],))["status"] == "등록"


def test_422_pop_rules(world):
    v, F = world.v, client("현장")
    invalid(F.post("/pop/work/start", data={"job_no": v["job_cancel"]}))                         # 취소된 Job 에서 작업 시작
    invalid(F.post(f"/pop/work/{v['work_open']}/finish", data={"output_qty": "1"}))              # 투입 0건으로 종료
    invalid(F.post(f"/pop/work/{v['p1_work']}/finish", data={"output_qty": "1"}))                # 이미 종료한 실적
    invalid(F.post("/pop/stops", data={"work_id": str(v["p1_work"]), "stop_reason": "x"}))       # 진행 중이 아닌 실적 정지
    invalid(F.post("/pop/stops/scrap", data={"work_id": str(v["work_open"]), "scrap_qty": "0"}))  # 폐기 수량 0
    invalid(F.post("/pop/stops/scrap", data={"work_id": str(v["work_open"]), "scrap_qty": "-1"}))
    stop = cs.db1("select work_stop_id from work_stop where work_result_id = %s", (v["p1_work"],))["work_stop_id"]
    invalid(F.post(f"/pop/stops/{stop}/resume"))                                                 # 이미 재개한 정지
    assert cs.db1("select count(*) as n from roll where work_result_id = %s", (v["work_open"],))["n"] == 0


def test_422_material_rules(world):
    v, F, Q = world.v, client("현장"), client("품질")
    w = str(v["work_open"])
    invalid(F.post("/mat/inputs", data={"work_id": w, "lot_no": v["lot_wait"]}))                 # 검사 대기 LOT 투입
    invalid(F.post("/mat/inputs", data={"work_id": w, "lot_no": v["lot_fail"]}))                 # 불합격 LOT 투입
    invalid(F.post("/mat/inputs", data={"work_id": str(v["p1_work"]), "lot_no": v["lot2"]}))     # 끝난 실적에 투입
    invalid(Q.post("/mat/inspections", data={"lot_no": v["lot1"], "result": "불합격"}))           # 투입된 LOT 의 판정 변경
    invalid(Q.post("/mat/inspections", data={"lot_no": v["lot_wait"], "result": "보류"}))         # 없는 판정
    invalid(F.post("/mat/receipts", data={"item_code": v["item_code"], "received_qty": "1"}))    # 제품 품목 입고
    invalid(F.post("/mat/receipts", data={"item_code": v["raw_code"], "received_qty": "0"}))     # 입고 수량 0
    assert cs.db1("select count(*) as n from material_input where work_result_id = %s", (v["work_open"],))["n"] == 0


def test_422_duplicate_scan_then_next_scan_works(world):
    """같은 실적에 같은 LOT 을 두 번 스캔하면 422 이고, **그 다음 스캔은 그대로 된다**(POP 은 다음 스캔을 막지 않는다)."""
    v, F = world.v, client("현장")
    w = F.post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]
    assert F.post("/mat/inputs", data={"work_id": str(w), "lot_no": v["lot1"]}).status_code == 200
    invalid(F.post("/mat/inputs", data={"work_id": str(w), "lot_no": v["lot1"]}))                # 중복 스캔
    invalid(F.post("/mat/inputs", data={"work_id": str(w), "lot_no": NONE}))                     # 없는 LOT
    assert F.post("/mat/inputs", data={"work_id": str(w), "lot_no": v["lot2"]}).status_code == 200   # 다음 스캔
    assert cs.db1("select count(*) as n from material_input where work_result_id = %s", (w,))["n"] == 2


def test_422_color_rules(world):
    v, Q = world.v, client("품질")
    invalid(Q.post(f"/clr/records/{v['color']}/mix", data={"component_name": ["가", "나"], "ratio_pct": ["60", "30"]}))   # 합 90
    invalid(Q.post(f"/clr/records/{v['color']}/mix", data={"component_name": ["가"], "ratio_pct": ["60", "40"]}))         # 개수 다름
    invalid(Q.post("/clr/records", data={"job_no": v["job_no"], "color_name": v["color_name"], "seq_no": "1"}))           # 같은 차수
    assert cs.db1("select sum(ratio_pct) as t from color_record_mix where color_record_id = %s", (v["color"],))["t"] == 100


def test_422_quality_rules(world):
    v, Q = world.v, client("품질")
    invalid(Q.post("/qua/inspections", data={"roll_no": v["fn2"], "result": "보류"}))             # 없는 판정
    invalid(Q.post("/qua/inspections", data={"roll_no": v["fn2"], "result": "합격", "delta_e": "-1"}))
    invalid(Q.post("/qua/inspections", data={"roll_no": v["fn2"], "result": "불합격", "defect_code": [NONE], "position": ["x"]}))
    done = cs.db1("select n.inspection_id from inspection n join roll r using (roll_id) where r.roll_no = %s", (v["s1"],))["inspection_id"]
    invalid(Q.post(f"/qua/inspections/{done}", data={"result": "불합격"}))                        # 출하 승인된 롤의 검사 수정
    invalid(Q.post(f"/qua/inspections/{done}/delete"))                                           # … 삭제
    assert cs.db1("select result from inspection where inspection_id = %s", (done,))["result"] == "합격"


def test_422_system_rules(world):
    v, A = world.v, client("관리자")
    me = cs.role_logins()["관리자"]
    invalid(A.post(f"/sys/users/{me['login_id']}/delete"))                                       # 자기 자신 삭제
    invalid(A.post("/sys/permissions", data={"role_code": me["code"], "menu_code": "SYS", "level": "조회"}))   # 잠김 방지
    invalid(A.post("/sys/permissions", data={"role_code": world.role_code, "menu_code": "XXX", "level": "조회"}))
    invalid(A.post("/sys/permissions", data={"role_code": world.role_code, "menu_code": "BAS", "level": "관리"}))
    invalid(A.post("/sys/users", data={"login_id": "한글", "user_name": "x", "role_code": world.role_code, "password": "x"}))
    assert cs.db1("select level, write_scope from sys_permission where role_code = %s and menu_code = 'SYS'",
                  (me["code"],)) == {"level": "입력", "write_scope": "일반"}
    assert v["user"]


# ════════════════════════════════════════════════════════════════════════
# 422 — 형식이 틀린 입력은 500 이 아니다 (필수값 누락과 같은 줄 — 입력값 오류)
# ════════════════════════════════════════════════════════════════════════
NUL = "a\x00b"
NUL_REQUESTS = {   # 모듈 → [(역할, 메서드, 경로, 본문/인자)]
    "login": [(None, "POST", "/login", {"login_id": NUL, "password": "x"})],
    "bas": [("관리자", "GET", "/bas/items", {"code": NUL}), ("관리자", "GET", "/bas/customers", {"name": NUL}),
            ("관리자", "POST", "/bas/items", {"item_code": NUL, "item_name": "x", "item_type": "제품"})],
    "prt": [("관리자", "GET", "/prt/plates", {"code": NUL}), ("관리자", "GET", "/prt/inks", {"name": NUL})],
    "job": [("관리자", "GET", "/job/orders", {"no": NUL}), ("관리자", "GET", "/job/orders", {"q": NUL}),
            ("관리자", "GET", "/job/mapping", {"no": NUL}), ("관리자", "GET", "/job/orders/a%00b/print", None),
            ("관리자", "POST", "/job/mapping", {"job_no": NUL})],
    "sys": [("관리자", "GET", "/sys/users", {"login_id": NUL}), ("관리자", "GET", "/sys/users", {"edit": NUL}),
            ("관리자", "GET", "/sys/logs", {"login_id": NUL})],
    "pop": [("현장", "GET", "/pop/work", {"no": NUL}), ("현장", "GET", "/pop/work", {"roll": NUL}),
            ("현장", "GET", "/pop/roll-labels", {"no": NUL}), ("현장", "POST", "/pop/work/start", {"job_no": NUL})],
    "mat": [("현장", "GET", "/mat/lots", {"no": NUL}), ("현장", "GET", "/mat/receipts", {"supplier": NUL}),
            ("현장", "GET", "/mat/inspections", {"insp_status": NUL}), ("현장", "GET", "/mat/lots/a%00b/label", None),
            ("현장", "POST", "/mat/receipts", {"item_code": NUL, "received_qty": "1"}),
            ("품질", "POST", "/mat/inspections", {"lot_no": NUL, "result": "합격"})],
    "clr": [("품질", "GET", "/clr/records", {"job_no": NUL}), ("품질", "POST", "/clr/records", {"job_no": NUL, "color_name": "x"})],
    "rll": [("현장", "GET", "/rll/history", {"no": NUL}), ("현장", "GET", "/rll/finishing", {"rolls": NUL}),
            ("현장", "GET", "/rll/slitting", {"parent": NUL}), ("현장", "POST", "/rll/finishing", {"roll_no": NUL})],
    "qua": [("품질", "GET", "/qua/inspections", {"no": NUL}), ("품질", "GET", "/qua/defect-stats/rolls", {"defect_code": NUL}),
            ("품질", "POST", "/qua/inspections", {"roll_no": NUL, "result": "합격"})],
    "shp": [("현장", "GET", "/shp/shipments", {"no": NUL}), ("관리자", "GET", "/shp/coa", {"customer": NUL}),
            ("관리자", "GET", "/shp/coa/a%00b/print", None),
            ("현장", "POST", "/shp/shipments", {"job_no": NUL, "ship_date": "2026-10-03"})],
    "trc": [("관리자", "GET", "/trc/trace", {"q": NUL}), ("관리자", "GET", "/trc/trace/forward", {"no": NUL}),
            ("관리자", "GET", "/trc/trace/backward", {"no": NUL})],
}


@pytest.mark.parametrize("module", list(NUL_REQUESTS))
def test_nul_byte_input_is_not_500(module):
    """글자 입력에 NUL(0x00)이 섞여 들어오면 입력값 오류(422)나 없음(404)이지 500 이 아니다.  → DEF-QA1-001"""
    bad = []
    for role, method, path, payload in NUL_REQUESTS[module]:
        c = client(role) if role else anon()
        r = c.request(method, path, **({"params": payload} if method == "GET" else {"data": payload}))
        if r.status_code >= 500:
            bad.append(f"{method} {path} {payload and list(payload)} → {r.status_code} {r.json().get('reason', '')[:60]}")
    assert bad == [], f"{len(bad)}/{len(NUL_REQUESTS[module])} 건이 500"


def overflow_requests(v) -> dict[str, list[tuple[str, str, dict]]]:
    w = str(v["work_open"])
    return {
        "mat": [("현장", "/mat/receipts", {"item_code": v["raw_code"], "received_qty": "1e15"}),
                ("현장", "/mat/inputs", {"work_id": w, "lot_no": v["lot1"], "input_qty": "1e15"})],
        "pop": [("현장", "/pop/stops/scrap", {"work_id": w, "scrap_qty": "1e15"}),
                ("현장", f"/pop/work/{v['work_ovf']}/finish", {"output_qty": "1e15"}),
                ("현장", f"/pop/work/{v['work_ovf']}/finish", {"output_qty": "1", "width_mm": "1e9"}),
                ("현장", f"/pop/work/{v['work_ovf']}/finish", {"output_qty": "1", "length_m": "1e15"})],
        "clr": [("품질", "/clr/records", {"job_no": v["job_no"], "color_name": "넘침", "color_l": "1000000"}),
                ("품질", "/clr/records", {"job_no": v["job_no"], "color_name": "넘침", "seq_no": "99999999999"}),
                ("품질", f"/clr/records/{v['color']}", {"color_name": v["color_name"], "color_l": "1000000"})],
        "rll": [("현장", "/rll/finishing", {"roll_no": v["fn2"], "length_m": "1e15"}),
                ("현장", "/rll/finishing", {"roll_no": v["fn2"], "width_mm": "1e9"}),
                ("현장", "/rll/slitting", {"roll_no": v["fn2"], "count": "1", "widths_mm": "1e9"})],
        "qua": [("품질", "/qua/inspections", {"roll_no": v["fn2"], "result": "합격", "delta_e": "99999.999"})],
        "job": [("생산", "/job/orders", {"item_id": str(v["item"]), "customer_id": str(v["customer"]), "order_qty": "1e15",
                                        "due_date": "2026-10-10"}),
                ("생산", "/job/mapping", {"job_no": v["job_no"], "planned_roll_count": "99999999999"})],
        "prt": [("관리자", "/prt/anilox", {"anilox_code": f"{v['item_code']}-OVF", "anilox_name": "x", "line_count": "1e12"})],
    }


@pytest.mark.parametrize("module", ["mat", "pop", "clr", "rll", "qua", "job", "prt"])
def test_out_of_range_number_is_422_not_500(world, module):
    """컬럼이 담을 수 없는 큰 수 — 입력값 오류(422)여야 하고 500 이 아니다. 아무것도 쓰이지 않는다.  → DEF-QA1-002"""
    v = world.v
    if "work_ovf" not in v:      # 투입이 있는(종료할 수 있는) 진행 중 실적
        v["work_ovf"] = client("현장").post("/pop/work/start", data={"job_no": v["job_no"]}).json()["work_id"]
        assert client("현장").post("/mat/inputs", data={"work_id": str(v["work_ovf"]), "lot_no": v["lot2"]}).status_code == 200
    bad = []
    for role, path, data in overflow_requests(v)[module]:
        r = client(role).post(path, data=data)
        if r.status_code != 422:
            bad.append(f"POST {path} {data} → {r.status_code} {r.text[:90]}")
    assert bad == [], f"{len(bad)} 건이 422 가 아니다"


# ════════════════════════════════════════════════════════════════════════
# POP — 422 가 나도 다음 스캔을 막지 않는다 (서버 응답으로 볼 수 있는 데까지)
# ════════════════════════════════════════════════════════════════════════
POP_MENUS = [m for m, ch in ACCESS["channels"].items() if "현장 POP" in ch]           # 설계도 §6 「주로 쓰는 채널」
POP_SCAN_GETS = [(r, p, a) for r, p, a in SCAN_GETS if SCREEN_PATHS.get(p) in POP_MENUS]


def test_pop_scan_screens_come_from_design_doc():
    assert POP_MENUS == ["생산 실적 (POP)", "자재 · 입고", "조색 기록", "후가공 · 슬리팅 롤 이력", "품질 검사 기록", "출하"]
    assert len(POP_SCAN_GETS) == 9


@pytest.mark.parametrize("role,path,arg", POP_SCAN_GETS, ids=[f"{p}?{a}" for _, p, a in POP_SCAN_GETS])
def test_pop_scan_get_422_keeps_the_scan_box(role, path, arg):
    """현장 POP 화면에서 없는 번호를 스캔(브라우저 GET)하면 422 이되, **그 화면에 스캔칸이 그대로 있어야** 다음 스캔을 할 수 있다.
    오류 화면(`_error.html` — 「메인으로」 「로그인」 버튼뿐)으로 가면 스캔이 막힌다.  → DEF-QA1-004"""
    r = client(role).get(path, params={arg: NONE, "device": "pop"}, headers=HTML)
    assert r.status_code == 422
    assert "data-scan" in r.text, "422 응답에 스캔칸이 없다 — 오류 화면으로 빠졌다"
    assert NONE in r.text and "ch-pop" in r.text


def flash_of(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="flash-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else {}


def pop_scan_posts(v) -> list[tuple[str, str, dict, str]]:   # (역할, 경로, 틀린 스캔, 스캔하던 화면)
    return [
        ("현장", "/mat/inputs", {"work_id": str(v["work_open"]), "lot_no": NONE}, f"/mat/inputs?work_id={v['work_open']}&device=pop"),
        ("현장", "/pop/work/start", {"job_no": NONE}, "/pop/work?device=pop"),
        ("현장", "/rll/slitting", {"roll_no": NONE, "count": "2"}, "/rll/slitting?device=pop"),
        ("품질", "/qua/inspections", {"roll_no": NONE, "result": "합격"}, "/qua/inspections?device=pop"),
        ("현장", f"/shp/shipments/{v['ship_open']}/rolls", {"roll_no": NONE}, f"/shp/shipments?no={v['ship_open']}&device=pop"),
    ]


def test_pop_scan_post_422_returns_to_the_scan_screen(world):
    """브라우저 폼 POST 의 422 — 스캔하던 화면으로 303, 그 화면에 사유(알림)와 스캔칸이 함께 있다."""
    bad = []
    for role, path, data, screen in pop_scan_posts(world.v):
        c = client(role)
        r = c.post(path, data=data, headers={**HTML, "referer": f"http://testserver{screen}"})
        if r.status_code != 303 or not r.headers.get("location", "").endswith(screen):
            bad.append(f"POST {path} → {r.status_code} {r.headers.get('location')}")
            continue
        page = c.get(r.headers["location"], headers=HTML)
        flash = flash_of(page.text)
        if page.status_code != 200 or "data-scan" not in page.text or NONE not in json.dumps(flash, ensure_ascii=False):
            bad.append(f"POST {path} 뒤 화면 {page.status_code} · 스캔칸 {'data-scan' in page.text} · 알림 {flash}")
    assert bad == []


def test_form_post_422_without_referer_lands_on_a_real_page(world):
    """Referer 가 없는 폼 POST 의 422 — 돌아간 곳이 열리는 화면이어야 한다(알림을 볼 수 있어야 한다).
    지금은 POST 전용 주소로 303 을 보내 405 가 난다.  → DEF-QA1-005"""
    bad = []
    for role, path, data, _screen in pop_scan_posts(world.v):
        c = client(role)
        r = c.post(path, data=data, headers=HTML)
        page = c.get(r.headers.get("location", "/"), headers=HTML) if r.status_code == 303 else r
        if page.status_code != 200:
            bad.append(f"POST {path} → {r.status_code} {r.headers.get('location')} → GET {page.status_code}")
    assert not bad, " / ".join(bad)


# ════════════════════════════════════════════════════════════════════════
# 401 — 인증 실패
# ════════════════════════════════════════════════════════════════════════
def test_401_login_failure(world):
    v = world.v
    for login_id, pw in ((v["login_user"], "틀린-비밀번호"), (f"{world.tag.lower()}-nobody", "x"), (v["login_user"], "")):
        c = anon()
        r = c.post("/login", data={"login_id": login_id, "password": pw})
        assert r.status_code in (401, 422) and r.status_code != 200, r.text
        if pw:
            err(r, 401, "unauthorized")
        assert c.get("/bas/items").status_code == 401, "로그인에 실패했는데 세션이 생겼다"
    r = anon().post("/login", data={"login_id": v["login_user"], "password": "틀린-비밀번호"}, headers=HTML)
    assert r.status_code == 401 and 'name="password"' in r.text, "브라우저는 로그인 화면을 401 로 다시 그린다"
    logged = cs.db1("select count(*) as n from sys_access_log where log_type = '로그인' and result = '실패' and login_id = %s",
                    (v["login_user"],))["n"]
    assert logged >= 2, "로그인 실패가 접근 로그에 남지 않았다"
    c = anon()
    assert c.post("/login", data={"login_id": v["login_user"], "password": v["login_pw"]}).status_code == 303
    assert c.get("/sta/board").status_code == 200


def test_401_browser_get_goes_to_login():
    r = anon().get("/job/orders?q=1&status=등록", headers=HTML)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login?next=%2Fjob%2Forders%3Fq%3D1")
    r = anon().post("/job/orders", headers=HTML)
    assert r.status_code == 401 and "로그인이 필요합니다" in r.text


def test_401_forged_or_cleared_session(world):
    c = anon()
    c.cookies.set("lcomfine_session", "eyJ1c2VyIjp7ImxvZ2luX2lkIjoiYWRtaW4ifX0=.forged.signature")
    err(c.get("/sys/users"), 401, "unauthorized")
    c = anon()
    assert c.post("/login", data={"login_id": world.v["login_user"], "password": world.v["login_pw"]}).status_code == 303
    assert c.get("/sta/board").status_code == 200
    assert c.post("/logout").status_code == 303
    err(c.get("/sta/board"), 401, "unauthorized")


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_401_api_docs_are_not_open_to_anonymous(path):
    """인증 없이 열리는 것은 `/health` · `/static/*` · 로그인 화면뿐이다(api-contract §2). API 문서는 엔드포인트·입력 항목을 전부 보여 준다.
    지금은 로그인 없이 200 이다.  → DEF-QA1-006"""
    assert anon().get(path).status_code in (401, 404)


def test_401_stopped_account_cannot_login(world):
    uid, pw = f"{world.tag.lower()}-u6", secrets.token_urlsafe(12)
    A = client("관리자")
    assert A.post("/sys/users", data={"login_id": uid, "user_name": "중지 (예시)", "role_code": world.role_code, "password": pw}).status_code == 200
    assert A.post(f"/sys/users/{uid}/delete").status_code == 200
    err(anon().post("/login", data={"login_id": uid, "password": pw}), 401, "unauthorized")


def test_401_stopped_account_live_session_is_cut(world):
    """중지된 계정이 **이미 열어 둔 세션**도 더는 통하지 않아야 한다(인증 실패 401).
    지금은 세션이 사용자·역할을 들고 있고 요청마다 DB 를 다시 보지 않아 계속 통한다.  → DEF-QA1-003"""
    uid, pw = f"{world.tag.lower()}-u7", secrets.token_urlsafe(12)
    A = client("관리자")
    admin_code = cs.role_logins()["관리자"]["code"]
    assert A.post("/sys/users", data={"login_id": uid, "user_name": "세션 (예시)", "role_code": admin_code, "password": pw}).status_code == 200
    u = http().session(uid, pw)
    assert u.get("/sys/users").status_code == 200
    assert A.post(f"/sys/users/{uid}/delete").status_code == 200                     # 관리자가 그 계정을 중지
    assert cs.db1("select status from sys_user where login_id = %s", (uid,))["status"] == "중지"
    got = {"조회": u.get("/sys/users").status_code, "쓰기": u.post("/bas/items").status_code}
    assert got == {"조회": 401, "쓰기": 401}, f"중지된 계정의 세션이 계속 통한다 — {got}"


# ════════════════════════════════════════════════════════════════════════
# 403 — 권한 없음 (전수는 test_qa1_rbac.py)
# ════════════════════════════════════════════════════════════════════════
def test_403_message_and_page():
    body = err(client("현장").get("/bas/items"), 403, "forbidden")
    assert body["message"] == "접근 권한이 없습니다"
    for r in (client("현장").get("/bas/items", headers=HTML), client("현장").post("/sys/users", headers=HTML)):
        assert r.status_code == 403 and "접근 권한이 없습니다" in r.text


# ════════════════════════════════════════════════════════════════════════
# 503 — DB 연결 실패 (이 프로세스의 접속 문자열만 바꾼다. PostgreSQL 은 멈추지 않는다)
# ════════════════════════════════════════════════════════════════════════
@pytest.fixture
def db_down(monkeypatch):
    from lcomfine.app import rbac

    for role in ROLES:                       # 세션은 DB 가 살아 있을 때 만들어 둔다
        client(role)
    monkeypatch.setenv("LCOMFINE_PG_DSN", "postgresql:///lcomfine_db?host=/nonexistent-q1-socket-dir")
    rbac.invalidate()
    yield
    monkeypatch.undo()
    rbac.invalidate()


def test_503_every_screen_and_function(db_down):
    """DB 가 끊기면 화면 32 · 기능 94 가 전부 503 `서비스 일시 중단` 이다 — 200 으로 멀쩡한 화면도, 500 도 없다."""
    A = client("관리자")
    pages = {p: A.get(p, headers=HTML) for p in SCREEN_PATHS}
    assert {p: r.status_code for p, r in pages.items() if r.status_code != 503} == {}
    assert all("서비스 일시 중단" in r.text for r in pages.values())
    codes = {f.id: A.request(f.method, cs.sweep_path(f)) for f in SCREEN_FNS}
    assert {k: r.status_code for k, r in codes.items() if r.status_code != 503} == {}
    assert all(r.json()["code"] == "db_unavailable" and r.json()["message"] == "서비스 일시 중단" for r in codes.values())


def test_503_other_roles_and_entry_points(db_down):
    for role in ROLES:
        assert client(role).get("/", headers=HTML).status_code == 503
        assert client(role).get("/sta/board", headers=HTML).status_code == 503
    err(client("현장").post("/mat/inputs", data={"work_id": "1", "lot_no": "X"}), 503, "db_unavailable")
    err(anon().post("/login", data={"login_id": "q1-x", "password": "x"}), 503, "db_unavailable")
    r = anon().get("/health")
    assert r.status_code == 503 and r.json()["db"]["ok"] is False
    assert anon().get("/static/style.css").status_code == 200          # 정적 파일은 DB 와 무관하다


def test_503_recovers_when_db_is_back():
    assert client("관리자").get("/bas/items", headers=HTML).status_code == 200
    assert anon().get("/health").json()["db"]["ok"] is True


# ════════════════════════════════════════════════════════════════════════
# 501 — ERP 연계 · 미확정 연계
# ════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("method,path", [("GET", "/erp/status"), ("GET", "/erp/orders"), ("POST", "/erp/shipments"), ("POST", "/erp/status")])
def test_501_erp_is_undecided(method, path):
    """무엇을 부르든 501 `ERP 연계 미확정 (D-02)` — 빈 목록이나 성공을 돌려주는 조용한 폴백이 없다."""
    body = err(client("관리자").request(method, path), 501, "undecided")
    assert body["message"] == "ERP 연계 미확정 (D-02)" and body["decision"] == "D-02"
    page = client("생산").request(method, path, headers=HTML)
    assert page.status_code == 501 and "미확정 (D-02)" in page.text
    err(anon().request(method, path), 401, "unauthorized")


# ════════════════════════════════════════════════════════════════════════
# 500 — 처리되지 않은 예외 + 로그
# ════════════════════════════════════════════════════════════════════════
def test_500_unhandled_exception_is_logged():
    c = private_app()
    try:
        body = err(c.get("/q1-boom"), 500, "internal_error")
        assert body["message"] == "예상하지 못한 오류"
        page = c.get("/q1-boom", headers=HTML)
        assert page.status_code == 500 and "예상하지 못한 오류" in page.text
        rows = cs.db("select log_type, result, method, detail from sys_access_log where path = '/q1-boom' order by log_id")
        assert len(rows) == 2 and all(r["log_type"] == "오류" and r["result"] == "실패" for r in rows)
        assert "RuntimeError" in rows[0]["detail"] and "Q1 의도한 예외" in rows[0]["detail"]
    finally:
        cs.db("delete from sys_access_log where path = '/q1-boom'")


def test_405_wrong_method_is_not_500():
    assert client("관리자").put("/bas/items").status_code == 405
    assert client("관리자").delete("/bas/items/1").status_code == 405
