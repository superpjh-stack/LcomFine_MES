"""QA1 테스트 공용 도구 — 검사기(`tools/check_screens.py`)를 라이브러리로 쓴다. (테스트 함수는 없다)

- 기대값은 설계도(§5 IA · §6 권한 표)와 `contracts/function-list.md` 를 검사기의 **자체 파서**로 읽은 것이다.
  앱의 `nav` · `contracts` · `rbac` 가 스스로 적은 값을 기대값으로 쓰지 않는다.
- 요청은 같은 프로세스의 TestClient 로 보낸다(실제 서버로 보내는 것은 `uv run python tools/check_screens.py`).
- 테스트 데이터의 업무 코드는 전부 `Q1-<6자>-…` 이고 모듈이 끝나면 지운다. 시드 계정 4개는 **로그인에만** 쓴다 —
  시드 역할의 권한 48칸과 시드 계정의 행을 바꾸지 않는다(권한 표를 바꿔 보는 검사는 검사 전용 역할로 한다).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_screens as cs  # noqa: E402

HTML = cs.HTML
ACCESS = cs.design_access()            # 설계도 §6 — {roles, cells}
IA = cs.design_ia()                    # 설계도 §5 — [{menu, count, subs}]
FNS = cs.contract_functions()          # 계약 100줄
SCREEN_FNS = [f for f in FNS if not f.is_batch]
WRITE_FNS = [f for f in SCREEN_FNS if f.is_write]
READ_FNS = [f for f in SCREEN_FNS if not f.is_write]
BATCH_FNS = [f for f in FNS if f.is_batch]
ROLES = ACCESS["roles"]                # 관리자 · 생산 · 품질 · 현장 (설계도 표의 열 순서)
SCREEN_PATHS = cs.screen_paths(FNS)    # 화면 경로 → 대메뉴명 (32)
FN = {f.id: f for f in FNS}

_http: cs.Http | None = None
_sessions: dict[str, object] = {}


def http() -> cs.Http:
    global _http
    if _http is None:
        _http = cs.Http(inprocess=True)
    return _http


def client(role: str):
    """그 역할(설계도의 역할명)의 시드 계정으로 로그인한 세션 — 역할마다 하나를 돌려쓴다."""
    if role not in _sessions:
        _sessions[role] = http().session(cs.role_logins()[role]["login_id"])
    return _sessions[role]


def anon():
    return http().session()


def build_world(batch: bool = False) -> cs.Flow:
    """한 Job 을 화면 API 로 끝까지 흘린 세계 — 기준정보 · Job · LOT · 롤 · 검사 · 출하(승인) · 계정 · 검사 전용 역할."""
    return cs.Flow(http()).run(batch=batch)


def drop_world(flow: cs.Flow) -> None:
    cs.cleanup(flow.tag)
    left = cs.leftovers(flow.tag)
    assert not left, f"뒷정리 뒤에 Q1 행이 남았다: {left}"


def failed_steps(flow: cs.Flow, fn_id: str) -> list[str]:
    return [f"[{s.role}] {s.call} → {s.status} {s.evidence}" for s in flow.by_fn().get(fn_id, []) if not s.ok]


def err(resp, status: int, code: str) -> dict:
    """오류 계약(goal.md §2.5) — 상태코드와 `code` 를 함께 본다."""
    assert resp.status_code == status, f"기대 {status}, 실제 {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body["code"] == code, body
    return body


def invalid(resp) -> dict:
    """422 `validation_error` + 사람이 읽을 문장."""
    body = err(resp, 422, "validation_error")
    assert body["message"], body
    return body
