#!/usr/bin/env python
"""백업 · 복구 검증 (G-20) — `make backup` · `make restore-check`.

    uv run python tools/backup.py backup                  # pg_dump → backups/<DB>-<일시>.dump + 같은 이름의 .json(테이블별 행 수)
    uv run python tools/backup.py restore-check [덤프]    # 덤프(기본: backups/ 의 가장 최근 것)를 **별도의 임시 DB** 에 복구해 행 수를 대조

지키는 것
  · **운영 DB(`LCOMFINE_PG_DSN`)에는 쓰지 않는다.** 백업은 읽기만 하고, 복구 검증은 `createdb` 로 만든 임시 DB
    (`<DB>_restore_check_<프로세스>_<시각>`)에만 복구한 뒤 `dropdb` 로 지운다. 임시 DB 이름이 운영 DB 와 같으면 시작하지 않는다.
  · 행 수의 기준은 **덤프를 뜬 그 순간**이다. 덤프와 행 수 세기를 한 스냅샷(`pg_export_snapshot` → `pg_dump --snapshot`)에서 해서,
    다른 사람이 같은 DB 에 쓰는 중이어도 덤프의 내용과 기준 행 수가 어긋나지 않는다. 복구 검증은 복구된 임시 DB 의 행 수를 그 기준과 대조한다.
  · 조용히 통과하지 않는다 — 덤프가 비었거나, 테이블이 빠졌거나, 한 테이블이라도 행 수가 다르면 종료코드 1.
  · 접속 비밀번호는 명령줄 인자·출력·기준 파일에 남기지 않는다(자식 프로세스의 환경변수로만 넘긴다). `backups/` 는 gitignore 다.

`pg_dump` · `pg_restore` 가 PATH 에 있어야 한다(서버와 같은 주 버전). 보존 기간·보관 위치·주기는 운영 환경(D-03)이 정해지면 정한다 —
이 도구는 덤프를 지우지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from lcomfine.db import conn as appconn  # noqa: E402 — `.env` 를 읽고 DSN 을 준다

BACKUP_DIR = ROOT / "backups"
TEMP_DB_MARK = "_restore_check_"


class BackupError(RuntimeError):
    """사람이 읽을 사유와 함께 종료코드 1 로 끝낸다."""


# ── 접속 정보 ────────────────────────────────────────────────────────────
def conn_params() -> dict[str, str]:
    """`LCOMFINE_PG_DSN` → libpq 인자. DB 이름이 없으면 진행하지 않는다(어느 DB 인지 지어내지 않는다)."""
    params = {k: str(v) for k, v in conninfo_to_dict(appconn.dsn()).items() if v is not None}
    if not params.get("dbname"):
        raise BackupError("LCOMFINE_PG_DSN 에 DB 이름이 없다")
    return params


def conninfo(params: dict[str, str], *, dbname: str | None = None) -> str:
    """비밀번호를 뺀 접속 문자열(자식 프로세스의 인자·출력에 써도 된다)."""
    p = {k: v for k, v in params.items() if k != "password"}
    if dbname:
        p["dbname"] = dbname
    return make_conninfo(**p)


def child_env(params: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    if params.get("password"):
        env["PGPASSWORD"] = params["password"]
    return env


def connect(params: dict[str, str], *, dbname: str | None = None, autocommit: bool = True) -> psycopg.Connection:
    p = dict(params)
    if dbname:
        p["dbname"] = dbname
    return psycopg.connect(make_conninfo(**p), autocommit=autocommit)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise BackupError(f"`{tool}` 을 찾을 수 없다 — PostgreSQL 클라이언트 도구가 PATH 에 있어야 한다")
    return path


def run(cmd: list[str], env: dict[str, str]) -> None:
    p = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise BackupError(f"`{Path(cmd[0]).name}` 실패 (종료코드 {p.returncode}) — {(p.stderr or p.stdout).strip()[-600:]}")


def table_counts(cur: psycopg.Cursor) -> dict[str, int]:
    """public 스키마의 테이블별 행 수 (이 커서의 트랜잭션이 보는 그대로)."""
    cur.execute("select tablename from pg_tables where schemaname = 'public' order by tablename")
    names = [r[0] for r in cur.fetchall()]
    out: dict[str, int] = {}
    for name in names:
        cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier("public", name)))
        out[name] = cur.fetchone()[0]
    return out


# ── 백업 ────────────────────────────────────────────────────────────────
def backup() -> int:
    params = conn_params()
    db = params["dbname"]
    pg_dump = need("pg_dump")
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dump = BACKUP_DIR / f"{db}-{stamp}.dump"
    manifest = dump.with_suffix(".json")
    if dump.exists() or manifest.exists():
        raise BackupError(f"같은 이름의 덤프가 이미 있다 — {dump.name} (덮어쓰지 않는다)")

    # 덤프와 행 수를 **같은 스냅샷**에서 뜬다 — 이 트랜잭션이 열려 있는 동안 pg_dump 가 그 스냅샷을 쓴다. 읽기만 한다.
    with connect(params, autocommit=False) as c, c.cursor() as cur:
        cur.execute("set transaction isolation level repeatable read read only")
        cur.execute("select pg_export_snapshot(), current_setting('server_version')")
        snapshot, server_version = cur.fetchone()
        counts = table_counts(cur)
        try:
            run([pg_dump, "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}",
                 f"--file={dump}", f"--dbname={conninfo(params)}"], child_env(params))
        except BackupError:
            dump.unlink(missing_ok=True)   # 반쯤 쓴 덤프를 남겨 두지 않는다
            raise
        c.rollback()
    if not dump.exists() or dump.stat().st_size == 0:
        dump.unlink(missing_ok=True)
        raise BackupError("pg_dump 가 빈 덤프를 만들었다")
    manifest.write_text(json.dumps({"database": db, "taken_at": datetime.now().isoformat(timespec="seconds"),
                                    "server_version": server_version, "dump": dump.name, "tables": counts},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"백업 — DB `{db}` (PostgreSQL {server_version}) → {dump.relative_to(ROOT)} ({dump.stat().st_size:,}B)")
    print(f"기준 행 수 — 테이블 {len(counts)}개 · 행 {sum(counts.values()):,} → {manifest.relative_to(ROOT)}")
    print("다음: `make restore-check` — 이 덤프를 임시 DB 에 복구해 테이블별 행 수를 대조한다")
    return 0


# ── 복구 검증 ───────────────────────────────────────────────────────────
def latest_dump() -> Path:
    dumps = sorted(BACKUP_DIR.glob("*.dump"), key=lambda p: p.stat().st_mtime) if BACKUP_DIR.exists() else []
    if not dumps:
        raise BackupError("backups/ 에 덤프가 없다 — 먼저 `make backup`")
    return dumps[-1]


def restore_check(dump_arg: str | None) -> int:
    params = conn_params()
    source_db = params["dbname"]
    pg_restore = need("pg_restore")
    dump = Path(dump_arg).resolve() if dump_arg else latest_dump()
    manifest = dump.with_suffix(".json")
    if not dump.exists():
        raise BackupError(f"덤프가 없다 — {dump}")
    if not manifest.exists():
        raise BackupError(f"기준 행 수 파일이 없다 — {manifest.name} (이 도구의 `backup` 으로 뜬 덤프만 검증한다)")
    want: dict[str, int] = json.loads(manifest.read_text(encoding="utf-8"))["tables"]

    temp_db = f"{source_db}{TEMP_DB_MARK}{os.getpid()}_{int(time.time())}"
    if temp_db == source_db or TEMP_DB_MARK not in temp_db:
        raise BackupError("임시 DB 이름이 운영 DB 와 구분되지 않는다 — 복구하지 않는다")
    print(f"복구 검증 — 덤프 {dump.relative_to(ROOT) if dump.is_relative_to(ROOT) else dump} → 임시 DB `{temp_db}` "
          f"(운영 DB `{source_db}` 에는 쓰지 않는다)")

    admin = connect(params, dbname="postgres")   # CREATE/DROP DATABASE 는 다른 DB 에 붙어서 한다
    created = False
    try:
        if admin.execute("select 1 from pg_database where datname = %s", (temp_db,)).fetchone():
            raise BackupError(f"임시 DB `{temp_db}` 가 이미 있다 — 지우지 않고 멈춘다")
        enc = admin.execute("select pg_encoding_to_char(encoding), datcollate, datctype from pg_database where datname = %s",
                            (source_db,)).fetchone()
        if enc is None:
            raise BackupError(f"운영 DB `{source_db}` 를 찾을 수 없다")
        admin.execute(sql.SQL("create database {} template template0 encoding {} lc_collate {} lc_ctype {}").format(   # createdb
            sql.Identifier(temp_db), sql.Literal(enc[0]), sql.Literal(enc[1]), sql.Literal(enc[2])))
        created = True
        run([pg_restore, "--no-owner", "--no-privileges", "--exit-on-error", f"--dbname={conninfo(params, dbname=temp_db)}",
             str(dump)], child_env(params))
        with connect(params, dbname=temp_db) as c, c.cursor() as cur:
            got = table_counts(cur)
            cur.execute("select count(*) from pg_trigger where not tgisinternal")
            n_triggers = cur.fetchone()[0]
            cur.execute("select count(*) from pg_views where schemaname = 'public'")
            n_views = cur.fetchone()[0]
    finally:
        try:
            if created:
                admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(temp_db)))   # dropdb
        finally:
            admin.close()

    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    differ = {t: (want[t], got[t]) for t in sorted(set(want) & set(got)) if want[t] != got[t]}
    w = max((len(t) for t in want), default=10)
    for t in sorted(want):
        mark = "없음" if t in missing else ("다름" if t in differ else "같음")
        print(f"  {t:<{w}}  덤프 시점 {want[t]:>8,}  복구 {got.get(t, 0):>8,}  {mark}")
    print(f"임시 DB `{temp_db}` 삭제함 · 복구된 트리거 {n_triggers} · 뷰 {n_views}")
    if missing or extra or differ:
        print(f"판정: FAIL — 행 수 불일치 · 복구에 없는 테이블 {missing or 0} · 덤프 기준에 없는 테이블 {extra or 0} · 행 수가 다른 테이블 {differ or 0}")
        return 1
    if not want:
        print("판정: FAIL — 기준 행 수 파일에 테이블이 없다 (빈 덤프)")
        return 1
    print(f"판정: PASS — 테이블 {len(want)}개 전부 복구 · 테이블별 행 수 일치 (행 {sum(want.values()):,})")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("backup", "restore-check"):
        print(__doc__.strip().splitlines()[0])
        print("사용법: tools/backup.py backup | restore-check [덤프 파일]")
        return 2
    try:
        return backup() if argv[0] == "backup" else restore_check(argv[1] if len(argv) > 1 else None)
    except BackupError as exc:
        print(f"FAIL — {exc}")
        return 1
    except psycopg.OperationalError as exc:
        print(f"FAIL — DB 에 접속할 수 없다: {str(exc).strip().splitlines()[0]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
