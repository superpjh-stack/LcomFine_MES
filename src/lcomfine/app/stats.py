"""집계 — 실적 현황(생산 · 품질 · 납기)과 불량 유형별 집계의 SQL 을 두는 **한 곳** (G-10).

담당 **개발3**. 산식은 `contracts/interfaces.md` §7 · decisions.md D-25 그대로이고, 문장이 비워 둔 곳의 해석은
D-301 · D-302 에 적었다. QA2 가 같은 문장으로 SQL 을 따로 짜서 대조한다 — 산식을 바꾸려면 계약부터 고친다.

**어떤 테이블에도 쓰지 않는다**(P10 · G-05). 이 파일의 SQL 은 전부 `select` 다. 집계 결과를 캐시 테이블에 쌓지 않는다.
현황판(F-STA-04)과 집계 화면(F-STA-01~03)은 같은 함수를 부른다 — 같은 값을 두 번 계산하는 SQL 을 두지 않는다.
행이 없으면 빈 리스트를 돌려준다(화면이 `미수집` 을 보여 준다). 분모가 0 인 비율은 `None` 이다(0 으로 지어내지 않는다).

해석 (D-301)
  · "날짜가 기간 안" = `timestamptz::date` 가 `date_from` 이상 `date_to` 이하 (양 끝 포함). 날짜는 DB 세션 시간대 기준이다.
  · 합(`output_qty` · `scrap_qty`)은 더할 값이 하나도 없으면 0 이다(합의 항이 0개). 평균(`avg_delta_e`)은 값이 없으면 None.
  · 비율은 파이썬 float (`fail_count / inspection_count`). 반올림하지 않는다 — 화면이 표시할 때만 자른다.
  · `delivery` 의 "오늘" 은 인자 `today`(기본 = 실행한 날). 같은 기간이라도 날이 지나면 `pending` 이 `late` 로 넘어간다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..db import conn
from .util import http

#: 품목 조건 — `item_id` 가 None 이면 전체. 품목은 `job.item_id` (D-25)
_ITEM_FILTER = "(%(item_id)s::bigint is null or j.item_id = %(item_id)s::bigint)"

_PRODUCTION_SQL = f"""
select i.item_id, i.item_code, i.item_name,
       count(*)::int                 as work_count,
       coalesce(sum(w.output_qty), 0) as output_qty,
       coalesce(sum(s.scrap_qty), 0)  as scrap_qty
  from work_result w
  join job j on j.job_id = w.job_id
  join item i on i.item_id = j.item_id
  left join (select work_result_id, sum(scrap_qty) as scrap_qty
               from work_scrap group by work_result_id) s on s.work_result_id = w.work_result_id
 where w.status = '완료'
   and w.ended_at::date between %(date_from)s and %(date_to)s
   and {_ITEM_FILTER}
 group by i.item_id, i.item_code, i.item_name
 order by i.item_code
"""

_QUALITY_SQL = f"""
select i.item_id, i.item_code, i.item_name,
       count(*)::int                                    as inspection_count,
       count(*) filter (where n.result = '불합격')::int as fail_count,
       avg(n.delta_e)                                   as avg_delta_e,
       count(n.delta_e)::int                            as delta_e_count
  from inspection n
  join job j on j.job_id = n.job_id
  join item i on i.item_id = j.item_id
 where n.inspected_at::date between %(date_from)s and %(date_to)s
   and {_ITEM_FILTER}
 group by i.item_id, i.item_code, i.item_name
 order by i.item_code
"""

# 납기 판정 — 그 Job 의 **승인된** 출하 가운데 가장 이른 ship_date 를 본다 (interfaces.md §7)
_DELIVERY_SQL = f"""
with first_ship as (
    select job_id, min(ship_date) as first_ship_date
      from shipment
     where status = '승인'
     group by job_id
)
select i.item_id, i.item_code, i.item_name,
       count(*)::int as job_count,
       count(*) filter (where f.first_ship_date <= j.due_date)::int as on_time,
       count(*) filter (where f.first_ship_date > j.due_date
                           or (f.first_ship_date is null and j.due_date < %(today)s))::int as late,
       count(*) filter (where f.first_ship_date is null and j.due_date >= %(today)s)::int as pending
  from job j
  join item i on i.item_id = j.item_id
  left join first_ship f on f.job_id = j.job_id
 where j.due_date between %(date_from)s and %(date_to)s
   and j.status <> '취소'
   and {_ITEM_FILTER}
 group by i.item_id, i.item_code, i.item_name
 order by i.item_code
"""

_DEFECT_BY_TYPE_SQL = f"""
select d.defect_code_id, d.defect_code, d.defect_name,
       count(*)::int                  as defect_count,
       count(distinct n.roll_id)::int as roll_count
  from inspection_defect x
  join inspection n on n.inspection_id = x.inspection_id
  join defect_code d on d.defect_code_id = x.defect_code_id
  join job j on j.job_id = n.job_id
 where n.inspected_at::date between %(date_from)s and %(date_to)s
   and {_ITEM_FILTER}
 group by d.defect_code_id, d.defect_code, d.defect_name
 order by count(*) desc, d.defect_code
"""

# 불량 유형별 집계의 내역 — 집계와 **같은 조건**(기간 · 품목)으로 불량 행을 낱낱이 편다. 행 수 = defect_count 의 합
_DEFECT_ROLLS_SQL = f"""
select x.inspection_defect_id, d.defect_code, d.defect_name, x.position, x.note,
       r.roll_no, r.process_type, j.job_no, i.item_code, i.item_name,
       n.inspection_id, n.result, n.delta_e, n.inspected_at
  from inspection_defect x
  join inspection n on n.inspection_id = x.inspection_id
  join defect_code d on d.defect_code_id = x.defect_code_id
  join roll r on r.roll_id = n.roll_id
  join job j on j.job_id = n.job_id
  join item i on i.item_id = j.item_id
 where n.inspected_at::date between %(date_from)s and %(date_to)s
   and {_ITEM_FILTER}
   and (%(defect_code)s::text is null or d.defect_code = %(defect_code)s::text)
 order by n.inspected_at desc, x.inspection_defect_id
"""


# ── 조건(기간 · 품목) — 집계 화면들이 같은 규칙으로 읽는다 ────────────────
def parse_date(text: str | None, name: str = "날짜") -> date | None:
    """`YYYY-MM-DD` 글자 → date. 비어 있으면 None, 형식이 틀리면 422."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise http.validation_error("날짜는 YYYY-MM-DD 로 입력해 주세요", fields=[{"name": name, "reason": text}]) from None


def period(date_from: str | None, date_to: str | None, *, today: date | None = None) -> tuple[date, date]:
    """집계 화면의 기간. 비워 두면 **이번 달 1일 ~ 오늘**(화면의 기본 조회 범위, D-302). 시작이 끝보다 늦으면 422."""
    day = today or date.today()
    d1 = parse_date(date_from, "기간 시작") or day.replace(day=1)
    d2 = parse_date(date_to, "기간 끝") or max(day, d1)
    if d1 > d2:
        raise http.validation_error("기간의 시작이 끝보다 늦습니다", fields=[{"name": "기간", "reason": f"{d1} ~ {d2}"}])
    return d1, d2


def parse_item(item_id: str | None) -> int | None:
    """품목 조건(`item_id`). 비어 있으면 None(전체). 숫자가 아니거나 없는 품목이면 422."""
    text = (item_id or "").strip()
    if not text:
        return None
    if not text.isdigit() or conn.q1("select 1 from item where item_id = %s", (int(text),)) is None:
        raise http.validation_error("없는 품목입니다", fields=[{"name": "품목", "reason": text}])
    return int(text)


def item_options() -> list[tuple[int, str]]:
    """품목 선택칸 — 제품이거나 Job 이 가리키는 품목. (item_id, `코드 이름`)."""
    return [(r["item_id"], f"{r['item_code']} {r['item_name']}") for r in conn.q(
        """select i.item_id, i.item_code, i.item_name from item i
            where i.item_type = '제품' or exists (select 1 from job j where j.item_id = i.item_id)
            order by i.item_code""")]


def _params(date_from: date, date_to: date, item_id: int | None) -> dict:
    return {"date_from": date_from, "date_to": date_to, "item_id": item_id}


def rate(numerator: int, denominator: int) -> float | None:
    """비율. 분모가 0 이면 None — 0 으로 지어내지 않는다."""
    return numerator / denominator if denominator else None


def production(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """생산 집계 (D2·D5) — 품목별 {item_id, item_code, item_name, work_count, output_qty, scrap_qty}.

    대상: `work_result` 중 `status='완료'` 이고 `ended_at` 의 날짜가 기간 안. `scrap_qty` 는 그 실적들의 폐기 수량 합.
    """
    return conn.q(_PRODUCTION_SQL, _params(date_from, date_to, item_id))


def quality(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """품질 집계 (D2·D7) — 품목별 {item_id, item_code, item_name, inspection_count, fail_count, fail_rate, avg_delta_e}.

    대상: `inspection` 중 `inspected_at` 의 날짜가 기간 안. 검사 **행** 수다(롤마다 최신 검사만 세지 않는다).
    `delta_e_count`(ΔE 가 적힌 검사 수)는 `totals` 가 전체 평균을 낼 때 쓰는 덧붙인 열이다.
    """
    rows = conn.q(_QUALITY_SQL, _params(date_from, date_to, item_id))
    for r in rows:
        r["fail_rate"] = rate(r["fail_count"], r["inspection_count"])
    return rows


def delivery(date_from: date, date_to: date, item_id: int | None = None, *, today: date | None = None) -> list[dict]:
    """납기 집계 (D2·D8) — 품목별 {item_id, item_code, item_name, job_count, on_time, late, pending, on_time_rate}.

    대상: `job` 중 `due_date` 가 기간 안이고 `status<>'취소'`. 판정은 그 Job 의 승인된 출하 중 가장 이른 `ship_date`.
    on_time: 그 날짜 ≤ 납기 · late: 그 날짜 > 납기, 또는 승인된 출하가 없고 납기 < 오늘 · pending: 승인된 출하가 없고 납기 ≥ 오늘.
    `today` 는 "오늘" 을 고정해 다시 계산할 때 준다(기본 = 실행한 날).
    """
    params = _params(date_from, date_to, item_id)
    params["today"] = today or date.today()
    rows = conn.q(_DELIVERY_SQL, params)
    for r in rows:
        r["on_time_rate"] = rate(r["on_time"], r["on_time"] + r["late"])
    return rows


def defect_by_type(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """불량 유형별 집계 (D7) — 불량코드별 {defect_code, defect_name, defect_count, roll_count}. F-QUA-05 가 쓴다.

    대상: `inspection_defect` — 그 검사의 `inspected_at` 날짜가 기간 안. `roll_count` 는 서로 다른 롤 수.
    """
    return conn.q(_DEFECT_BY_TYPE_SQL, _params(date_from, date_to, item_id))


def defect_rolls(date_from: date, date_to: date, defect_code: str | None = None, item_id: int | None = None) -> list[dict]:
    """불량 롤 내역 (D7) — 집계와 같은 조건의 불량 행마다 {defect_code, defect_name, position, roll_no, job_no, …}. F-QUA-06 이 쓴다.

    `defect_code` 를 주면 그 불량 유형만. 행 수는 `defect_by_type` 의 `defect_count` 합과 같다.
    """
    params = _params(date_from, date_to, item_id)
    params["defect_code"] = defect_code or None
    return conn.q(_DEFECT_ROLLS_SQL, params)


def totals(kind: str, rows: list[dict]) -> dict | None:
    """품목별 행을 한 줄로 더한다(화면의 합계 줄 · 현황판의 큰 숫자). 행이 없으면 None → 화면은 `미수집`.

    SQL 을 다시 돌리지 않고 위 함수가 준 행만 더한다. 비율은 더한 값으로 다시 나눈다(비율의 평균이 아니다).
    """
    if not rows:
        return None
    if kind == "production":
        return {"work_count": sum(r["work_count"] for r in rows),
                "output_qty": sum((r["output_qty"] for r in rows), Decimal(0)),
                "scrap_qty": sum((r["scrap_qty"] for r in rows), Decimal(0))}
    if kind == "quality":
        count = sum(r["inspection_count"] for r in rows)
        fail = sum(r["fail_count"] for r in rows)
        measured = sum(r["delta_e_count"] for r in rows)
        weighted = sum((r["avg_delta_e"] * r["delta_e_count"] for r in rows if r["delta_e_count"]), Decimal(0))
        return {"inspection_count": count, "fail_count": fail, "fail_rate": rate(fail, count),
                "avg_delta_e": weighted / measured if measured else None}
    if kind == "delivery":
        on_time, late = sum(r["on_time"] for r in rows), sum(r["late"] for r in rows)
        return {"job_count": sum(r["job_count"] for r in rows), "on_time": on_time, "late": late,
                "pending": sum(r["pending"] for r in rows), "on_time_rate": rate(on_time, on_time + late)}
    raise ValueError(f"집계 종류가 아니다: {kind!r} — production · quality · delivery")


def board(today: date | None = None) -> dict:
    """현황판 — 오늘의 {production, quality, delivery} 요약. 위 세 함수를 그대로 부른다 (기간 = 오늘 하루, D-302).

    `totals` 는 그 행들을 더한 한 줄씩이다(행이 없으면 None). 납기는 **오늘이 납기인** Job 이다.
    """
    day = today or date.today()
    out = {
        "today": day,
        "production": production(day, day),
        "quality": quality(day, day),
        "delivery": delivery(day, day, today=day),
    }
    out["totals"] = {k: totals(k, out[k]) for k in ("production", "quality", "delivery")}
    return out
