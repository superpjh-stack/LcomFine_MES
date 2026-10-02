"""rll 라우터 — 후가공 · 슬리팅 롤 이력 (기능 7) · 담당 개발2.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D6. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("RLL-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  RLL-01 후가공 → /rll/finishing
      F-RLL-01 후가공 실적 등록 [등록] POST /rll/finishing
      F-RLL-02 splice 등록 [등록] POST /rll/finishing/splice
      F-RLL-03 후가공 조회 [조회] GET /rll/finishing
  RLL-02 슬리팅 → /rll/slitting
      F-RLL-04 슬리팅 분할 등록 [등록] POST /rll/slitting
      F-RLL-05 슬리팅 조회 [조회] GET /rll/slitting
  RLL-03 롤 이력 → /rll/history
      F-RLL-06 롤 이력 조회 [조회] GET /rll/history
      F-RLL-07 롤 라벨 출력 [출력] GET /rll/history/{roll_no}/label
"""

from fastapi import APIRouter

router = APIRouter()
