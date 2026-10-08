"""모든 계정의 비밀번호를 `LCOMFINE_SEED_PASSWORD` 하나로 맞춘다 (`make db-passwords`).

- 값은 `.env` 의 환경변수로만 받는다. 코드·문서·출력 어디에도 비밀번호 값을 쓰지 않는다 (G-19).
- 이미 그 값인 계정은 건드리지 않는다 — 해시를 다시 쓰면 `sys_user_session_epoch_trg` 가 그 계정의 세션을 전부 끊는다 (D-26).
- 상태(정상·잠금·중지)·역할·실패 횟수는 그대로 둔다. 바꾸는 것은 비밀번호 해시뿐이다.
- 개발·테스트 DB 용이다. 운영 DB 에는 쓰지 않는다 (D-416).
"""

from __future__ import annotations

import sys

from lcomfine.app import auth
from lcomfine.app.settings import get_settings
from lcomfine.db import conn


def main() -> int:
    password = get_settings().seed_password
    if not password:
        print("FAIL LCOMFINE_SEED_PASSWORD 미설정 — `.env` 에 넣는다 (`make setup`). 기본 비밀번호는 없다 (G-19)")
        return 1
    rows = conn.q("select login_id, password_hash from sys_user order by user_id")
    changed: list[str] = []
    for r in rows:
        if auth.verify_password(password, r["password_hash"] or ""):
            continue
        conn.x("update sys_user set password_hash = %s, updated_at = now(), updated_by = %s where login_id = %s",
               (auth.hash_password(password), "reset_passwords", r["login_id"]))
        changed.append(r["login_id"])
    print(f"계정 {len(rows)} · 비밀번호 맞춘 계정 {len(changed)} · 이미 같아서 둔 계정 {len(rows) - len(changed)}"
          + (f" · 바뀐 계정: {', '.join(changed[:8])}{' …' if len(changed) > 8 else ''}" if changed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
