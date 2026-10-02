"""pop 라우터 — 생산 실적 (POP) (기능 8) · 담당 개발2.

쓰는 저장소: D5(`work_result` `work_stop` `work_scrap`) · D6(인쇄 롤 — `lineage.make_print_roll` 로만). 이 밖의 테이블에는 쓰지 않는다(G-05).
`job` 행은 건드리지 않는다(D2 는 P2 만 쓴다). POP 의 시작·종료·정지는 **사람이 누르는 기록**이다 — 설비에서 받는 값은 없다.

  POP-01 작업 실적 → /pop/work
      F-POP-01 작업 시작 [등록] POST /pop/work/start
      F-POP-02 작업 종료 [등록] POST /pop/work/{work_id}/finish
      F-POP-03 작업 실적 조회 [조회] GET /pop/work
  POP-02 정지 · 폐기 → /pop/stops
      F-POP-04 정지 등록 [등록] POST /pop/stops
      F-POP-05 재개 등록 [수정] POST /pop/stops/{stop_id}/resume
      F-POP-06 폐기 등록 [등록] POST /pop/stops/scrap
      F-POP-07 정지·폐기 조회 [조회] GET /pop/stops
  POP-03 롤 라벨 → /pop/roll-labels
      F-POP-08 인쇄 롤 라벨 출력 [출력] GET /pop/roll-labels/{roll_no}/print

이 파일 앞쪽의 「현장 화면 공용 도우미」는 개발2 의 다른 라우터(mat · clr · rll)도 가져다 쓴다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ...db import conn
from .. import lineage, nav, printing, rbac, templating
from ..util import audit, http

router = APIRouter()

LIST_LIMIT = 300        # 목록 상한 — 화면이 한 쪽씩 넘긴다(app.js)

# ── 현장 화면 공용 도우미 (mat · clr · rll 도 쓴다) ─────────────────────
def bad(message: str, name: str, reason: str) -> Exception:
    """422 — 항목 하나의 사유."""
    return http.validation_error(message, fields=[{"name": name, "reason": reason}])


def text_of(value: str | None, label: str, *, required: bool = False, max_len: int = 500) -> str | None:
    v = (value or "").strip()
    if not v:
        if required:
            raise bad(f"{label}을(를) 입력해 주세요", label, "필수값")
        return None
    if len(v) > max_len:
        raise bad(f"{label}이(가) 너무 깁니다", label, f"{max_len}자 이하")
    return v


#: 숫자 컬럼이 담는 범위 — `contracts/db-schema.md` §4 (정수부 자릿수 = numeric(p,s) 의 p−s, 소수 자릿수 = s)
QTY = (11, 3)           # numeric(14,3) — 입고 수량 · 투입량 · 실적 수량 · 폐기 수량 · 길이 (m)
WIDTH = (8, 2)          # numeric(10,2) — 폭 (mm)
LAB = (5, 2)            # numeric(7,2)  — 색상값 L · a · b
RATIO = (3, 3)          # numeric(6,3)  — 배합비 (%)
INT4_MAX = 2_147_483_647                 # integer — 차수 · 분할 순번
INT8_MAX = 9_223_372_036_854_775_807     # bigint  — 내부 키 (작업 실적 · 조색 기록)


def decimal_of(value: str | None, label: str, *, required: bool = False, positive: bool = False,
               non_negative: bool = False, digits: tuple[int, int] = QTY) -> Decimal | None:
    """숫자 입력칸 → Decimal. `digits` = (정수부 자릿수, 소수 자릿수) — 그 컬럼이 담지 못하는 값은 422 (어느 칸인지 알린다).

    DB 는 소수 자릿수를 넘는 값을 반올림해 담는다 — 범위와 부호는 그 **담기는 값**으로 판정하고, 반올림이 일어나면 담기는 값을 돌려준다.
    """
    v = (value or "").strip().replace(",", "")
    if not v:
        if required:
            raise bad(f"{label}을(를) 입력해 주세요", label, "필수값")
        return None
    try:
        d = Decimal(v)
    except InvalidOperation:
        raise bad(f"{label}은(는) 숫자여야 합니다", label, v) from None
    if not d.is_finite():
        raise bad(f"{label}은(는) 숫자여야 합니다", label, v)
    int_digits, scale = digits
    too_big = bad(f"{label}이(가) 너무 큽니다", label, f"정수부 {int_digits}자리 · 소수 {scale}자리까지 — 입력 {v[:40]}")
    if d and d.adjusted() >= int_digits:                       # |d| ≥ 10^정수부 자릿수
        raise too_big
    stored = d.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP) if d and d.adjusted() >= -scale - 1 else Decimal(0)
    if abs(stored) >= Decimal(10) ** int_digits:               # 반올림으로 자릿수가 넘어가는 값 (예: 99999999999.9995)
        raise too_big
    if positive and stored <= 0:
        raise bad(f"{label}은(는) 0 보다 커야 합니다", label, v[:40])
    if non_negative and d < 0:
        raise bad(f"{label}은(는) 0 이상이어야 합니다", label, v[:40])
    return d if d == stored else stored


def int_of(value: str | None, label: str, *, required: bool = False, minimum: int | None = None,
           maximum: int = INT4_MAX) -> int | None:
    """정수 입력칸 → int. `maximum` 을 넘으면 422 — 기본은 `integer` 컬럼의 상한, 내부 키(bigint)는 `INT8_MAX`."""
    v = (value or "").strip()
    if not v:
        if required:
            raise bad(f"{label}을(를) 입력해 주세요", label, "필수값")
        return None
    try:
        n = int(v)
    except ValueError:
        raise bad(f"{label}은(는) 정수여야 합니다", label, v[:40]) from None
    if minimum is not None and n < minimum:
        raise bad(f"{label}은(는) {minimum} 이상이어야 합니다", label, v[:40])
    if abs(n) > maximum:
        raise bad(f"{label}이(가) 너무 큽니다", label, f"{maximum} 이하 — 입력 {v[:40]}")
    return n


def date_of(value: str | None, label: str) -> date | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise bad(f"{label}은(는) 날짜(YYYY-MM-DD)여야 합니다", label, v) from None


def path_id(raw: str) -> int:
    """경로에 박힌 내부 키 — 숫자가 아니면 그런 대상은 없다(404)."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise http.not_found() from None


def equipment_options() -> list[tuple[str, str]]:
    return [(r["equipment_code"], f"{r['equipment_name']} [{r['equipment_code']}]") for r in conn.q(
        "select equipment_code, equipment_name from equipment where use_yn = 'Y' order by equipment_code")]


def equipment_of(code: str | None) -> dict | None:
    """설비 코드(선택) → 설비 행. 비어 있으면 None, 없는 코드는 422."""
    code = (code or "").strip()
    if not code:
        return None
    row = conn.q1("select equipment_id, equipment_code, equipment_name, process_id from equipment where equipment_code = %s",
                  (code,))
    if row is None:
        raise bad("없는 설비 코드입니다", "설비", code)
    return row


def back_to(request: Request, url: str) -> str:
    """쓰기 뒤 돌아갈 주소 — 스캔하던 화면이 `?device=pop` 으로 열려 있었으면(채널 훅 D-19) 그 채널을 물려준다."""
    device = parse_qs(urlparse(request.headers.get("referer") or "").query).get("device", [""])[0]
    if device not in nav.DEVICE_CHANNEL or device == "web" or "device=" in url:
        return url
    path, sep, anchor = url.partition("#")
    return f"{path}{'&' if '?' in path else '?'}device={device}{sep}{anchor}"


def scan_failure(request: Request, exc: Exception) -> dict:
    """GET 스캔 진입(`?no=`)에서 번호를 못 찾았을 때 — JSON 은 422 를 그대로 올리고, 브라우저는 **같은 화면**을
    422 로 다시 그려 큰 글씨로 알린다(스캔칸이 그대로 있어 다음 스캔을 막지 않는다, D-201). 돌려주는 값은 화면에 넘길 오류."""
    if not http.wants_html(request):
        raise exc
    detail = getattr(exc, "detail", None) or {}
    return {"message": detail.get("message", ""), "fields": detail.get("fields") or []}


def label_page(request: Request, labels: list, *, screen_id: str, back: str, title: str) -> HTMLResponse:
    """라벨 인쇄용 화면 — 라벨 조각(`printing.render_label`)을 늘어놓고 브라우저 인쇄 버튼을 둔다(D-04)."""
    return templating.render(request, "pop/label_print.html",
                             {"labels": [printing.render_label(x) for x in labels], "back": back, "title": title},
                             screen_id=screen_id)


# ── 조회용 SQL ──────────────────────────────────────────────────────────
_WORK_SELECT = """
select w.work_result_id, w.status, w.started_at, w.ended_at, w.output_qty, w.qty_unit, w.worker, w.note,
       j.job_no, j.status as job_status, i.item_name, jl.lot_no as job_lot_no,
       e.equipment_code, e.equipment_name, r.roll_no,
       (select count(*) from material_input mi where mi.work_result_id = w.work_result_id) as input_count,
       (select s.work_stop_id from work_stop s where s.work_result_id = w.work_result_id and s.resumed_at is null) as open_stop_id
  from work_result w
  join job j on j.job_id = w.job_id
  join item i on i.item_id = j.item_id
  left join job_lot jl on jl.job_lot_id = w.job_lot_id
  left join equipment e on e.equipment_id = w.equipment_id
  left join roll r on r.work_result_id = w.work_result_id
"""


def open_works() -> list[dict]:
    """끝나지 않은 작업 실적(진행·정지) — 자재 투입·정지·폐기 화면이 고르는 목록."""
    return conn.q(_WORK_SELECT + " where w.status <> '완료' order by w.started_at desc, w.work_result_id desc")


def work_of(work_id: int) -> dict | None:
    return conn.q1(_WORK_SELECT + " where w.work_result_id = %s", (work_id,))


def find_job(job_no: str) -> dict | None:
    """Job 번호(스캔값) → Job. 앞뒤 공백은 떼고 소문자로 들어온 값은 대문자로도 찾는다. 없으면 None."""
    job_no = (job_no or "").strip()
    if not job_no:
        return None
    return conn.q1(
        """select j.job_id, j.job_no, j.status, j.order_qty, j.qty_unit, j.due_date, j.equipment_id,
                  i.item_code, i.item_name, c.customer_name, e.equipment_code
             from job j join item i on i.item_id = j.item_id join customer c on c.customer_id = j.customer_id
             left join equipment e on e.equipment_id = j.equipment_id
            where j.job_no = any(%s) order by (j.job_no = %s) desc limit 1""",
        (sorted({job_no, job_no.upper()}), job_no))


def job_of(job_no: str | None) -> dict:
    """사용자가 입력·스캔한 Job 번호 → Job. 비었거나 없으면 422."""
    no = text_of(job_no, "Job 번호", required=True)
    job = find_job(no)
    if job is None:
        raise bad("없는 Job 번호입니다", "Job 번호", no)
    return job


JOB_OPEN = "등록"       # job.status — 작업을 시작할 수 있는 Job (취소·완료 Job 은 422, D-202)


def closed_job(status: str, job_no: str) -> Exception:
    """422 — `등록` 이 아닌(취소·완료) Job 에는 작업을 시작하지 못한다."""
    return bad(f"{status} 상태의 Job 은 작업을 시작할 수 없습니다", job_no, f"상태 {status}")


def assert_job_open(cur, job_id: int, job_no: str) -> None:
    """실적을 넣는 **그 트랜잭션 안에서** Job 행을 `for share` 로 잠그고 상태를 다시 본다(DEF-QA2-004 · D-211).

    바깥에서 읽은 상태는 화면에 보일 문장을 고르는 데만 쓴다 — 그 읽기와 실적 INSERT 사이에 취소·마감이 끝날 수 있다.
    취소·마감(`routers/job.py` 의 `lock_job`)은 같은 행을 `for update` 로 잠그므로 둘 중 하나만 통과한다:
    여기가 먼저 잠그면 취소·마감은 이 커밋을 기다렸다가 실적을 세어 422, 취소·마감이 먼저면 여기가 기다렸다가 바뀐 상태를 보고 422.
    잠금은 쓰기가 아니다(P5 는 D2 에 쓰지 않는다 — G-05). 이 트랜잭션은 이 뒤에 `job` 행을 고치지 않는다(잠금 올리기 없음 — 교착 없음).
    """
    cur.execute("select status from job where job_id = %s for share", (job_id,))
    now = cur.fetchone()
    if now is None:
        raise bad("없는 Job 번호입니다", "Job 번호", job_no)
    if now["status"] != JOB_OPEN:
        raise closed_job(now["status"], job_no)


# ── POP-01 작업 실적 ────────────────────────────────────────────────────
@router.get(nav.path_of("POP-01"), response_class=HTMLResponse)          # F-POP-03 작업 실적 조회
def work_list(request: Request, no: str = "", day: str = "", roll: str = "",
              user: rbac.User = rbac.require_fn("F-POP-03")):
    """진행 중 실적과 그날 완료한 실적. `?no=<Job 번호>` 는 작업지시서 바코드 스캔 진입 — 그 Job 의 시작 칸이 열린다."""
    the_day = date_of(day, "기준일") or date.today()
    scan_error, job, job_lots = None, None, []
    if no.strip():
        job = find_job(no)
        if job is None:
            scan_error = scan_failure(request, bad("없는 Job 번호입니다", "Job 번호", no.strip()))
        else:
            job_lots = conn.q("select lot_no, planned_roll_count from job_lot where job_id = %s order by lot_no",
                              (job["job_id"],))
    rows = conn.q(_WORK_SELECT + """ where w.status <> '완료' or w.ended_at::date = %s
                                     order by (w.status = '완료'), w.started_at desc, w.work_result_id desc limit %s""",
                  (the_day, LIST_LIMIT))
    made = None
    if roll.strip() and conn.q1("select 1 from roll where roll_no = %s", (roll.strip(),)):
        made = printing.render_label(printing.roll_label(roll.strip()))
    return templating.render(
        request, "pop/work.html",
        {"rows": rows, "day": the_day, "job": job, "job_lots": job_lots, "scan_error": scan_error, "no": no.strip(),
         "equipment_options": equipment_options(), "made_label": made, "made_roll": roll.strip() if made else "",
         "can_start": user.can("F-POP-01"), "can_finish": user.can("F-POP-02")},
        screen_id="POP-01", status_code=422 if scan_error else 200)


@router.post(nav.path_of("POP-01") + "/start")                            # F-POP-01 작업 시작
def work_start(request: Request, job_no: str = Form(""), lot_no: str = Form(""), equipment_code: str = Form(""),
               note: str = Form(""), user: rbac.User = rbac.require_fn("F-POP-01")):
    job = job_of(job_no)
    if job["status"] != JOB_OPEN:                                         # 빠른 거절 — 판정은 아래 트랜잭션 안에서 한 번 더 한다
        raise closed_job(job["status"], job["job_no"])
    job_lot_id = None
    lot = text_of(lot_no, "생산 LOT")
    if lot:
        row = conn.q1("select job_lot_id, job_id from job_lot where lot_no = %s", (lot,))
        if row is None:
            raise bad("없는 생산 LOT 번호입니다", "생산 LOT", lot)
        if row["job_id"] != job["job_id"]:
            raise bad("이 Job 의 생산 LOT 이 아닙니다", "생산 LOT", f"{lot} 은 {job['job_no']} 의 LOT 이 아니다")
        job_lot_id = row["job_lot_id"]
    eq = equipment_of(equipment_code)
    equipment_id = eq["equipment_id"] if eq else job["equipment_id"]      # 안 고르면 Job 의 계획 설비
    process_id = eq["process_id"] if eq else None
    if eq is None and equipment_id is not None:
        process_id = conn.q1("select process_id from equipment where equipment_id = %s", (equipment_id,))["process_id"]
    with conn.tx() as cur:
        assert_job_open(cur, job["job_id"], job["job_no"])                # Job 행을 잠그고 상태를 다시 본다 — 취소·마감과 겹쳐도 하나만 통과
        cur.execute(
            """insert into work_result (job_id, job_lot_id, process_id, equipment_id, status, worker, note)
               values (%s, %s, %s, %s, '진행', %s, %s) returning work_result_id""",
            (job["job_id"], job_lot_id, process_id, equipment_id, user.login_id, text_of(note, "비고")))
        work_id = cur.fetchone()["work_result_id"]
    audit.log_change(request, user, "F-POP-01", f"work_result:{work_id}", f"작업 시작 — Job {job['job_no']}")
    return http.saved(request, f"작업을 시작했습니다 — Job {job['job_no']}",
                      back=back_to(request, nav.path_of("POP-01")), data={"work_id": work_id, "job_no": job["job_no"]})


@router.post(nav.path_of("POP-01") + "/{work_id}/finish")                 # F-POP-02 작업 종료
def work_finish(request: Request, work_id: str, output_qty: str = Form(""), qty_unit: str = Form(""),
                length_m: str = Form(""), width_mm: str = Form(""), user: rbac.User = rbac.require_fn("F-POP-02")):
    """실적을 `완료` 로 닫고 인쇄 롤 1개 + 계보 `투입` 행(투입 LOT 마다 한 줄)을 **한 트랜잭션**으로 만든다(D-13)."""
    wid = path_id(work_id)
    qty = decimal_of(output_qty, "실적 수량", required=True, non_negative=True)
    length = decimal_of(length_m, "길이", non_negative=True)
    width = decimal_of(width_mm, "폭", positive=True, digits=WIDTH)
    with conn.tx() as cur:
        cur.execute("select work_result_id, status, job_id from work_result where work_result_id = %s for update", (wid,))
        w = cur.fetchone()                    # 실적 행을 잠근다 — 같은 실적을 동시에 두 번 종료하지 못한다
        if w is None:
            raise http.not_found()
        cur.execute("select qty_unit from job where job_id = %s", (w["job_id"],))
        job_unit = cur.fetchone()["qty_unit"]
        if w["status"] == "완료":
            raise bad("이미 종료한 작업 실적입니다", "작업 실적", f"{wid} — 상태 완료")
        if w["status"] == "정지":
            raise bad("정지 중인 작업은 재개한 뒤 종료합니다", "작업 실적", f"{wid} — 상태 정지")
        roll = lineage.make_print_roll(cur, work_result_id=wid, by=user.login_id, length_m=length, width_mm=width)
        cur.execute("""update work_result
                          set status = '완료', ended_at = now(), output_qty = %s, qty_unit = %s,
                              updated_at = now(), updated_by = %s
                        where work_result_id = %s""",
                    (qty, text_of(qty_unit, "수량 단위") or job_unit, user.login_id, wid))
    roll_no = roll["roll_no"]
    audit.log_change(request, user, "F-POP-02", f"roll:{roll_no}", f"작업 종료 — 실적 {wid} · 인쇄 롤 {roll_no}")
    label_url = f"{nav.path_of('POP-03')}/{roll_no}/print"
    return http.saved(request, f"작업을 종료했습니다 — 인쇄 롤 {roll_no}",
                      back=back_to(request, f"{nav.path_of('POP-01')}?roll={roll_no}"),
                      data={"work_id": wid, "roll_no": roll_no, "label_url": label_url})


# ── POP-02 정지 · 폐기 ──────────────────────────────────────────────────
@router.get(nav.path_of("POP-02"), response_class=HTMLResponse)          # F-POP-07 정지·폐기 조회
def stop_list(request: Request, work_id: str = "", user: rbac.User = rbac.require_fn("F-POP-07")):
    wid = int_of(work_id, "작업 실적", maximum=INT8_MAX)
    where, params = ("where w.work_result_id = %s", (wid,)) if wid is not None else ("", ())
    stops = conn.q(f"""
        select s.work_stop_id, s.work_result_id, s.stop_reason, s.stopped_at, s.resumed_at, s.created_by, j.job_no, w.status
          from work_stop s join work_result w on w.work_result_id = s.work_result_id join job j on j.job_id = w.job_id
          {where} order by (s.resumed_at is null) desc, s.stopped_at desc limit {LIST_LIMIT}""", params)
    scraps = conn.q(f"""
        select c.work_scrap_id, c.work_result_id, c.scrap_qty, c.qty_unit, c.reason, c.scrapped_at, c.created_by,
               j.job_no, d.defect_code, d.defect_name
          from work_scrap c join work_result w on w.work_result_id = c.work_result_id join job j on j.job_id = w.job_id
          left join defect_code d on d.defect_code_id = c.defect_code_id
          {where} order by c.scrapped_at desc limit {LIST_LIMIT}""", params)
    defect_options = [(r["defect_code"], f"{r['defect_name']} [{r['defect_code']}]") for r in conn.q(
        "select defect_code, defect_name from defect_code where use_yn = 'Y' order by defect_code")]
    return templating.render(
        request, "pop/stops.html",
        {"stops": stops, "scraps": scraps, "works": open_works(), "work_id": wid, "defect_options": defect_options,
         "can_stop": user.can("F-POP-04"), "can_resume": user.can("F-POP-05"), "can_scrap": user.can("F-POP-06")},
        screen_id="POP-02")


def _work_for_write(cur, work_id: int, label: str = "작업 실적") -> dict:
    """사용자가 고른 작업 실적 — 없으면 422(입력값). 행을 잠근다."""
    cur.execute("select work_result_id, status, job_id from work_result where work_result_id = %s for update", (work_id,))
    w = cur.fetchone()
    if w is None:
        raise bad("없는 작업 실적입니다", label, str(work_id))
    return w


@router.post(nav.path_of("POP-02"))                                       # F-POP-04 정지 등록
def stop_create(request: Request, work_id: str = Form(""), stop_reason: str = Form(""), stopped_at: str = Form(""),
                user: rbac.User = rbac.require_fn("F-POP-04")):
    wid = int_of(work_id, "작업 실적", required=True, maximum=INT8_MAX)
    reason = text_of(stop_reason, "정지 사유", required=True)
    at = None
    if stopped_at.strip():
        try:
            at = datetime.fromisoformat(stopped_at.strip())
        except ValueError:
            raise bad("정지 시각은 날짜·시각이어야 합니다", "정지 시각", stopped_at) from None
    with conn.tx() as cur:
        w = _work_for_write(cur, wid)
        if w["status"] != "진행":
            raise bad("진행 중인 작업만 정지할 수 있습니다", "작업 실적", f"{wid} — 상태 {w['status']}")
        if at is not None:
            cur.execute("select %s::timestamptz > now() as future", (at,))
            if cur.fetchone()["future"]:
                raise bad("정지 시각이 지금보다 뒤입니다", "정지 시각", stopped_at)
        cur.execute("""insert into work_stop (work_result_id, stop_reason, stopped_at, created_by)
                       values (%s, %s, coalesce(%s::timestamptz, now()), %s) returning work_stop_id""",
                    (wid, reason, at, user.login_id))
        stop_id = cur.fetchone()["work_stop_id"]
        cur.execute("update work_result set status = '정지', updated_at = now(), updated_by = %s where work_result_id = %s",
                    (user.login_id, wid))
    audit.log_change(request, user, "F-POP-04", f"work_stop:{stop_id}", f"정지 — 실적 {wid} · {reason}")
    return http.saved(request, "정지를 기록했습니다", data={"stop_id": stop_id, "work_id": wid})


@router.post(nav.path_of("POP-02") + "/scrap")                            # F-POP-06 폐기 등록
def scrap_create(request: Request, work_id: str = Form(""), scrap_qty: str = Form(""), qty_unit: str = Form(""),
                 defect_code: str = Form(""), reason: str = Form(""), user: rbac.User = rbac.require_fn("F-POP-06")):
    """폐기 수량·사유만 적는다. 롤·계보를 만들지 않는다."""
    wid = int_of(work_id, "작업 실적", required=True, maximum=INT8_MAX)
    qty = decimal_of(scrap_qty, "폐기 수량", required=True, positive=True)
    defect_id = None
    code = text_of(defect_code, "불량코드")
    if code:
        d = conn.q1("select defect_code_id from defect_code where defect_code = %s", (code,))
        if d is None:
            raise bad("없는 불량코드입니다", "불량코드", code)
        defect_id = d["defect_code_id"]
    with conn.tx() as cur:
        _work_for_write(cur, wid)
        cur.execute("""insert into work_scrap (work_result_id, scrap_qty, qty_unit, defect_code_id, reason, created_by)
                       values (%s, %s, %s, %s, %s, %s) returning work_scrap_id""",
                    (wid, qty, text_of(qty_unit, "수량 단위"), defect_id, text_of(reason, "사유"), user.login_id))
        scrap_id = cur.fetchone()["work_scrap_id"]
    audit.log_change(request, user, "F-POP-06", f"work_scrap:{scrap_id}", f"폐기 — 실적 {wid} · 수량 {qty}")
    return http.saved(request, "폐기를 기록했습니다", data={"scrap_id": scrap_id, "work_id": wid})


@router.post(nav.path_of("POP-02") + "/{stop_id}/resume")                 # F-POP-05 재개 등록
def stop_resume(request: Request, stop_id: str, user: rbac.User = rbac.require_fn("F-POP-05")):
    sid = path_id(stop_id)
    with conn.tx() as cur:
        cur.execute("select work_stop_id, work_result_id, resumed_at from work_stop where work_stop_id = %s for update",
                    (sid,))
        s = cur.fetchone()
        if s is None:
            raise http.not_found()
        if s["resumed_at"] is not None:
            raise bad("이미 재개한 정지입니다", "정지", str(sid))
        cur.execute("update work_stop set resumed_at = now() where work_stop_id = %s", (sid,))
        cur.execute("""update work_result set status = '진행', updated_at = now(), updated_by = %s
                        where work_result_id = %s and status = '정지'""", (user.login_id, s["work_result_id"]))
    audit.log_change(request, user, "F-POP-05", f"work_stop:{sid}", f"재개 — 실적 {s['work_result_id']}")
    return http.saved(request, "재개를 기록했습니다", data={"stop_id": sid, "work_id": s["work_result_id"]})


# ── POP-03 롤 라벨 ──────────────────────────────────────────────────────
@router.get(nav.path_of("POP-03"), response_class=HTMLResponse)          # 화면 — 라벨을 뽑을 인쇄 롤 목록
def roll_label_list(request: Request, no: str = "", user: rbac.User = rbac.require_screen("POP-03")):
    scan_error, preview, preview_no = None, None, ""
    if no.strip():
        node = lineage.resolve(no.strip())
        if node is None or node.kind != lineage.ROLL:
            scan_error = scan_failure(request, bad("없는 롤 번호입니다", "롤 번호", no.strip()))
        else:
            preview, preview_no = printing.render_label(printing.roll_label(node.no)), node.no
    rows = conn.q(f"""
        select v.roll_no, v.state, r.length_m, r.width_mm, r.produced_at, r.produced_by, j.job_no, i.item_name
          from v_roll_state v join roll r on r.roll_id = v.roll_id
          join job j on j.job_id = r.job_id join item i on i.item_id = j.item_id
         where v.process_type = '인쇄' order by r.produced_at desc, r.roll_id desc limit {LIST_LIMIT}""")
    return templating.render(
        request, "pop/roll_labels.html",
        {"rows": rows, "scan_error": scan_error, "preview": preview, "preview_no": preview_no, "no": no.strip(),
         "can_print": user.can("F-POP-08")},
        screen_id="POP-03", status_code=422 if scan_error else 200)


@router.get(nav.path_of("POP-03") + "/{roll_no}/print", response_class=HTMLResponse)   # F-POP-08 인쇄 롤 라벨 출력
def roll_label_print(request: Request, roll_no: str, user: rbac.User = rbac.require_fn("F-POP-08")):
    if conn.q1("select 1 from roll where roll_no = %s", (roll_no,)) is None:
        raise http.not_found()
    label = printing.roll_label(roll_no)
    return label_page(request, [label], screen_id="POP-03", back=back_to(request, nav.path_of("POP-03")), title=f"{label.kind} — {roll_no}")
