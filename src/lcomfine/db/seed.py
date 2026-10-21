"""공통 시드 — 부서 8 · 권한 260칸 · 부서별 계정 8 · 채번 7 · 공통코드 3그룹. **두 번 돌려도 행 수가 같다**(G-21).

    uv run python -m lcomfine.db.seed                      # 공통 → 개발1 → 개발2 → 개발3 시드(파일이 있는 것만)
    uv run python -m lcomfine.db.seed --common-only        # 공통만

- 권한 칸은 `contracts.permission_cells()`(= `contracts/permission-matrix.md`, 정본 그대로)가 원본이다.
  시드는 그 표로 맞추고 **표에 없는 행은 지운다** — 칸을 바꾸려면 매트릭스를 고친다.
- 채번 형식 7행은 D-509 표 그대로(`(예시)` 가설). 이미 있는 행은 건드리지 않는다 — 시스템 관리 화면에서 바꾼 값을 되돌리지 않는다.
- 계정 비밀번호는 `LCOMFINE_SEED_PASSWORD` 로만 받는다. 없으면 **실패한다** — 기본 비밀번호를 지어내지 않는다(G-19).
- 회사 실데이터는 없다. 표시명에는 `(예시)` 를 붙인다. `notification_setting` 은 시드하지 않는다(행이 없으면 켜짐).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from ..app import auth, contracts, numbering
from ..app.settings import get_settings
from ..app.util.screen import example
from . import conn

SEEDED_BY = "seed"

#: 부서 8 — (코드, 정본 이름, 순서). 순서 = 권한 표의 열 순서
ROLES: list[tuple[str, str, int]] = [(code, name, i) for i, (name, code) in enumerate(contracts.ROLE_CODES.items(), 1)]

#: 부서별 계정 — 로그인 ID 는 부서 코드 소문자(전산 관리자만 `admin`). 표시명은 `<부서 이름> (예시)`
USERS: list[tuple[str, str, str]] = [("admin" if code == "ADM" else code.lower(), name, code) for code, name, _ in ROLES]

#: 채번 7 — D-509 표 `KIND-YYMM-nnnn` (예시). (종류, 접두, 날짜 형식, 자릿수)
NUMBER_RULES: list[tuple[str, str, str, int]] = [(kind, f"{kind}-", "YYMM-", 4) for kind in numbering.KINDS]
NUMBER_RULE_NOTE = "(예시) D-509 가설"

#: 공통코드 3그룹 — 값은 받은 적이 없다. 전부 `(예시)`. (그룹, 코드, 이름)
COMMON_CODES: list[tuple[str, str, str]] = [
    *[("설비", f"EQ{i:02d}", f"설비 {i}") for i in (1, 2)],
    *[("불량유형", f"DF{i:02d}", f"불량유형 {i}") for i in (1, 2, 3)],
    *[("수금수단", f"PM{i:02d}", f"수금수단 {i}") for i in (1, 2, 3)],
]

DEV_SEEDS = ("seed_dev1", "seed_dev2", "seed_dev3")


def seed_roles() -> None:
    for code, name, sort_no in ROLES:
        conn.x("""insert into sys_role (role_code, role_name, sort_no, created_by) values (%s, %s, %s, %s)
                  on conflict (role_code) do update set role_name = excluded.role_name, sort_no = excluded.sort_no""",
               (code, name, sort_no, SEEDED_BY))


def seed_permissions() -> None:
    """260칸을 매트릭스대로 맞추고, 표에 없는 (부서, 화면) 행은 지운다 — 한 트랜잭션."""
    cells = contracts.permission_cells()
    with conn.tx() as cur:
        for screen_id, role_code, level in cells:
            cur.execute("""insert into sys_permission (role_code, screen_id, level, updated_at, updated_by)
                           values (%s, %s, %s, now(), %s)
                           on conflict (role_code, screen_id) do update
                              set level = excluded.level, updated_at = now(), updated_by = excluded.updated_by
                            where sys_permission.level is distinct from excluded.level""",
                        (role_code, screen_id, level, SEEDED_BY))
        cur.execute("""delete from sys_permission p
                        where not exists (select 1 from unnest(%s::text[], %s::text[]) as c(role_code, screen_id)
                                           where c.role_code = p.role_code and c.screen_id = p.screen_id)""",
                    ([r for _, r, _ in cells], [s for s, _, _ in cells]))


def seed_number_rules() -> None:
    for kind, prefix, date_format, digits in NUMBER_RULES:
        conn.x("""insert into sys_number_rule (seq_kind, prefix, date_format, seq_digits, note, updated_at, updated_by)
                  values (%s, %s, %s, %s, %s, now(), %s)
                  on conflict (seq_kind) do nothing""",
               (kind, prefix, date_format, digits, f"{NUMBER_RULE_NOTE} — {numbering.KIND_NAMES[kind]}", SEEDED_BY))


def seed_common_codes() -> None:
    for sort_no, (group, code, name) in enumerate(COMMON_CODES, 1):
        conn.x("""insert into sys_common_code (group_code, code, code_name, sort_no, created_by)
                  values (%s, %s, %s, %s, %s)
                  on conflict (group_code, code) do nothing""",
               (group, code, example(name), sort_no, SEEDED_BY))


def seed_users() -> None:
    """시드 계정을 환경변수 비밀번호로 맞춘다(있으면 비밀번호·상태를 되돌린다 — 검사 도구가 이 계정으로 로그인한다).

    비밀번호가 이미 그 값이면 해시를 다시 쓰지 않는다 — 다시 쓰면 `sys_user_session_epoch_trg` 가 그 계정의 살아 있는 세션을
    전부 끊는다(D-26). 그래서 시드를 다시 돌려도 로그인해 있던 사람은 그대로다."""
    password = get_settings().seed_password
    if not password:
        raise SystemExit("LCOMFINE_SEED_PASSWORD 미설정 — 시드 계정을 만들 수 없다. `make setup` 으로 `.env` 를 만들거나 "
                         "환경변수로 준다. 기본 비밀번호는 두지 않는다(G-19).")
    for login_id, role_name, role_code in USERS:
        name = example(role_name)
        cur = conn.q1("select password_hash from sys_user where login_id = %s", (login_id,))
        if cur is not None and auth.verify_password(password, cur["password_hash"]):
            conn.x("""update sys_user set role_code = %s, user_name = %s, status = '정상', fail_count = 0,
                             updated_at = now(), updated_by = %s
                       where login_id = %s""",
                   (role_code, name, SEEDED_BY, login_id))
            continue
        conn.x("""insert into sys_user (login_id, user_name, password_hash, role_code, created_by)
                  values (%s, %s, %s, %s, %s)
                  on conflict (login_id) do update
                     set password_hash = excluded.password_hash, role_code = excluded.role_code,
                         user_name = excluded.user_name, status = '정상', fail_count = 0,
                         updated_at = now(), updated_by = excluded.created_by""",
               (login_id, name, auth.hash_password(password), role_code, SEEDED_BY))


def run_dev_seeds() -> list[str]:
    """개발 1·2·3 의 시드를 순서대로 돌린다. 파일이 아직 없으면 건너뛰고 한 줄 남긴다. 있는데 실패하면 그대로 실패한다."""
    ran: list[str] = []
    here = Path(__file__).resolve().parent
    for name in DEV_SEEDS:
        if not (here / f"{name}.py").exists():
            print(f"개발 시드 {name} — 파일 없음, 건너뜀")
            continue
        mod = importlib.import_module(f"lcomfine.db.{name}")
        rc = mod.main()
        if rc:
            raise SystemExit(f"{name} 실패 (종료코드 {rc})")
        ran.append(name)
    return ran


LOG_TABLES = frozenset({"sys_access_log", "sys_change_log"})


def table_counts() -> dict[str, int]:
    """public 스키마의 테이블별 행 수 — 시드 멱등(G-21) 대조용. 접근 · 변경 로그는 시드와 무관하게 늘므로 뺀다."""
    names = [r["table_name"] for r in conn.q(
        """select table_name from information_schema.tables
            where table_schema = 'public' and table_type = 'BASE TABLE' order by table_name""")]
    return {n: conn.q1(f'select count(*) as n from "{n}"')["n"] for n in names if n not in LOG_TABLES}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    seed_roles()
    seed_permissions()
    seed_users()
    seed_number_rules()
    seed_common_codes()
    ran = [] if "--common-only" in argv else run_dev_seeds()
    c = table_counts()
    levels = {r["level"]: r["n"] for r in conn.q("select level, count(*) as n from sys_permission group by level")}
    print(f"공통 시드 — 부서 {c['sys_role']} · 권한 {c['sys_permission']}칸(W {levels.get('W', 0)} · R {levels.get('R', 0)})"
          f" · 계정 {c['sys_user']} · 채번 {c['sys_number_rule']} · 공통코드 {c['sys_common_code']}")
    print(f"개발 시드 — {', '.join(ran) if ran else '없음'}")
    print("행 수 — " + " · ".join(f"{k} {v}" for k, v in c.items() if v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
