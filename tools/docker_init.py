"""컨테이너 첫 기동 — 빈 DB 면 스키마를 만들고, 이어서 공통 시드를 돌린다 (docker-compose 의 `seed` 서비스가 부른다).

    /app/.venv/bin/python tools/docker_init.py [seed 인자 …]      # 예: --common-only

- 스키마는 **테이블이 하나도 없을 때만** 만든다(`src/lcomfine/db/schema.sql` 그대로). 테이블이 있으면 건드리지 않는다 —
  그 뒤의 스키마 변경은 이관 SQL(ALTER)로 반영한다(D-08). 호스트 bind-mount(`docker-entrypoint-initdb.d`)를 쓰지 않는 이유는
  compose 파일만 받아 가는 배포 도구(Hostinger Docker Manager 등)에는 호스트에 저장소가 없기 때문이다(D-31).
- 시드는 `lcomfine.db.seed` 그대로 — 두 번 돌려도 행 수가 같다(G-09). 비밀번호는 `LCOMFINE_SEED_PASSWORD` 로만(G-19).
- 실패는 삼키지 않는다 — 스키마 SQL 오류·DB 접속 실패는 그대로 올라가 `seed` 서비스가 실패하고 `app` 은 뜨지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lcomfine.db import conn, seed

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "lcomfine" / "db" / "schema.sql"


def table_count() -> int:
    return conn.q1("select count(*) as n from information_schema.tables "
                   "where table_schema = 'public' and table_type = 'BASE TABLE'")["n"]


def main(argv: list[str]) -> int:
    before = table_count()
    if before == 0:
        with conn.tx() as cur:
            cur.execute(SCHEMA.read_text(encoding="utf-8"))
        print(f"스키마 — 빈 DB 에 {SCHEMA.name} 적용 → 테이블 {table_count()}")
    else:
        print(f"스키마 — 테이블 {before} 있음 · 건너뜀 (변경은 ALTER 이관으로)")
    return seed.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
