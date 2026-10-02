"""prt 라우터 — 인쇄 기준 관리 (기능 12) · 담당 개발1.

아키텍트가 만든 **빈 스텁**이다. 담당 개발자가 이 파일을 채운다(한 파일은 한 사람만 — decisions.md D-22).
쓰는 저장소: D1. 이 밖의 테이블에는 쓰지 않는다(G-05).

규약 (contracts/interfaces.md)
  · 화면 경로는 `nav.path_of("PRT-01")` — 문자열로 다시 적지 않는다.
  · 화면 GET 은 `rbac.require_screen(화면 ID)`, 기능 엔드포인트는 `rbac.require_fn(기능 ID)`.
  · 화면 GET 을 여기 등록하면 그 경로의 placeholder 는 저절로 빠진다.
  · 쓰기 성공 뒤 `audit.log_change(...)` · 응답은 `http.saved(...)`.

담당 화면과 기능 (contracts/function-list.md)
  PRT-01 판사양 관리 → /prt/plates
      F-PRT-01 판사양 등록 [등록] POST /prt/plates
      F-PRT-02 판사양 수정 [수정] POST /prt/plates/{id}
      F-PRT-03 판사양 삭제 [삭제] POST /prt/plates/{id}/delete
      F-PRT-04 판사양 조회 [조회] GET /prt/plates
  PRT-02 아니록스 관리 → /prt/anilox
      F-PRT-05 아니록스 등록 [등록] POST /prt/anilox
      F-PRT-06 아니록스 수정 [수정] POST /prt/anilox/{id}
      F-PRT-07 아니록스 삭제 [삭제] POST /prt/anilox/{id}/delete
      F-PRT-08 아니록스 조회 [조회] GET /prt/anilox
  PRT-03 잉크조성 관리 → /prt/inks
      F-PRT-09 잉크조성 등록 [등록] POST /prt/inks
      F-PRT-10 잉크조성 수정 [수정] POST /prt/inks/{id}
      F-PRT-11 잉크조성 삭제 [삭제] POST /prt/inks/{id}/delete
      F-PRT-12 잉크조성 조회 [조회] GET /prt/inks
"""

from fastapi import APIRouter

router = APIRouter()
