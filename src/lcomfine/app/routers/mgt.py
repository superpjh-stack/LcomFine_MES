"""MGT 경영관리 — 목표·경보기준·위험조치·재무자료."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import financial, management, nav, rbac, templating
from ..util import audit, http
from .bas import bad, choice, day, exists_or_404, need, pk, s

router = APIRouter()
PERIODS = ("연간", "월간", "주간")
SCOPES = ("company", "department", "customer", "item", "equipment", "warehouse")
LEVELS = ("주의", "위험")
OPS = ("gt", "gte", "lt", "lte", "outside")
ACTION_STATES = ("대기", "진행", "완료", "취소")
GLOBAL_ISSUE_ROLES = ("ST", "EX", "ADM")


def number(v: str | None, label: str, *, required: bool = True) -> Decimal | None:
    raw = s(v, label)
    if raw is None:
        if required:
            raise bad(label, "필수 항목입니다")
        return None
    try:
        out = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        raise bad(label, "숫자여야 합니다") from None
    if not out.is_finite() or abs(out) >= Decimal("1e14") or out.as_tuple().exponent < -4:
        raise bad(label, "정수 14자리 · 소수 4자리까지 입력할 수 있습니다")
    return out


def scope_values(kind: str | None, key: str | None) -> tuple[str, str | None]:
    k = choice(kind, "적용 범위", SCOPES)
    value = s(key, "범위 값")
    if k == "company":
        if value is not None:
            raise bad("범위 값", "전사 범위에는 입력하지 않습니다")
        return k, None
    if value is None:
        raise bad("범위 값", "전사 외 범위에는 필수입니다")
    return k, value


def dates(period_from, period_to):
    start, end = day(period_from, "시작일"), day(period_to, "종료일")
    if start > end:
        raise bad("기간", "시작일은 종료일보다 늦을 수 없습니다")
    return start, end


def metric(cur, key: str | None) -> dict:
    value = need(key, "지표")
    cur.execute("select * from management_metric where metric_key=%s and use_yn='Y'", (value,))
    row = cur.fetchone()
    if row is None:
        raise bad("지표", "사용 중인 지표가 아닙니다")
    return row


def overlap(cur, table: str, metric_key, start, end, scope_kind, scope_key, *, level=None, exclude=None):
    extra, args = "", [metric_key, end, start, scope_kind, scope_key]
    if level is not None:
        extra += " and level=%s"
        args.append(level)
    if exclude is not None:
        extra += " and id<>%s"
        args.append(exclude)
    cur.execute(f"""select id from {table} where metric_key=%s and status='사용'
                    and period_from <= %s and period_to >= %s and scope_kind=%s
                    and scope_key is not distinct from %s {extra} limit 1""", tuple(args))
    if cur.fetchone():
        raise bad("기간", "같은 지표·범위에 겹치는 사용 기간이 있습니다", "겹치는 활성 기준이 있습니다")


@router.get("/mgt/targets", response_class=HTMLResponse)
def target_list(request: Request, user: rbac.User = rbac.require_screen("MGT-010")):
    rows = conn.q("""select t.*,m.metric_name,m.unit,m.direction,v.version_no,v.target_value,v.range_min,v.range_max,v.change_reason
                     from management_target t join management_metric m using(metric_key)
                     join lateral (select * from management_target_version where target_id=t.id order by version_no desc limit 1) v on true
                     order by t.period_from desc,t.id desc""")
    return templating.render(request, "mgt/targets.html", {"rows": rows, "metrics": conn.q("select * from management_metric where use_yn='Y' order by metric_name")}, screen_id="MGT-010")


@router.post("/mgt/targets")
def target_create(request: Request, metric_key: str | None = Form(None), period_kind: str | None = Form(None),
                  period_from: str | None = Form(None), period_to: str | None = Form(None),
                  scope_kind: str | None = Form(None), scope_key: str | None = Form(None),
                  target_value: str | None = Form(None), range_min: str | None = Form(None),
                  range_max: str | None = Form(None), change_reason: str | None = Form(None),
                  user: rbac.User = rbac.require_fn("F-MGT-011")):
    start, end = dates(period_from, period_to)
    scope_type, scope_value = scope_values(scope_kind, scope_key)
    payload = {"target_value": number(target_value, "목표값"), "range_min": number(range_min, "정상 하한", required=False),
               "range_max": number(range_max, "정상 상한", required=False), "change_reason": need(change_reason, "변경 사유")}
    if (payload["range_min"] is None) != (payload["range_max"] is None) or (payload["range_min"] is not None and payload["range_min"] > payload["range_max"]):
        raise bad("정상 범위", "하한과 상한을 함께 입력하고 하한은 상한 이하여야 합니다")
    with conn.tx() as cur:
        m = metric(cur, metric_key)
        kind = choice(period_kind, "기간 구분", PERIODS)
        overlap(cur, "management_target", m["metric_key"], start, end, scope_type, scope_value)
        cur.execute("""insert into management_target(metric_key,period_kind,period_from,period_to,scope_kind,scope_key,created_by)
                       values (%s,%s,%s,%s,%s,%s,%s) returning id""",
                    (m["metric_key"], kind, start, end, scope_type, scope_value, user.login_id))
        target_id = cur.fetchone()["id"]
        management.create_target_version(cur, target_id, payload, user)
    resp = http.saved(request, "경영목표를 등록했습니다", back="/mgt/targets", data={"id": target_id})
    audit.log_change(request, user, "F-MGT-011", f"management_target:{scope_value or 'company'}:{target_id}", "경영목표 등록")
    return resp


@router.post("/mgt/targets/{id}")
def target_version(request: Request, id: str, target_value: str | None = Form(None), range_min: str | None = Form(None),
                   range_max: str | None = Form(None), change_reason: str | None = Form(None),
                   user: rbac.User = rbac.require_fn("F-MGT-012")):
    target_id = pk(id)
    payload = {"target_value": number(target_value, "목표값"), "range_min": number(range_min, "정상 하한", required=False),
               "range_max": number(range_max, "정상 상한", required=False), "change_reason": need(change_reason, "변경 사유")}
    if (payload["range_min"] is None) != (payload["range_max"] is None) or (payload["range_min"] is not None and payload["range_min"] > payload["range_max"]):
        raise bad("정상 범위", "하한과 상한을 함께 입력하고 하한은 상한 이하여야 합니다")
    with conn.tx() as cur:
        row = exists_or_404(cur, "management_target", target_id, "id,scope_key")
        management.create_target_version(cur, target_id, payload, user)
    resp = http.saved(request, "목표 새 버전을 저장했습니다", back="/mgt/targets", data={"id": target_id})
    audit.log_change(request, user, "F-MGT-012", f"management_target:{row['scope_key'] or 'company'}:{target_id}", "목표 새 버전")
    return resp


@router.post("/mgt/targets/{id}/delete")
def target_stop(request: Request, id: str, user: rbac.User = rbac.require_fn("F-MGT-013")):
    target_id = pk(id)
    with conn.tx() as cur:
        row = exists_or_404(cur, "management_target", target_id, "id,scope_key")
        cur.execute("update management_target set status='중지',updated_at=now(),updated_by=%s where id=%s", (user.login_id,target_id))
    resp = http.saved(request, "경영목표를 중지했습니다", back="/mgt/targets", data={"id": target_id})
    audit.log_change(request, user, "F-MGT-013", f"management_target:{row['scope_key'] or 'company'}:{target_id}", "경영목표 중지")
    return resp


@router.get("/mgt/thresholds", response_class=HTMLResponse)
def threshold_list(request: Request, user: rbac.User = rbac.require_screen("MGT-020")):
    rows = conn.q("select t.*,m.metric_name,m.unit from management_threshold t join management_metric m using(metric_key) order by period_from desc,t.id desc")
    return templating.render(request, "mgt/thresholds.html", {"rows": rows, "metrics": conn.q("select * from management_metric where use_yn='Y' order by metric_name")}, screen_id="MGT-020")


def threshold_values(metric_key, level, compare_op, value_min, value_max, period_from, period_to, scope_kind, scope_key):
    start, end = dates(period_from, period_to)
    sk, sv = scope_values(scope_kind, scope_key)
    op = choice(compare_op, "비교 방식", OPS)
    low, high = number(value_min, "기준값"), number(value_max, "상한", required=False)
    if op == "outside" and high is None:
        raise bad("상한", "범위 밖 비교에는 필수입니다")
    if op == "outside" and low > high:
        raise bad("경보 범위", "하한은 상한 이하여야 합니다")
    return {"metric_key": metric_key, "level": choice(level, "경보 단계", LEVELS), "compare_op": op,
            "value_min": low, "value_max": high, "period_from": start, "period_to": end,
            "scope_kind": sk, "scope_key": sv}


@router.post("/mgt/thresholds")
def threshold_create(request: Request, metric_key: str | None = Form(None), level: str | None = Form(None), compare_op: str | None = Form(None),
                     value_min: str | None = Form(None), value_max: str | None = Form(None), period_from: str | None = Form(None),
                     period_to: str | None = Form(None), scope_kind: str | None = Form(None), scope_key: str | None = Form(None),
                     user: rbac.User = rbac.require_fn("F-MGT-021")):
    v = threshold_values(metric_key, level, compare_op, value_min, value_max, period_from, period_to, scope_kind, scope_key)
    with conn.tx() as cur:
        m = metric(cur, v["metric_key"]); v["metric_key"] = m["metric_key"]
        overlap(cur, "management_threshold", m["metric_key"], v["period_from"], v["period_to"], v["scope_kind"], v["scope_key"], level=v["level"])
        cur.execute("""insert into management_threshold(metric_key,level,compare_op,value_min,value_max,period_from,period_to,scope_kind,scope_key,created_by)
                       values (%(metric_key)s,%(level)s,%(compare_op)s,%(value_min)s,%(value_max)s,%(period_from)s,%(period_to)s,%(scope_kind)s,%(scope_key)s,%(created_by)s) returning id""", {**v,"created_by":user.login_id})
        row_id = cur.fetchone()["id"]
    resp = http.saved(request, "경보기준을 등록했습니다", back="/mgt/thresholds", data={"id":row_id})
    audit.log_change(request,user,"F-MGT-021",f"management_threshold:{v['scope_key'] or 'company'}:{row_id}","경보기준 등록")
    return resp


@router.post("/mgt/thresholds/{id}")
def threshold_update(request: Request, id: str, metric_key: str | None = Form(None), level: str | None = Form(None), compare_op: str | None = Form(None),
                     value_min: str | None = Form(None), value_max: str | None = Form(None), period_from: str | None = Form(None),
                     period_to: str | None = Form(None), scope_kind: str | None = Form(None), scope_key: str | None = Form(None),
                     user: rbac.User = rbac.require_fn("F-MGT-022")):
    row_id = pk(id); v = threshold_values(metric_key,level,compare_op,value_min,value_max,period_from,period_to,scope_kind,scope_key)
    with conn.tx() as cur:
        exists_or_404(cur,"management_threshold",row_id,"id")
        m=metric(cur,v["metric_key"]); v["metric_key"]=m["metric_key"]
        overlap(cur,"management_threshold",m["metric_key"],v["period_from"],v["period_to"],v["scope_kind"],v["scope_key"],level=v["level"],exclude=row_id)
        cur.execute("""update management_threshold set metric_key=%(metric_key)s,level=%(level)s,compare_op=%(compare_op)s,value_min=%(value_min)s,value_max=%(value_max)s,
                       period_from=%(period_from)s,period_to=%(period_to)s,scope_kind=%(scope_kind)s,scope_key=%(scope_key)s,updated_at=now(),updated_by=%(updated_by)s where id=%(id)s""", {**v,"updated_by":user.login_id,"id":row_id})
    resp=http.saved(request,"경보기준을 수정했습니다",back="/mgt/thresholds",data={"id":row_id})
    audit.log_change(request,user,"F-MGT-022",f"management_threshold:{v['scope_key'] or 'company'}:{row_id}","경보기준 수정")
    return resp


@router.post("/mgt/thresholds/{id}/delete")
def threshold_stop(request: Request,id: str,user: rbac.User=rbac.require_fn("F-MGT-023")):
    row_id=pk(id)
    with conn.tx() as cur:
        row=exists_or_404(cur,"management_threshold",row_id,"id,scope_key")
        cur.execute("update management_threshold set status='중지',updated_at=now(),updated_by=%s where id=%s",(user.login_id,row_id))
    resp=http.saved(request,"경보기준을 중지했습니다",back="/mgt/thresholds",data={"id":row_id})
    audit.log_change(request,user,"F-MGT-023",f"management_threshold:{row['scope_key'] or 'company'}:{row_id}","경보기준 중지")
    return resp


@router.get("/mgt/issues", response_class=HTMLResponse)
def issue_list(request: Request, user: rbac.User=rbac.require_screen("MGT-030")):
    args = () if user.role_code in GLOBAL_ISSUE_ROLES else (user.role_code,user.role_code)
    where = "" if not args else "where i.owner_role=%s or exists(select 1 from management_action a where a.issue_id=i.id and a.owner_role=%s)"
    rows=conn.q(f"""select i.*,m.metric_name from management_issue i left join management_metric m using(metric_key)
                   {where} order by case i.status when '신규' then 1 when '진행' then 2 else 3 end,i.last_seen_at desc""",args)
    ids=[r["id"] for r in rows]
    actions=conn.q("select a.*,u.user_name from management_action a left join sys_user u on u.user_id=a.owner_user_id where a.issue_id=any(%s) order by a.due_date,a.id",(ids or [0],))
    by_issue={i:[] for i in ids}
    for a in actions: by_issue[a["issue_id"]].append(a)
    return templating.render(request,"mgt/issues.html",{"rows":rows,"actions":by_issue,"roles":rbac.roles()},screen_id="MGT-030")


def _can_assign(user, owner_role):
    if user.role_code not in ("ST","ADM") and owner_role != user.role_code:
        raise http.forbidden("담당 범위 밖 부서에 조치를 배정할 수 없습니다")


@router.post("/mgt/issues/{id}/actions")
def action_create(request: Request,id: str,owner_role: str|None=Form(None),owner_user_id: str|None=Form(None),
                  due_date: str|None=Form(None),action_text: str|None=Form(None),
                  user: rbac.User=rbac.require_fn("F-MGT-031")):
    issue_id=pk(id); role=need(owner_role,"담당 부서"); _can_assign(user,role)
    due=day(due_date,"기한"); text=need(action_text,"조치 내용")
    uid=None
    if s(owner_user_id,"담당자"):
        if not str(owner_user_id).isdigit(): raise bad("담당자","목록에서 고른 값이 아닙니다")
        uid=int(owner_user_id)
    with conn.tx() as cur:
        cur.execute("select role_code from sys_role where role_code=%s and use_yn='Y'",(role,))
        if cur.fetchone() is None: raise bad("담당 부서","없는 부서입니다")
        if uid is not None:
            cur.execute("select 1 from sys_user where user_id=%s and role_code=%s and status='정상'",(uid,role))
            if cur.fetchone() is None: raise bad("담당자","담당 부서의 정상 사용자가 아닙니다")
        try: action_id=management.assign_action(cur,issue_id,{"owner_role":role,"owner_user_id":uid,"due_date":due,"action_text":text},user)
        except LookupError: raise http.not_found() from None
        cur.execute("update management_issue set status='진행',updated_at=now(),updated_by=%s where id=%s and status='신규'",(user.login_id,issue_id))
    resp=http.saved(request,"조치를 배정했습니다",back="/mgt/issues",data={"id":action_id})
    audit.log_change(request,user,"F-MGT-031",f"management_action:{action_id}",f"조치 배정 · {role}")
    return resp


@router.post("/mgt/issues/actions/{id}")
def action_update(request: Request,id: str,status: str|None=Form(None),user: rbac.User=rbac.require_fn("F-MGT-032")):
    action_id=pk(id); state=choice(status,"상태",ACTION_STATES)
    with conn.tx() as cur:
        cur.execute("select owner_role from management_action where id=%s",(action_id,)); row=cur.fetchone()
        if row is None: raise http.not_found()
        if user.role_code not in ("ST","ADM") and row["owner_role"] != user.role_code:
            raise http.forbidden("담당 부서는 자기 조치만 변경할 수 있습니다")
        management.transition_action(cur,action_id,state,user)
    resp=http.saved(request,"조치 상태를 변경했습니다",back="/mgt/issues",data={"id":action_id})
    audit.log_change(request,user,"F-MGT-032",f"management_action:{action_id}",f"조치 상태 · {state}")
    return resp


@router.post("/mgt/issues/{id}/delete")
def issue_close(request: Request,id: str,close_reason: str|None=Form(None),user: rbac.User=rbac.require_fn("F-MGT-033")):
    issue_id=pk(id); reason=need(close_reason,"강제 종료 사유")
    with conn.tx() as cur:
        row=exists_or_404(cur,"management_issue",issue_id,"id,owner_role")
        if user.role_code not in ("ST","ADM") and row["owner_role"] not in (None,user.role_code):
            raise http.forbidden("담당 범위 밖 위험을 종료할 수 없습니다")
        cur.execute("update management_issue set status='해결',resolved_at=now(),close_reason=%s,updated_at=now(),updated_by=%s where id=%s",(reason,user.login_id,issue_id))
    resp=http.saved(request,"위험을 해결 처리했습니다",back="/mgt/issues",data={"id":issue_id})
    audit.log_change(request,user,"F-MGT-033",f"management_issue:{issue_id}",f"강제 종료 · {reason}")
    return resp


@router.get("/mgt/financial-imports",response_class=HTMLResponse)
def financial_list(request:Request,user:rbac.User=rbac.require_screen("MGT-040")):
    rows=conn.q("select * from financial_import_batch order by created_at desc,id desc limit 100")
    return templating.render(request,"mgt/financial_imports.html",{"rows":rows},screen_id="MGT-040")


@router.post("/mgt/financial-imports")
async def financial_upload(request:Request,period_from:str|None=Form(None),period_to:str|None=Form(None),
                           file:UploadFile=File(...),user:rbac.User=rbac.require_fn("F-MGT-041")):
    start,end=dates(period_from,period_to)
    content=await file.read()
    try:
        with conn.tx() as cur:
            parsed=financial.parse(content,cur)
            batch_id=financial.stage(cur,start,end,parsed,user,s(file.filename,"파일명") or "upload.xlsx")
    except financial.UploadError as exc:
        raise bad(exc.field,exc.reason,exc.message) from None
    resp=http.saved(request,"재무자료를 검증했습니다",back="/mgt/financial-imports",data={"id":batch_id,"rows":len(parsed["rows"]),"errors":sum(1 for r in parsed["rows"] if r["error"])})
    audit.log_change(request,user,"F-MGT-041",f"financial_import_batch:{batch_id}","재무자료 검증 업로드")
    return resp


@router.post("/mgt/financial-imports/{id}")
def financial_apply(request:Request,id:str,user:rbac.User=rbac.require_fn("F-MGT-042")):
    batch_id=pk(id)
    with conn.tx() as cur:
        try: old=financial.apply(cur,batch_id,user)
        except LookupError: raise http.not_found() from None
        except ValueError as exc: raise bad("회차",str(exc)) from None
    resp=http.saved(request,"재무자료 회차를 반영했습니다",back="/mgt/financial-imports",data={"id":batch_id,"replaced":old})
    audit.log_change(request,user,"F-MGT-042",f"financial_import_batch:{batch_id}",f"재무자료 반영 · 이전 {old or '없음'}")
    return resp
