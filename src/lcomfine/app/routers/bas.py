"""bas 라우터 — 기준정보 관리 (기능 20) · 담당 개발1.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D1. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("BAS-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  BAS-01 품목 관리 → /bas/items
      F-BAS-01 품목 등록 [등록] POST /bas/items
      F-BAS-02 품목 수정 [수정] POST /bas/items/{id}
      F-BAS-03 품목 삭제 [삭제] POST /bas/items/{id}/delete
      F-BAS-04 품목 조회 [조회] GET /bas/items
  BAS-02 고객 관리 → /bas/customers
      F-BAS-05 고객 등록 [등록] POST /bas/customers
      F-BAS-06 고객 수정 [수정] POST /bas/customers/{id}
      F-BAS-07 고객 삭제 [삭제] POST /bas/customers/{id}/delete
      F-BAS-08 고객 조회 [조회] GET /bas/customers
  BAS-03 공정 관리 → /bas/processes
      F-BAS-09 공정 등록 [등록] POST /bas/processes
      F-BAS-10 공정 수정 [수정] POST /bas/processes/{id}
      F-BAS-11 공정 삭제 [삭제] POST /bas/processes/{id}/delete
      F-BAS-12 공정 조회 [조회] GET /bas/processes
  BAS-04 설비 관리 → /bas/equipment
      F-BAS-13 설비 등록 [등록] POST /bas/equipment
      F-BAS-14 설비 수정 [수정] POST /bas/equipment/{id}
      F-BAS-15 설비 삭제 [삭제] POST /bas/equipment/{id}/delete
      F-BAS-16 설비 조회 [조회] GET /bas/equipment
  BAS-05 불량코드 관리 → /bas/defect-codes
      F-BAS-17 불량코드 등록 [등록] POST /bas/defect-codes
      F-BAS-18 불량코드 수정 [수정] POST /bas/defect-codes/{id}
      F-BAS-19 불량코드 삭제 [삭제] POST /bas/defect-codes/{id}/delete
      F-BAS-20 불량코드 조회 [조회] GET /bas/defect-codes
"""

from fastapi import APIRouter

router = APIRouter()
