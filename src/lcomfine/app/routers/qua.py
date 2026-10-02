"""qua 라우터 — 품질 검사 기록 (기능 6) · 담당 개발3.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D7. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("QUA-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  QUA-01 검사 결과 → /qua/inspections
      F-QUA-01 검사 결과 등록 [등록] POST /qua/inspections
      F-QUA-02 검사 결과 수정 [수정] POST /qua/inspections/{id}
      F-QUA-03 검사 결과 삭제 [삭제] POST /qua/inspections/{id}/delete
      F-QUA-04 검사 결과 조회 [조회] GET /qua/inspections
  QUA-02 불량 집계 → /qua/defect-stats
      F-QUA-05 불량 유형별 집계 조회 [조회] GET /qua/defect-stats
      F-QUA-06 불량 롤 조회 [조회] GET /qua/defect-stats/rolls
"""

from fastapi import APIRouter

router = APIRouter()
