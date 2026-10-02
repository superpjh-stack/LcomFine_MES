"""pop 라우터 — 생산 실적 (POP) (기능 8) · 담당 개발2.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D5 · D6(인쇄 롤). 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("POP-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
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
"""

from fastapi import APIRouter

router = APIRouter()
