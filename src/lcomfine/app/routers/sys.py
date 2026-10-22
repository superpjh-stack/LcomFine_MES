"""SYS 시스템 — 사용자 관리(SYS-010) · 역할·권한(SYS-020) · 공통코드(SYS-030) · 로그(SYS-040). 담당 개발1.

- 사용자의 부서·상태는 요청마다 DB 에서 읽는다(rbac.current_user) — 상태를 바꾸면 다음 요청부터 401(트리거가 세션 판을 올린다),
  부서를 바꾸면 다음 요청부터 그 부서의 권한. 퇴사자는 지우지 않고 중지(비활성)로 둔다.
- 권한 칸은 DB 데이터(`sys_permission`)다. 저장하면 `rbac.invalidate()`. 시드를 다시 돌리면 `contracts/permission-matrix.md` 로 되돌아간다.
- 로그 화면은 `sys_access_log` · `sys_change_log` · `erp_upload_batch` 를 읽기만 한다(쓰기 0).
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import auth, contracts, nav, rbac, templating
from ..util import audit, http
from .bas import bad, choice, day, edit_row, integer, like, need, pk, ref_id, s, yn

router = APIRouter()

USER_STATUSES = ("정상", "잠금", "중지")
INACTIVE = "중지"


# ── SYS-010 사용자 관리 ─────────────────────────────────────────────────
def _role(code: str | None) -> str:
    c = need(code, "부서")
    if rbac.role(c) is None:
        raise bad("부서", f"역할 {len(rbac.roles())} 중 하나여야 합니다 ({c})")
    return c


@router.get(nav.path_of("SYS-010"), response_class=HTMLResponse)
def users(request: Request, q: str | None = None, role: str | None = None, status: str | None = None,
          edit: str | None = None, user: rbac.User = rbac.require_screen("SYS-010")):
    """F-SYS-014 — 사용자 목록 (비밀번호 해시는 내보내지 않는다)."""
    rows = conn.q(
        """select u.user_id, u.login_id, u.user_name, u.role_code, r.role_name, u.status, u.fail_count, u.last_login_at,
                  u.created_at, u.updated_at, u.updated_by
             from sys_user u join sys_role r on r.role_code = u.role_code
            where (%(q)s::text is null or u.login_id ilike %(q)s or u.user_name ilike %(q)s)
              and (%(r)s::text is null or u.role_code = %(r)s)
              and (%(st)s::text is null or u.status = %(st)s)
            order by r.sort_no, u.login_id limit 1000""",
        {"q": like(q), "r": s(role, "부서"), "st": choice(status, "상태", USER_STATUSES, required=False)})
    ed = None
    if edit:
        ed = conn.q1("select user_id, login_id, user_name, role_code, status from sys_user where user_id = %s",
                     (pk(edit),))
        if ed is None:
            raise http.not_found()
    return templating.render(request, "sys/users.html",
                             {"rows": rows, "edit": ed, "roles": rbac.roles(), "statuses": USER_STATUSES,
                              "form": {"q": q or "", "role": role or "", "status": status or ""}},
                             screen_id="SYS-010")


@router.post("/sys/users")
def user_create(request: Request, login_id: str | None = Form(None), user_name: str | None = Form(None),
                role_code: str | None = Form(None), password: str | None = Form(None),
                user: rbac.User = rbac.require_fn("F-SYS-011")):
    lid = need(login_id, "사번(로그인 ID)")
    name = need(user_name, "이름")
    rc = _role(role_code)
    if not password:
        raise bad("비밀번호", "필수 항목입니다", "필수 항목을 입력해 주세요 — 비밀번호")
    with conn.tx() as cur:
        cur.execute("select 1 from sys_user where login_id = %s", (lid,))
        if cur.fetchone():
            raise bad("사번(로그인 ID)", lid, "이미 있는 사번입니다")
        cur.execute("""insert into sys_user (login_id, user_name, password_hash, role_code, created_by)
                       values (%s, %s, %s, %s, %s) returning user_id""",
                    (lid, name, auth.hash_password(password), rc, user.login_id))
        uid = cur.fetchone()["user_id"]
    resp = http.saved(request, f"사용자를 등록했습니다 ({lid})", back=nav.path_of("SYS-010"), data={"id": uid})
    audit.log_change(request, user, "F-SYS-011", f"sys_user:{lid}", f"사용자 등록 · 부서 {rc}")
    return resp


@router.post("/sys/users/{id}")
def user_update(request: Request, id: str, login_id: str | None = Form(None), user_name: str | None = Form(None),
                role_code: str | None = Form(None), status: str | None = Form(None),
                password: str | None = Form(None), user: rbac.User = rbac.require_fn("F-SYS-012")):
    uid = pk(id)
    name = need(user_name, "이름")
    rc = _role(role_code)
    st = choice(status, "상태", USER_STATUSES)
    with conn.tx() as cur:
        cur.execute("select user_id, login_id, role_code, status from sys_user where user_id = %s for update", (uid,))
        row = cur.fetchone()
        if row is None:
            raise http.not_found()
        if s(login_id, "사번(로그인 ID)") is not None and s(login_id, "사번(로그인 ID)") != row["login_id"]:
            raise bad("사번(로그인 ID)", "사번은 바꾸지 않습니다", "사번은 바꿀 수 없습니다")
        if row["login_id"] == user.login_id and (st != "정상" or rc != row["role_code"]):
            raise bad("상태", "자기 계정의 부서·상태는 바꿀 수 없습니다 — 다른 관리자가 바꾼다")
        cur.execute("""update sys_user set user_name = %s, role_code = %s, status = %s, updated_at = now(),
                              updated_by = %s where user_id = %s""", (name, rc, st, user.login_id, uid))
        if password:
            cur.execute("update sys_user set password_hash = %s where user_id = %s", (auth.hash_password(password), uid))
    changes = [f"부서 {row['role_code']} → {rc}"] if rc != row["role_code"] else []
    changes += [f"상태 {row['status']} → {st}"] if st != row["status"] else []
    changes += ["비밀번호 초기화"] if password else []
    resp = http.saved(request, f"사용자를 수정했습니다 ({row['login_id']})", back=nav.path_of("SYS-010"), data={"id": uid})
    audit.log_change(request, user, "F-SYS-012", f"sys_user:{row['login_id']}",
                     "사용자 수정" + (" · " + " · ".join(changes) if changes else ""))
    return resp


@router.post("/sys/users/{id}/delete")
def user_deactivate(request: Request, id: str, user: rbac.User = rbac.require_fn("F-SYS-013")):
    """퇴사자는 삭제하지 않고 비활성(중지)으로 둔다 — 다음 요청부터 401 · SSO 토큰도 발급되지 않는다."""
    uid = pk(id)
    with conn.tx() as cur:
        cur.execute("select login_id, status from sys_user where user_id = %s for update", (uid,))
        row = cur.fetchone()
        if row is None:
            raise http.not_found()
        if row["login_id"] == user.login_id:
            raise bad("사용자", "자기 계정은 비활성으로 바꿀 수 없습니다")
        cur.execute("update sys_user set status = %s, updated_at = now(), updated_by = %s where user_id = %s",
                    (INACTIVE, user.login_id, uid))
    resp = http.saved(request, f"사용자를 비활성(중지)으로 바꿨습니다 ({row['login_id']})", back=nav.path_of("SYS-010"),
                      data={"id": uid, "status": INACTIVE})
    audit.log_change(request, user, "F-SYS-013", f"sys_user:{row['login_id']}", f"사용자 비활성 · {row['status']} → 중지")
    return resp


# ── SYS-020 역할·권한 ───────────────────────────────────────────────────
ADMIN_ROLE = "ADM"          # 전산 관리자 — 전 화면 R 이상(goal.md §6) · 이 화면 W 를 잃으면 아무도 권한을 고칠 수 없다
CELL_PREFIX = "cell:"       # 폼 칸 이름 `cell:<부서 코드>:<화면 ID>` = W | R | ''(없음)
ROLE_NAME_PREFIX = "role_name:"


@router.get(nav.path_of("SYS-020"), response_class=HTMLResponse)
def roles(request: Request, user: rbac.User = rbac.require_screen("SYS-020")):
    """F-SYS-022 — 역할 목록 · 메뉴 × 역할 처리(W)·조회(R). 기본값은 contracts/permission-matrix.md."""
    rs = rbac.roles()
    default = {(sid, rc): lv for sid, rc, lv in contracts.permission_cells()}
    matrix = []
    for row in rbac.matrix():
        sid = row["screen"].screen_id
        matrix.append({"screen": row["screen"],
                       "cells": [{"role": r.code, "level": lv, "default": default.get((sid, r.code)),
                                  "changed": lv != default.get((sid, r.code))} for r, lv in zip(rs, row["cells"])]})
    users_per_role = {r["role_code"]: r["n"] for r in
                      conn.q("select role_code, count(*) as n from sys_user where status = '정상' group by role_code")}
    return templating.render(request, "sys/roles.html",
                             {"roles": rs, "matrix": matrix, "counts": rbac.counts(), "users_per_role": users_per_role,
                              "changed": sum(c["changed"] for m in matrix for c in m["cells"])},
                             screen_id="SYS-020")


@router.post("/sys/roles")
async def roles_save(request: Request, user: rbac.User = rbac.require_fn("F-SYS-021")):
    """칸 값 W · R · 없음 — 보낸 칸만 바꾼다. 저장하면 rbac.invalidate() · 다음 요청부터 반영."""
    form = await request.form()
    codes = {r.code for r in rbac.roles()}
    screens = {sc.screen_id for sc in nav.SCREENS}
    cells: dict[tuple[str, str], str | None] = {}
    names: dict[str, str] = {}
    for key, raw in form.multi_items():
        val = str(raw).strip()
        if key.startswith(CELL_PREFIX):
            parts = key[len(CELL_PREFIX):].split(":")
            if len(parts) != 2 or parts[0] not in codes or parts[1] not in screens:
                raise bad("권한 칸", f"없는 부서·화면입니다 ({key})")
            if val not in ("W", "R", ""):
                raise bad("권한 칸", f"W · R · 없음 중 하나여야 합니다 ({parts[0]} · {parts[1]})")
            cells[(parts[0], parts[1])] = val or None
        elif key.startswith(ROLE_NAME_PREFIX):
            rc = key[len(ROLE_NAME_PREFIX):]
            if rc not in codes:
                raise bad("역할 이름", f"없는 부서입니다 ({rc})")
            names[rc] = need(val, f"역할 이름 ({rc})")
    if not cells and not names:
        raise bad("권한 칸", "필수 항목입니다", "필수 항목을 입력해 주세요 — 바꿀 권한 칸")
    lost = [sid for (rc, sid), lv in cells.items() if rc == ADMIN_ROLE and lv is None]
    if lost:
        raise bad("권한 칸", f"전산 관리자는 전 화면 R 이상이어야 합니다 ({', '.join(lost[:5])})")
    if cells.get((ADMIN_ROLE, "SYS-020"), "W") != "W":
        raise bad("권한 칸", "전산 관리자의 역할·권한(SYS-020) 칸은 W 여야 합니다 — 아니면 아무도 권한을 고칠 수 없다")
    changed = 0
    with conn.tx() as cur:
        for rc, nm in names.items():
            cur.execute("select 1 from sys_role where role_name = %s and role_code <> %s", (nm, rc))
            if cur.fetchone():
                raise bad("역할 이름", f"이미 있는 역할 이름입니다 ({nm})")
            cur.execute("update sys_role set role_name = %s, updated_at = now(), updated_by = %s "
                        "where role_code = %s and role_name <> %s", (nm, user.login_id, rc, nm))
            changed += cur.rowcount
        for (rc, sid), lv in cells.items():
            if lv is None:
                cur.execute("delete from sys_permission where role_code = %s and screen_id = %s", (rc, sid))
            else:
                cur.execute("""insert into sys_permission (role_code, screen_id, level, updated_at, updated_by)
                               values (%s, %s, %s, now(), %s)
                               on conflict (role_code, screen_id) do update
                                  set level = excluded.level, updated_at = now(), updated_by = excluded.updated_by
                                where sys_permission.level <> excluded.level""", (rc, sid, lv, user.login_id))
            changed += cur.rowcount
    rbac.invalidate()
    resp = http.saved(request, f"역할·권한을 저장했습니다 (바뀐 칸 {changed})", back=nav.path_of("SYS-020"),
                      data={"changed": changed})
    audit.log_change(request, user, "F-SYS-021", "sys_permission", f"권한 칸 {len(cells)} 보냄 · 바뀜 {changed}")
    return resp


# ── SYS-030 공통코드 ────────────────────────────────────────────────────
CODE_GROUPS = ("설비", "불량유형", "수금수단")      # 정본 「설비·불량유형·수금수단 코드를 여기서 관리한다」

#: 그룹 → 그 코드를 글자로 담는 곳 (FK 가 아니라 코드 값이라 카탈로그로 찾지 못한다)
_CODE_REFS: dict[str, tuple[tuple[str, str], ...]] = {
    "설비": (("work_order", "equipment_code = %s"), ("production_daily", "equipment_code = %s"),
             ("work_sequence", "equipment_code = %s")),
    "불량유형": (("inspection_daily", "defects ? %s"),),
    "수금수단": (("erp_upload_row", "parsed->>'method' = %s"),),
}


def _code_refs(cur, group: str, code: str) -> list[str]:
    hits = []
    for table, cond in _CODE_REFS.get(group, ()):
        cur.execute(f"select 1 from {table} where {cond} limit 1", (code,))
        if cur.fetchone():
            hits.append(table)
    return hits


@router.get(nav.path_of("SYS-030"), response_class=HTMLResponse)
def codes(request: Request, group: str | None = None, edit: str | None = None,
          user: rbac.User = rbac.require_screen("SYS-030")):
    """F-SYS-032 — 코드 그룹 · 코드 값."""
    rows = conn.q("""select id, group_code, code, code_name, sort_no, note, use_yn from sys_common_code
                      where (%(g)s::text is null or group_code = %(g)s)
                      order by array_position(%(groups)s::text[], group_code), sort_no, code""",
                  {"g": choice(group, "코드 그룹", CODE_GROUPS, required=False), "groups": list(CODE_GROUPS)})
    return templating.render(request, "sys/codes.html",
                             {"rows": rows, "groups": CODE_GROUPS, "edit": edit_row("sys_common_code", edit),
                              "form": {"group": group or ""}}, screen_id="SYS-030")


@router.post("/sys/codes")
def code_save(request: Request, id: str | None = Form(None), action: str | None = Form(None),
              group_code: str | None = Form(None), code: str | None = Form(None), code_name: str | None = Form(None),
              sort_no: str | None = Form(None), note: str | None = Form(None), use_yn: str | None = Form(None),
              user: rbac.User = rbac.require_fn("F-SYS-031")):
    """저장 한 기능 — `id` 가 없으면 등록, 있으면 수정, `action=delete` 면 삭제(참조가 있으면 사용 중지)."""
    act = choice(action or "save", "동작", ("save", "delete"))
    cid = ref_id(id, "공통코드", required=False)
    with conn.tx() as cur:
        if cid is not None:
            cur.execute("select id, group_code, code from sys_common_code where id = %s for update", (cid,))
            row = cur.fetchone()
            if row is None:
                raise http.not_found()
        elif act == "delete":
            raise bad("공통코드", "필수 항목입니다", "지울 공통코드를 고르세요")
        if act == "delete":
            refs = _code_refs(cur, row["group_code"], row["code"])
            if refs:
                cur.execute("update sys_common_code set use_yn = 'N', updated_at = now(), updated_by = %s where id = %s",
                            (user.login_id, cid))
                done = "사용 중지"
            else:
                cur.execute("delete from sys_common_code where id = %s", (cid,))
                done = "삭제"
            target, msg = f"sys_common_code:{row['group_code']}/{row['code']}", (
                "참조가 있어 지우지 않고 사용 중지로 바꿨습니다" if refs else "공통코드를 삭제했습니다")
            data = {"id": cid, "result": done}
        else:
            name = need(code_name, "코드 이름")
            order = integer(sort_no, "표시 순서", minimum=0) or 0
            use = yn(use_yn)
            if cid is None:
                grp = choice(group_code, "코드 그룹", CODE_GROUPS)
                cd = need(code, "코드 값")
                cur.execute("select 1 from sys_common_code where group_code = %s and code = %s", (grp, cd))
                if cur.fetchone():
                    raise bad("코드 값", cd, f"그 그룹에 이미 있는 코드입니다 ({grp} · {cd})")
                cur.execute("""insert into sys_common_code (group_code, code, code_name, sort_no, note, use_yn, created_by)
                               values (%s, %s, %s, %s, %s, %s, %s) returning id""",
                            (grp, cd, name, order, s(note, "비고"), use, user.login_id))
                cid = cur.fetchone()["id"]
                target, msg, data = f"sys_common_code:{grp}/{cd}", "공통코드를 등록했습니다", {"id": cid, "result": "등록"}
            else:
                if (s(group_code, "코드 그룹") and s(group_code, "코드 그룹") != row["group_code"]) or (s(code, "코드 값") and s(code, "코드 값") != row["code"]):
                    raise bad("코드 값", "그룹·코드 값은 바꾸지 않습니다", "코드 그룹·값은 바꿀 수 없습니다")
                cur.execute("""update sys_common_code set code_name = %s, sort_no = %s, note = %s, use_yn = %s,
                                      updated_at = now(), updated_by = %s where id = %s""",
                            (name, order, s(note, "비고"), use, user.login_id, cid))
                target, msg, data = (f"sys_common_code:{row['group_code']}/{row['code']}", "공통코드를 수정했습니다",
                                     {"id": cid, "result": "수정"})
    resp = http.saved(request, msg, back=nav.path_of("SYS-030"), data=data)
    audit.log_change(request, user, "F-SYS-031", target, msg)
    return resp


# ── SYS-040 로그 ────────────────────────────────────────────────────────
#: 탭 = 정본 L3 「접속 로그 · 변경 감사 로그 · 업로드·AI 호출 로그」 를 표 단위로 펼친 것(D-609). 전부 읽기만 — 쓰기 0.
LOG_TABS = ("access", "change", "erp", "sso")   # AI 호출 · 데이터 질의 탭은 D-529 로 없앴다
LOG_LIMIT = 500

#: 탭마다 (원본 표, 보이는 컬럼 — db-schema.md 의 컬럼 이름 그대로). 템플릿이 표 밑에 적는다.
LOG_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "access": ("sys_access_log", ("logged_at", "log_type", "login_id", "role_code", "method", "path", "screen_id",
                                  "function_id", "target", "result", "detail", "client_ip")),
    "change": ("sys_change_log", ("changed_at", "login_id", "role_code", "function_id", "screen_id", "target", "detail",
                                  "path", "client_ip")),
    "erp": ("erp_upload_batch", ("batch_no", "period_from", "period_to", "round_no", "status", "replaced_by", "source_file",
                                 "row_count", "error_count", "uploaded_at", "created_by")),
    "sso": ("sys_access_log (log_type = 'SSO')", ("logged_at", "login_id", "role_code", "result", "path", "target",
                                                  "detail", "client_ip")),
}
ACCESS_LOG_TYPES = ("로그인", "조회", "변경", "오류", "SSO")      # db-schema.md §6 `sys_access_log.log_type` 값 집합


@router.get(nav.path_of("SYS-040"), response_class=HTMLResponse)
def logs(request: Request, tab: str | None = None, login: str | None = None, log_type: str | None = None,
         date_from: str | None = None, date_to: str | None = None, user: rbac.User = rbac.require_screen("SYS-040")):
    """F-SYS-041 — 접속 · 변경 감사 · ERP 업로드 회차 · SSO. 읽기만 한다(최근 500행).

    기간(`date_from` · `date_to`) · 사용자(`login`) 는 모든 탭에 같은 방식. `log_type` 은 탭마다 구분 열 하나
    (접속 구분 · 기능 ID · 회차 상태 · 성공/실패). 머리 수치는 **같은 필터**로 센다.
    """
    t = choice(tab or "access", "탭", LOG_TABS)
    params = {"login": like(login), "from": day(date_from, "시작일", required=False),
              "to": day(date_to, "끝일", required=False), "type": s(log_type, "구분"), "limit": LOG_LIMIT}
    summary = None
    if t == "access":
        # 구분은 db-schema 의 값 집합 밖이면 422 (DEF-QA1-008 · D-609 「선택지 밖은 422」)
        params["type"] = choice(log_type, "구분", ACCESS_LOG_TYPES, required=False)
        rows = conn.q("""select logged_at as at, log_type, login_id, role_code, method, path, screen_id, function_id,
                                target, result, detail, client_ip
                           from sys_access_log
                          where (%(login)s::text is null or login_id ilike %(login)s)
                            and (%(type)s::text is null or log_type = %(type)s)
                            and (%(from)s::date is null or logged_at >= %(from)s)
                            and (%(to)s::date is null or logged_at < %(to)s::date + 1)
                          order by log_id desc limit %(limit)s""", params)
    elif t == "change":
        # 구분 = 기능 ID — 계약(function-list.md)에 없는 ID 는 422 (값 집합 = contracts.functions())
        if params["type"] is not None and params["type"] not in {fn.id for fn in contracts.functions()}:
            raise bad("기능 ID", f"계약(function-list.md)에 있는 기능 ID 여야 합니다 ({params['type']})")
        rows = conn.q("""select changed_at as at, login_id, role_code, function_id, screen_id, method, path, target, detail,
                                client_ip
                           from sys_change_log
                          where (%(login)s::text is null or login_id ilike %(login)s)
                            and (%(type)s::text is null or function_id = %(type)s)
                            and (%(from)s::date is null or changed_at >= %(from)s)
                            and (%(to)s::date is null or changed_at < %(to)s::date + 1)
                          order by id desc limit %(limit)s""", params)
    elif t == "erp":
        # W2 가 쌓은 회차(개발3 · COL-010) — 교체는 `replaced_by` 의 회차 번호로 보인다. 올린 사람 = created_by.
        params["type"] = choice(log_type, "회차 상태", ("반영", "교체"), required=False)
        where = """where (%(login)s::text is null or b.created_by ilike %(login)s)
                     and (%(type)s::text is null or b.status = %(type)s)
                     and (%(from)s::date is null or b.uploaded_at >= %(from)s)
                     and (%(to)s::date is null or b.uploaded_at < %(to)s::date + 1)"""
        rows = conn.q(f"""select b.uploaded_at as at, b.batch_no, b.period_from, b.period_to, b.round_no, b.status,
                                 n.batch_no as replaced_by, b.source_file, b.row_count, b.error_count, b.created_by
                            from erp_upload_batch b left join erp_upload_batch n on n.id = b.replaced_by
                          {where} order by b.id desc limit %(limit)s""", params)
        summary = conn.q1(f"""select count(*) as n, count(*) filter (where b.status = '반영') as live,
                                     count(*) filter (where b.status = '교체') as replaced,
                                     coalesce(sum(b.row_count), 0) as rows_total, coalesce(sum(b.error_count), 0) as errors
                                from erp_upload_batch b {where}""", params)
    else:
        # SSO — F-DOC-011(W4) 이 구분 SSO 로 남기는 행(D-514). 아직 없으면 표가 「미수집」.
        params["type"] = choice(log_type, "결과", ("성공", "실패"), required=False)
        where = """where log_type = 'SSO'
                     and (%(login)s::text is null or login_id ilike %(login)s)
                     and (%(type)s::text is null or result = %(type)s)
                     and (%(from)s::date is null or logged_at >= %(from)s)
                     and (%(to)s::date is null or logged_at < %(to)s::date + 1)"""
        rows = conn.q(f"""select logged_at as at, login_id, role_code, result, path, target, detail, client_ip
                            from sys_access_log {where} order by log_id desc limit %(limit)s""", params)
        summary = conn.q1(f"""select count(*) as n, count(*) filter (where result = '실패') as failed
                                from sys_access_log {where}""", params)
    return templating.render(request, "sys/logs.html",
                             {"tab": t, "rows": rows, "summary": summary, "limit": LOG_LIMIT, "source": LOG_SOURCES[t],
                              "form": {"login": login or "", "log_type": log_type or "", "date_from": date_from or "",
                                       "date_to": date_to or ""}}, screen_id="SYS-040")
