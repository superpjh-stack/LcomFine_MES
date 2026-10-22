"""AI 호출 — OpenAI 를 부르는 **유일한 곳**(D-504 · 개발3 · W3 · `contracts/interfaces.md` §9).

    complete(system, user, *, kind, cur=None, user_id=None) -> str   한 번 묻고 답 글자를 돌려준다
    NotConfigured                                                    키(`LCOMFINE_OPENAI_API_KEY`)가 없다 — 화면이 그 사실을 그대로 보인다(G-17)
    CallFailed                                                       호출이 실패했다(네트워크 · HTTP · 응답 형식) — 사유를 담는다
    set_client(fake)                                                 테스트 주입 — fake(model, system, user) -> str. None 이면 실제 호출로 되돌린다

**호출마다 `sys_ai_call_log` 1행** — 성공 · 실패(키 없음 포함) · 걸린 시간. `cur` 를 주면 그 트랜잭션 안에서, 없으면 자체 연결로 쓴다.
키 · 모델은 `settings` 로만 읽고 **값은 어디에도 적지 않는다**(G-21) — 로그의 실패 사유에서 키 글자는 가린다.
조용한 실패 금지: 실패를 잡아 기본 답을 돌려주지 않는다 — 예외로 올리고 화면이 보인다.
의존성은 표준 라이브러리 `urllib` 만(새 패키지 없음).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from ..db import conn
from .settings import get_settings

#: OpenAI Chat Completions 주소 (D-504)
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
#: 호출 제한 시간(초) — 데이터 질의는 사람이 기다리는 화면이다
TIMEOUT_SECONDS = 30
#: 실패 사유 글자 상한 (sys_ai_call_log.error)
ERROR_MAX = 500
#: 키 없음 — 화면 · 로그에 그대로 쓰는 문장 (G-17). 키 값은 적지 않는다
NOT_CONFIGURED_MESSAGE = "AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY"


class NotConfigured(RuntimeError):
    """키가 없다. 화면은 이 사실을 명시적으로 보인다(조용히 넘어가지 않는다)."""


class CallFailed(RuntimeError):
    """호출이 실패했다(네트워크 · HTTP 오류 · 응답 형식). 사유는 str(exc)."""


Client = Callable[[str, str, str], str]
_client: Client | None = None


def set_client(fake: Client | None) -> None:
    """테스트 주입. `fake(model, system, user) -> str`. None 이면 실제 OpenAI 호출로 되돌린다."""
    global _client
    _client = fake


def _config() -> tuple[str, str]:
    """(키, 모델) — `settings` 에서만 읽는다."""
    s = get_settings()
    return s.openai_api_key, s.openai_model


#: 키처럼 보이는 글자 — 값이 무엇이든 가린다(`Bearer …` 헤더 · OpenAI `sk-…` 꼴) — 심층 방어(DEF-QA3-006)
_KEY_PATTERNS = (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), re.compile(r"sk-[A-Za-z0-9._\-]{8,}"))


def _mask(text: str, key: str) -> str:
    """실패 사유에서 키 글자를 가린다 — 설정된 키 값 · `Bearer …` · `sk-…` 꼴. 로그 · 예외 문장 · 응답 어디로 가도 키가 없다."""
    text = text or ""
    if key:
        text = text.replace(key, "***")
    for pat in _KEY_PATTERNS:
        text = pat.sub("***", text)
    return text[:ERROR_MAX]


def _log(cur, *, kind: str, model: str, ok: bool, ms: int, error: str | None, user_id: int | None) -> None:
    sql = "insert into sys_ai_call_log (kind, model, ok, ms, error, user_id) values (%s, %s, %s, %s, %s, %s)"
    params = (kind, model, ok, ms, error, user_id)
    if cur is not None:
        cur.execute(sql, params)
    else:
        conn.x(sql, params)


def _openai(model: str, system: str, user: str, *, key: str) -> str:
    """실제 호출 — 이 함수 하나가 바깥으로 나가는 유일한 길이다(D-504)."""
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode("utf-8")
    req = urllib.request.Request(OPENAI_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:   # noqa: BLE001 — 본문을 못 읽어도 상태코드는 남긴다
            detail = ""
        raise CallFailed(f"HTTP {exc.code} {exc.reason} {detail}".strip()) from None
    except urllib.error.URLError as exc:
        raise CallFailed(f"연결 실패 — {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise CallFailed(f"연결 실패 — {exc}") from None
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise CallFailed("응답 형식이 다르다 — choices[0].message.content 없음") from None


def complete(system: str, user: str, *, kind: str, cur=None, user_id: int | None = None) -> str:
    """질문 하나 → 답 글자. 키가 없으면 `NotConfigured`, 실패하면 `CallFailed` — 둘 다 **로그를 남긴 뒤** 올린다.

    kind      sys_ai_call_log.kind (예: `데이터 질의`)
    cur       쓰기 트랜잭션의 커서 — 로그를 같은 트랜잭션에 쓴다. None 이면 자체 연결
    user_id   부른 사용자(sys_user.user_id)
    """
    key, model = _config()
    t0 = time.monotonic()
    if _client is None and not key:
        _log(cur, kind=kind, model=model, ok=False, ms=0, error=NOT_CONFIGURED_MESSAGE, user_id=user_id)
        raise NotConfigured(NOT_CONFIGURED_MESSAGE)
    try:
        text = _client(model, system, user) if _client is not None else _openai(model, system, user, key=key)
    except CallFailed as exc:
        masked = _mask(str(exc), key)       # HTTP 오류 본문이 키를 되비춰도 — 로그 · 올리는 예외 둘 다 가린 문장(DEF-QA3-006)
        _log(cur, kind=kind, model=model, ok=False, ms=int((time.monotonic() - t0) * 1000), error=masked, user_id=user_id)
        raise CallFailed(masked) from None
    except Exception as exc:   # noqa: BLE001 — 주입된 클라이언트의 예외도 실패로 기록하고 올린다(삼키지 않는다)
        _log(cur, kind=kind, model=model, ok=False, ms=int((time.monotonic() - t0) * 1000),
             error=_mask(f"{type(exc).__name__}: {exc}", key), user_id=user_id)
        raise CallFailed(_mask(f"{type(exc).__name__}: {exc}", key)) from exc
    if not isinstance(text, str):
        _log(cur, kind=kind, model=model, ok=False, ms=int((time.monotonic() - t0) * 1000), error="응답이 글자가 아니다", user_id=user_id)
        raise CallFailed("응답이 글자가 아니다")
    _log(cur, kind=kind, model=model, ok=True, ms=int((time.monotonic() - t0) * 1000), error=None, user_id=user_id)
    return text
