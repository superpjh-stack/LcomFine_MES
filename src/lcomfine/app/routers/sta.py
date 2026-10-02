"""sta 라우터 — 실적 현황 (기능 4) · 담당 개발3.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: 없음 — 읽기 전용. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("STA-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  STA-01 집계 (생산, 품질, 납기) → /sta/summary
      F-STA-01 생산 집계 조회 [조회] GET /sta/summary/production
      F-STA-02 품질 집계 조회 [조회] GET /sta/summary/quality
      F-STA-03 납기 집계 조회 [조회] GET /sta/summary/delivery
  STA-02 현황판 → /sta/board
      F-STA-04 현황판 [조회] GET /sta/board
"""

from fastapi import APIRouter

router = APIRouter()
