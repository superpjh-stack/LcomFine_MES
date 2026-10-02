# API 계약 — 오류 · 응답 규약 (아키텍트 · 2026-10-03)

> goal.md §2.5 오류 계약을 코드가 지키는 방식이다. QA1 이 이 표를 그대로 테스트 케이스로 쓴다.
> 구현은 `src/lcomfine/app/util/http.py`(예외 만들기) 와 `src/lcomfine/app/main.py`(핸들러). 엔드포인트 목록은 `function-list.md` 의 `API` 열이다.

## 1. 오류 계약

| 상황 | HTTP | `code` | 메시지 | 올리는 법 |
|---|---|---|---|---|
| 필수값 누락 · 코드 중복 · 없는 LOT/롤 스캔 · 이미 출하된 롤 재출하 · 자기 자신을 부모로 하는 계보 | **422** | `validation_error` | 상황에 맞는 문장 + 항목별 사유 | `raise http.validation_error("…", fields=[…])` |
| 인증 실패 (미로그인 · 로그인 실패) | **401** | `unauthorized` | `로그인이 필요합니다` | `rbac.require_*` 가 낸다 |
| 권한 없음 | **403** | `forbidden` | `접근 권한이 없습니다` | `rbac.require_screen` · `rbac.require_fn` 이 낸다 |
| 대상 없음 (경로의 키 · 없는 주소) | **404** | `not_found` | `대상을 찾을 수 없습니다` | `raise http.not_found()` |
| DB 연결 실패 | **503** | `db_unavailable` | `서비스 일시 중단` | `conn` 이 `DbUnavailable` 을 올린다 — 잡지 않는다 |
| ERP 연계 · 미확정 연계 | **501** | `undecided` | `… 미확정 (D-nn)` | `raise http.undecided("D-02", "ERP 연계")` |
| 처리되지 않은 예외 | **500** | `internal_error` | `예상하지 못한 오류` | 아무것도 하지 않는다 — 핸들러가 로그에 남긴다 |

- **조용한 실패 금지.** `try/except` 로 오류를 잡아 빈 목록·기본값·하드코딩 결과를 돌려주지 않는다. DB 를 끊었는데 화면이 멀쩡하면 결함이다.
- 422 와 404 의 경계: **사용자가 입력하거나 스캔한 번호**가 없으면 422(없는 LOT/롤 스캔), **경로에 박힌 키**가 없으면 404.
- 미구현 공용 모듈을 부르면 `NotImplementedError` → 500 이다. 501 은 "사람이 아직 정하지 않은 연계" 에만 쓴다.

## 2. 응답의 모양

요청의 `Accept` 에 `text/html` 이 있으면 브라우저로 본다. 없으면(테스트·스크립트) JSON 이다.

| 경우 | 브라우저 (`Accept: text/html`) | 그 밖 (JSON) |
|---|---|---|
| 화면 GET | 200 HTML | 200 HTML (화면은 HTML 뿐이다) |
| 쓰기 성공 | **303** → 원래 화면 + 알림 한 번 | **200** `{"ok": true, "message": "…", …}` (`http.saved(request, msg, data={…})`) |
| 422 (폼 POST) | **303** → 원래 화면 + 알림(메시지·항목별 사유). POP 은 큰 글씨, 닫으면 스캔칸으로 돌아간다 — 다음 스캔을 막지 않는다 | **422** `{"code": "validation_error", "message": "…", "fields": [{"name": …, "reason": …}]}` |
| 401 | GET 은 **303** → `/login?next=…` · POST 는 401 오류 화면 | **401** `{"code": "unauthorized", "message": "로그인이 필요합니다"}` |
| 403 · 404 · 501 · 503 · 500 | 그 상태코드의 오류 화면(`_error.html`) | 그 상태코드 + `{"code": …, "message": …}` (501 은 `decision` 포함) |

- 로그인: `POST /login`(`login_id` · `password` · `next` · `device`) — 성공 **303**, 실패 **401**(브라우저는 로그인 화면을 401 로 다시 그린다).
- **테스트는 JSON 쪽으로 판정한다.** `TestClient` 는 기본 `Accept: */*` 라 쓰기 성공 200 · 검증 실패 422 가 그대로 보인다.
- `/health` 는 인증 없이 200(DB 가 끊기면 503). `/static/*` 도 인증 없음.

## 3. DB 제약 위반은 422 다

라우터가 먼저 검사하는 것이 원칙이다. 놓친 경우에도 500 이 되지 않게 `main.py` 가 `psycopg.errors.IntegrityError`
(유니크 · FK · NOT NULL · CHECK · 계보 지킴이 트리거)를 **422** 로 바꾼다. 이때 `fields` 에는 제약 이름과 DB 메시지가 들어간다.
계보에서 이것이 뜻하는 바 — 순환, 자기 자신 부모, 재출하, 소진된 롤 출하는 `lineage` 가 놓쳐도 DB 가 막고 422 로 나온다(`db-schema.md` §3.4·§3.5).

## 4. 권한 판정 (G-17)

| 요청 | 의존성 | 결과 |
|---|---|---|
| 화면 GET | `rbac.require_screen(화면 ID)` 또는 조회 기능이면 `rbac.require_fn(기능 ID)` | 칸이 `없음` → 403 |
| 읽기 기능(`조회` `출력`) | `rbac.require_fn(기능 ID)` | 칸이 `없음` → 403 |
| 쓰기 기능(`등록` `수정` `삭제` `승인` `스캔`) | `rbac.require_fn(기능 ID)` | 칸이 `입력` 이 아니거나 기능의 범위가 칸의 `write_scope` 에 없으면 → 403 |

순서는 401 → 403 → 422 다. 권한이 없는 사람에게 입력값 오류를 먼저 알려 주지 않는다(의존성이 본문 검증보다 먼저 돈다).
쓰기 엔드포인트에 `rbac.require_fn` 이 빠지면 `조회` 역할의 쓰기가 통과한다 — QA1 이 48칸 × 쓰기 기능을 전수로 두드린다.

## 5. 접근 로그 (G-18)

| 구분 | 남기는 곳 | 언제 |
|---|---|---|
| `로그인` | `auth.authenticate` · `auth.logout_session` | 성공 · 실패(미등록 ID · 비밀번호 불일치 · 정상 아닌 계정) · 로그아웃 |
| `조회` | `templating.render(…, screen_id=…)` | 로그인한 사용자가 화면을 열 때마다 |
| `변경` | `audit.log_change(request, user, 기능 ID, 대상, 내용)` | **쓰기 기능이 성공할 때마다 — 개발자가 부른다** |
| `오류` | `main.py` 의 500 핸들러 | 처리되지 않은 예외 |

`sys_access_log` 한 줄 = 누가(`login_id` `role_code`) · 언제(`logged_at`) · 무엇을(`function_id` `target` `detail`). 시스템 관리 > 로그(F-SYS-07)가 이 표를 보여 준다.

## 6. 범위 밖 (G-12)

설비 PLC 실시간 수집 · 비전 검사 연동 · AI 분석에 해당하는 엔드포인트·테이블·메뉴를 만들지 않는다. 설비는 기준정보(설비 관리)까지다.
