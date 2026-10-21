# tests/test_dev2_screens.py — 개발2 화면 GET 20 개의 권한 문장 (api-contract §1 · §4): 칸 없는 부서 403 「이 화면을 볼 권한이 없습니다」 · 칸 있는 부서 200
import pytest

from lcomfine.app import nav
from lcomfine.db import conn
from tests.test_dev2_world import login

SCREENS = ("MAT-010", "MAT-020", "MAT-030", "MAT-040", "PRD-010", "PRD-020", "PRD-030", "PRD-040",
           "INS-010", "INS-020", "INS-030", "INS-040", "QC-010", "QC-020", "QC-030",
           "INV-010", "INV-020", "INV-030", "LOT-010", "LOT-020")
CANDIDATES = ("sl", "sh", "ds", "ac", "ex", "st")       # 시드 계정 login_id = 부서 코드 소문자 (전산 관리자는 전 화면 R 이상)


@pytest.mark.fn("F-MAT-013", "F-MAT-023", "F-MAT-033", "F-MAT-041", "F-PRD-013", "F-PRD-021", "F-PRD-031", "F-PRD-041",
                "F-INS-013", "F-INS-021", "F-INS-031", "F-INS-041", "F-QC-013", "F-QC-023", "F-QC-031",
                "F-INV-011", "F-INV-023", "F-INV-032", "F-LOT-011", "F-LOT-021")
def test_screen_get_uses_screen_permission_sentence():
    cells = {(r["role_code"], r["screen_id"]) for r in conn.q("select role_code, screen_id from sys_permission")}
    clients = {lid: login(lid) for lid in CANDIDATES}
    checked_403 = 0
    for sid in SCREENS:
        path = nav.path_of(sid)
        denied = [lid for lid in CANDIDATES if (lid.upper(), sid) not in cells]
        allowed = [lid for lid in CANDIDATES if (lid.upper(), sid) in cells]
        assert denied, f"{sid}: 칸 없는 부서가 시드 계정 중에 없다"
        r = clients[denied[0]].get(path)
        assert r.status_code == 403, f"{sid} {denied[0]} {r.status_code}"
        assert r.json()["message"] == "이 화면을 볼 권한이 없습니다", f"{sid}: {r.json()}"   # 기능 문장이 아니다
        checked_403 += 1
        if allowed:
            r = clients[allowed[0]].get(path, headers={"accept": "text/html"})
            assert r.status_code == 200, f"{sid} {allowed[0]} {r.status_code}"
    assert checked_403 == 20
