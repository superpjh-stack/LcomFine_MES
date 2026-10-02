"""QA3 테스트 도우미 (테스트 함수 없음) — `tools/check_security.py` 의 임시 세계와 브라우저 실측을 pytest 에서 쓴다.

- 임시 데이터는 접두 `Q3T<꼬리표>-`(기준정보) · `Q3N<꼬리표>-`(이관) · 계정 `q3t<꼬리표>-…` 로 만든다 — 검사기(`Q3C…` · `Q3M…` · `q3c…`)와도,
  동시에 도는 다른 pytest 실행과도 겹치지 않는다(꼬리표 = 프로세스 번호).
- 시드 계정 4개와 권한 표는 바꾸지 않는다. 계정 중지·잠금은 임시 계정으로만 한다.
- 결함을 드러내는 테스트는 **실패하는 채로 둔다**(skip/xfail 없음). 고쳐지면 통과한다.
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_security as cs  # noqa: E402

# pytest 도 여러 벌이 동시에 돈다(다른 QA 의 전체 실행에 이 파일이 끼어 돈다) → 실행마다 다른 꼬리표
cs.PREFIX, cs.MIG, cs.TMP_USER = f"Q3T{cs.TAG}-", f"Q3N{cs.TAG}-", f"q3t{cs.TAG.lower()}-"

from fastapi.testclient import TestClient  # noqa: E402

from lcomfine.app.main import app  # noqa: E402
from lcomfine.app.settings import get_settings  # noqa: E402
from lcomfine.db import conn  # noqa: E402

HTML = {"accept": "text/html"}


def build_world() -> "cs.World":
    """쓰기 기능 54개를 화면 API 로 한 번씩 부른 임시 세계. 만들다 실패하면 `error` 에 사유가 남는다."""
    w = cs.World()
    w.cleanup()
    try:
        w.build()
    except Exception as exc:  # noqa: BLE001 — 실패 사유는 테스트가 단언으로 드러낸다
        w.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    return w


def temp_user(role_code: str = "QC") -> tuple[str, str]:
    """관리자 화면 API 로 임시 계정을 만든다 → (login_id, 비밀번호). 비밀번호는 난수이고 어디에도 적지 않는다."""
    login_id, password = f"{cs.TMP_USER}{secrets.token_hex(4)}", secrets.token_urlsafe(12)
    r = cs.cl("admin").post("/sys/users", data={"login_id": login_id, "user_name": "임시 (예시) Q3", "role_code": role_code, "password": password})
    assert r.status_code == 200, r.text
    return login_id, password


def login(login_id: str, password: str | None = None) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"login_id": login_id, "password": password or get_settings().seed_password}, follow_redirects=False)
    assert r.status_code == 303, f"{login_id} 로그인 {r.status_code}"
    return c


def run_probe(world: "cs.World", *extra: str) -> dict:
    """실제 브라우저 실측(`tools/e2e/probe.py`). 띄우지 못하면 그 사실로 실패시킨다 — 건너뛰지 않는다."""
    keys = ("job_no", "lot_no", "print_roll", "roll", "shipment_no", "probe_shipment_no", "probe_rolls")
    out_file = ROOT / "outputs" / "e2e" / f"_probe_pytest_{cs.TAG}.json"
    rc, out = cs.run(["uv", "run", "--with", "playwright", "python", str(ROOT / "tools" / "e2e" / "probe.py"),
                      "--world", json.dumps({k: world.v[k] for k in keys if world.v.get(k)}, ensure_ascii=False),
                      "--out", str(out_file), *extra], timeout=600)
    assert rc == 0, f"브라우저 실측을 돌리지 못했다 (rc {rc}): {out[-400:]}"
    data = json.loads(out_file.read_text(encoding="utf-8"))
    out_file.unlink(missing_ok=True)
    return data
