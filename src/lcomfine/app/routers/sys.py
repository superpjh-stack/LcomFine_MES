"""sys 라우터 — 시스템 관리 (기능 7) · 담당 개발1.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: SYS. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("SYS-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  SYS-01 사용자 → /sys/users
      F-SYS-01 사용자 등록 [등록] POST /sys/users
      F-SYS-02 사용자 수정 [수정] POST /sys/users/{login_id}
      F-SYS-03 사용자 삭제 [삭제] POST /sys/users/{login_id}/delete
      F-SYS-04 사용자 조회 [조회] GET /sys/users
  SYS-02 권한 → /sys/permissions
      F-SYS-05 권한 조회 [조회] GET /sys/permissions
      F-SYS-06 권한 수정 [수정] POST /sys/permissions
  SYS-03 로그 → /sys/logs
      F-SYS-07 로그 조회 [조회] GET /sys/logs
"""

from fastapi import APIRouter

router = APIRouter()
