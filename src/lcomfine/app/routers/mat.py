"""mat 라우터 — 자재 · 입고 (기능 8) · 담당 개발2.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D3 (자재 투입은 D5). 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("MAT-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  MAT-01 입고 → /mat/receipts
      F-MAT-01 입고 등록 [등록] POST /mat/receipts
      F-MAT-02 입고 조회 [조회] GET /mat/receipts
  MAT-02 입고검사 → /mat/inspections
      F-MAT-03 입고검사 결과 등록 [등록] POST /mat/inspections
      F-MAT-04 입고검사 조회 [조회] GET /mat/inspections
  MAT-03 원재료 LOT → /mat/lots
      F-MAT-05 원재료 LOT 조회 [조회] GET /mat/lots
      F-MAT-06 원재료 LOT 라벨 출력 [출력] GET /mat/lots/{lot_no}/label
  MAT-04 자재 투입 → /mat/inputs
      F-MAT-07 자재 투입 스캔 [스캔] POST /mat/inputs
      F-MAT-08 자재 투입 조회 [조회] GET /mat/inputs
"""

from fastapi import APIRouter

router = APIRouter()
