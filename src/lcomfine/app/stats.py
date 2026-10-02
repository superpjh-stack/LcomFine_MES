"""집계 — 실적 현황(생산 · 품질 · 납기)과 불량 유형별 집계의 SQL 을 두는 **한 곳** (G-10).

담당 **개발3**. 아키텍트가 만든 것은 시그니처뿐이다. 산식은 `contracts/interfaces.md` §7 에 적혀 있다 —
QA2 가 그 산식으로 SQL 을 따로 짜서 대조한다. 산식을 바꾸려면 계약부터 고친다.

**어떤 테이블에도 쓰지 않는다**(P10 · G-05). 집계 결과를 캐시 테이블에 쌓지 않는다.
현황판(F-STA-04)과 집계 화면(F-STA-01~03)은 같은 함수를 부른다 — 같은 값을 두 번 계산하는 SQL 을 두지 않는다.
행이 없으면 빈 리스트를 돌려준다(화면이 `미수집` 을 보여 준다). 값을 지어내지 않는다.
"""

from __future__ import annotations

from datetime import date

_TODO = "미구현 — 담당 개발3 (app/stats.py)"


def production(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """생산 집계 (D2·D5) — 품목별 {item_id, item_code, item_name, work_count, output_qty, scrap_qty}."""
    raise NotImplementedError(_TODO)


def quality(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """품질 집계 (D2·D7) — 품목별 {item_id, item_code, item_name, inspection_count, fail_count, fail_rate, avg_delta_e}."""
    raise NotImplementedError(_TODO)


def delivery(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """납기 집계 (D2·D8) — 품목별 {item_id, item_code, item_name, job_count, on_time, late, pending, on_time_rate}."""
    raise NotImplementedError(_TODO)


def defect_by_type(date_from: date, date_to: date, item_id: int | None = None) -> list[dict]:
    """불량 유형별 집계 (D7) — 불량코드별 {defect_code, defect_name, defect_count, roll_count}. F-QUA-05 가 쓴다."""
    raise NotImplementedError(_TODO)


def board(today: date | None = None) -> dict:
    """현황판 — 오늘의 {production, quality, delivery} 요약. 위 세 함수를 그대로 부른다."""
    raise NotImplementedError(_TODO)
