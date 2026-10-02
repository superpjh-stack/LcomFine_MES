"""공통 시드 — 역할 4 · 권한 표 48칸 · 역할별 계정 4. **두 번 돌려도 행 수가 같다**(G-09).

    uv run python -m lcomfine.db.seed                      # 공통 → 개발1 → 개발2 → 개발3 시드(파일이 있는 것만)
    uv run python -m lcomfine.db.seed --common-only        # 공통만
    uv run python -m lcomfine.db.seed --reset-permissions  # 권한 표를 아래 기본값으로 되돌린다

- 권한 표 기본값 `PERMISSIONS` 는 goal.md §6(= 설계도 §6) 그대로다. `tools/check_trace.py` 가 설계도와 대조한다.
  이미 있는 칸은 건드리지 않는다 — 시스템 관리 > 권한 화면에서 바꾼 값을 시드가 되돌리면 안 된다.
- 계정 비밀번호는 `LCOMFINE_SEED_PASSWORD` 로만 받는다. 없으면 **실패한다** — 기본 비밀번호를 지어내지 않는다(G-19).
- 회사 실데이터는 없다. 표시명에는 `(예시)` 를 붙인다.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from ..app import auth, nav
from ..app.settings import get_settings
from ..app.util.screen import example
from . import conn

SEEDED_BY = "seed"

# 역할 4 (설계도 §6 표의 열 순서) — (코드, 역할명, 순서). 코드는 가설(D-20)
ROLES: list[tuple[str, str, int]] = [
    ("ADMIN", "관리자", 1),
    ("PROD", "생산", 2),
    ("QC", "품질", 3),
    ("FIELD", "현장", 4),
]

# 권한 표 48칸 — goal.md §6 그대로. 열 순서 = ROLES. 괄호 조건 2개 포함.
PERMISSIONS: list[tuple[str, tuple[str, str, str, str]]] = [
    ("기준정보 관리",           ("입력", "조회", "조회", "없음")),
    ("인쇄 기준 관리",          ("입력", "입력", "조회", "조회")),
    ("작업지시 관리",           ("입력", "입력", "조회", "조회")),
    ("생산 실적 (POP)",         ("조회", "입력", "조회", "입력")),
    ("자재 · 입고",             ("조회", "입력", "입력 (입고검사)", "입력")),
    ("조색 기록",               ("조회", "조회", "입력", "입력")),
    ("후가공 · 슬리팅 롤 이력", ("조회", "입력", "조회", "입력")),
    ("품질 검사 기록",          ("조회", "조회", "입력", "조회")),
    ("출하",                    ("입력 (승인)", "입력", "조회", "입력")),
    ("LOT 추적",                ("조회", "조회", "조회", "없음")),
    ("실적 현황",               ("조회", "조회", "조회", "조회")),
    ("시스템 관리",             ("입력", "없음", "없음", "없음")),
]

# 역할별 계정 — 로그인 ID 는 역할 코드 소문자(D-20). 표시명은 (예시)
USERS: list[tuple[str, str, str]] = [
    ("admin", "관리자", "ADMIN"),
    ("prod", "생산 담당", "PROD"),
    ("qc", "품질 담당", "QC"),
    ("field", "현장 작업자", "FIELD"),
]

DEV_SEEDS = ("seed_dev1", "seed_dev2", "seed_dev3")


def parse_cell(text: str) -> tuple[str, str]:
    """권한 표 한 칸의 글자 → (level, write_scope). `입력` → ('입력','일반') · `입력 (승인)` → ('입력','승인')."""
    text = text.strip()
    if text.startswith("입력"):
        scope = text[text.index("(") + 1: text.rindex(")")].strip() if "(" in text else "일반"
        return "입력", scope
    if text in ("조회", "없음"):
        return text, ""
    raise ValueError(f"권한 표에 없는 표기: {text!r}")


def permission_rows() -> list[tuple[str, str, str, str]]:
    """(role_code, menu_code, level, write_scope) 48행."""
    rows = []
    for menu_name, cells in PERMISSIONS:
        menu = nav.menu_by_name(menu_name)   # 대메뉴명이 nav 와 다르면 여기서 실패한다
        for (role_code, _name, _no), text in zip(ROLES, cells, strict=True):
            level, scope = parse_cell(text)
            rows.append((role_code, menu.code, level, scope))
    return rows


def seed_roles() -> None:
    for code, name, sort_no in ROLES:
        conn.x("""insert into sys_role (role_code, role_name, sort_no) values (%s, %s, %s)
                  on conflict (role_code) do update set role_name = excluded.role_name, sort_no = excluded.sort_no""",
               (code, name, sort_no))


def seed_permissions(reset: bool = False) -> None:
    for role_code, menu_code, level, scope in permission_rows():
        if reset:
            conn.x("""insert into sys_permission (role_code, menu_code, level, write_scope, updated_at, updated_by)
                      values (%s, %s, %s, %s, now(), %s)
                      on conflict (role_code, menu_code) do update
                         set level = excluded.level, write_scope = excluded.write_scope,
                             updated_at = now(), updated_by = excluded.updated_by""",
                   (role_code, menu_code, level, scope, SEEDED_BY))
        else:
            conn.x("""insert into sys_permission (role_code, menu_code, level, write_scope, updated_at, updated_by)
                      values (%s, %s, %s, %s, now(), %s)
                      on conflict (role_code, menu_code) do nothing""",
                   (role_code, menu_code, level, scope, SEEDED_BY))


def seed_users() -> None:
    """시드 계정을 환경변수 비밀번호로 맞춘다(있으면 비밀번호·상태를 되돌린다 — 검사 도구가 이 계정으로 로그인한다).

    비밀번호가 이미 그 값이면 해시를 다시 쓰지 않는다 — 다시 쓰면 `sys_user_session_epoch_trg` 가 그 계정의 살아 있는 세션을
    전부 끊는다(D-26). 그래서 시드를 다시 돌려도 로그인해 있던 사람은 그대로다."""
    password = get_settings().seed_password
    if not password:
        raise SystemExit("LCOMFINE_SEED_PASSWORD 미설정 — 시드 계정을 만들 수 없다. `make setup` 으로 `.env` 를 만들거나 "
                         "환경변수로 준다. 기본 비밀번호는 두지 않는다(G-19).")
    for login_id, name, role_code in USERS:
        cur = conn.q1("select password_hash from sys_user where login_id = %s", (login_id,))
        if cur is not None and auth.verify_password(password, cur["password_hash"]):
            conn.x("""update sys_user set role_code = %s, user_name = %s, status = '정상', fail_count = 0,
                             updated_at = now(), updated_by = %s
                       where login_id = %s""",
                   (role_code, example(name), SEEDED_BY, login_id))
            continue
        conn.x("""insert into sys_user (login_id, user_name, password_hash, role_code, created_by)
                  values (%s, %s, %s, %s, %s)
                  on conflict (login_id) do update
                     set password_hash = excluded.password_hash, role_code = excluded.role_code,
                         user_name = excluded.user_name, status = '정상', fail_count = 0,
                         updated_at = now(), updated_by = excluded.created_by""",
               (login_id, example(name), auth.hash_password(password), role_code, SEEDED_BY))


def run_dev_seeds() -> list[str]:
    """개발 1·2·3 의 시드를 순서대로 돌린다. 파일이 아직 없으면 건너뛰고, 있는데 실패하면 그대로 실패한다."""
    ran: list[str] = []
    here = Path(__file__).resolve().parent
    for name in DEV_SEEDS:
        if not (here / f"{name}.py").exists():
            continue
        mod = importlib.import_module(f"lcomfine.db.{name}")
        rc = mod.main()
        if rc:
            raise SystemExit(f"{name} 실패 (종료코드 {rc})")
        ran.append(name)
    return ran


def table_counts() -> dict[str, int]:
    """public 스키마의 테이블별 행 수 — 시드 멱등(G-09) 대조용. 접근 로그는 시드와 무관하게 늘므로 뺀다."""
    names = [r["table_name"] for r in conn.q(
        """select table_name from information_schema.tables
            where table_schema = 'public' and table_type = 'BASE TABLE' order by table_name""")]
    return {n: conn.q1(f'select count(*) as n from "{n}"')["n"] for n in names if n != "sys_access_log"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    seed_roles()
    seed_permissions(reset="--reset-permissions" in argv)
    seed_users()
    ran = [] if "--common-only" in argv else run_dev_seeds()
    c = table_counts()
    levels = {r["level"]: r["n"] for r in conn.q("select level, count(*) as n from sys_permission group by level")}
    print(f"공통 시드 — 역할 {c['sys_role']} · 권한 {c['sys_permission']}칸"
          f"(입력 {levels.get('입력', 0)} · 조회 {levels.get('조회', 0)} · 없음 {levels.get('없음', 0)}) · 계정 {c['sys_user']}")
    print(f"개발 시드 — {', '.join(ran) if ran else '없음(파일 없음)'}")
    print("행 수 — " + " · ".join(f"{k} {v}" for k, v in c.items() if v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
