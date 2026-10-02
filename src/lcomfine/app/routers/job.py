"""job 라우터 — 작업지시 관리 (기능 7) · 담당 개발1.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D2. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("JOB-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  JOB-01 작업지시 → /job/orders
      F-JOB-01 작업지시 등록 [등록] POST /job/orders
      F-JOB-02 작업지시 수정 [수정] POST /job/orders/{job_no}
      F-JOB-03 작업지시 취소 [삭제] POST /job/orders/{job_no}/cancel
      F-JOB-04 작업지시 조회 [조회] GET /job/orders
      F-JOB-05 작업지시서 출력 [출력] GET /job/orders/{job_no}/print
  JOB-02 Job-Lot-Roll 매핑 → /job/mapping
      F-JOB-06 Job-Lot-Roll 매핑 등록 [등록] POST /job/mapping
      F-JOB-07 Job-Lot-Roll 매핑 조회 [조회] GET /job/mapping
"""

from fastapi import APIRouter

router = APIRouter()
