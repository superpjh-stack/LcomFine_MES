#!/usr/bin/env python
"""로컬 `.env` 를 만든다 — `make setup` 이 부른다.

`.env` 가 없으면 `.env.example` 을 베껴 오고, 비밀(`SECRETS`)이 비어 있으면 이 자리에서 난수로 채운다.
**값은 화면에 찍지 않고 저장소에도 들어가지 않는다**(`.env` 는 gitignore, G-21).

이미 `.env` 가 있으면 **있는 키는 한 글자도 바꾸지 않는다.** 하는 일은 둘뿐이다:
  · `.env` 에서 값이 비어 있는 비밀 줄(`KEY=`)을 난수로 채운다
  · `.env.example` 에 있는데 `.env` 에 줄째로 없는 키를 뒤에 덧붙인다 — 비밀이면 난수, 아니면 예시 줄 그대로
    (`LCOMFINE_OPENAI_API_KEY=` 처럼 예시가 빈 값이면 빈 줄로 — 키 값은 사람이 넣는다)
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
#: 난수로 채우는 비밀. `LCOMFINE_OPENAI_API_KEY` 는 비밀이지만 난수로 만들 수 없으므로 여기 없다(빈 줄로 둔다)
SECRETS = ("LCOMFINE_SESSION_SECRET", "LCOMFINE_SEED_PASSWORD", "LCOMFINE_DB_PASSWORD", "LCOMFINE_APP_DB_PASSWORD", "LCOMFINE_SSO_SECRET")


def _key(line: str) -> str | None:
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    return s.split("=", 1)[0].strip()


def main() -> int:
    if not EXAMPLE.exists():
        print("FAIL .env.example 이 없다")
        return 1
    example = EXAMPLE.read_text(encoding="utf-8").splitlines()
    existed = ENV.exists()
    src = ENV.read_text(encoding="utf-8").splitlines() if existed else example
    out: list[str] = []
    filled: list[str] = []
    for raw in src:
        line = raw
        k = _key(raw)
        if k in SECRETS and raw.strip() == f"{k}=":
            line = f"{k}={secrets.token_urlsafe(24)}"
            filled.append(k)
        out.append(line)
    have = {k for k in map(_key, out) if k}
    added: list[str] = []
    for raw in example:            # 예전에 만든 .env 에 줄째로 없는 키 — 덧붙이기만 한다
        k = _key(raw)
        if not k or k in have:
            continue
        out.append(f"{k}={secrets.token_urlsafe(24)}" if k in SECRETS else raw.strip())
        (filled if k in SECRETS else added).append(k)
        have.add(k)
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    ENV.chmod(0o600)
    print(f".env {'갱신' if existed else '생성'} — 난수로 채운 비밀 {len(filled)}개 ({', '.join(filled) or '없음'})"
          f" · 덧붙인 키 {len(added)}개 ({', '.join(added) or '없음'}) · 있던 키는 그대로 · 값은 출력하지 않는다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
