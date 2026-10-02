#!/usr/bin/env python
"""로컬 `.env` 를 만든다 — `make setup` 이 부른다.

`.env.example` 을 베껴 오되 비밀 두 개(`LCOMFINE_SESSION_SECRET` · `LCOMFINE_SEED_PASSWORD`)가 비어 있으면
이 자리에서 난수로 채운다. **값은 화면에 찍지 않고 저장소에도 들어가지 않는다**(`.env` 는 gitignore, G-19).
이미 `.env` 가 있으면 비어 있는 비밀만 채우고 나머지는 건드리지 않는다.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
SECRETS = ("LCOMFINE_SESSION_SECRET", "LCOMFINE_SEED_PASSWORD")


def main() -> int:
    if not EXAMPLE.exists():
        print("FAIL .env.example 이 없다")
        return 1
    src = ENV if ENV.exists() else EXAMPLE
    out: list[str] = []
    filled: list[str] = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw
        for key in SECRETS:
            if raw.strip() == f"{key}=":
                line = f"{key}={secrets.token_urlsafe(24)}"
                filled.append(key)
        out.append(line)
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    ENV.chmod(0o600)
    print(f".env {'갱신' if src == ENV else '생성'} — 난수로 채운 비밀 {len(filled)}개 ({', '.join(filled) or '없음'}) · 값은 출력하지 않는다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
