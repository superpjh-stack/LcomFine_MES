"""shp 라우터 — 출하 (기능 7) · 담당 개발3.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D8 (+ 계보의 `출하` 행 — lineage 경유). 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("SHP-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  SHP-01 출하 → /shp/shipments
      F-SHP-01 출하 등록 [등록] POST /shp/shipments
      F-SHP-02 출하 롤 스캔 [스캔] POST /shp/shipments/{shipment_no}/rolls
      F-SHP-03 출하 취소 [삭제] POST /shp/shipments/{shipment_no}/cancel
      F-SHP-04 출하 조회 [조회] GET /shp/shipments
  SHP-02 출하 승인 → /shp/approvals
      F-SHP-05 출하 승인 [승인] POST /shp/approvals/{shipment_no}/approve
  SHP-03 COA → /shp/coa
      F-SHP-06 COA 조회 [조회] GET /shp/coa
      F-SHP-07 COA 출력 [출력] GET /shp/coa/{shipment_no}/print
"""

from fastapi import APIRouter

router = APIRouter()
