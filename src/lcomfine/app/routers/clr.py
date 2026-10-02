"""clr 라우터 — 조색 기록 (기능 5) · 담당 개발2.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D4. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("CLR-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  CLR-01 조색 기록 → /clr/records
      F-CLR-01 조색 기록 등록 [등록] POST /clr/records
      F-CLR-02 배합비 등록 [등록] POST /clr/records/{id}/mix
      F-CLR-03 조색 기록 수정 [수정] POST /clr/records/{id}
      F-CLR-04 조색 기록 삭제 [삭제] POST /clr/records/{id}/delete
      F-CLR-05 조색 기록 조회 [조회] GET /clr/records
"""

from fastapi import APIRouter

router = APIRouter()
