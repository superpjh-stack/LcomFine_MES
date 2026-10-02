# CLAUDE.md

**엘컴화인 MES** — 신규 웹 시스템(웹 애플리케이션 하나 + DB 하나). 설계도 2안(전체개발) 기준.
이 시스템의 본체는 **Job-Lot-Roll 계보**다. 롤이 합쳐지고(splice N:1) 나뉘어도(슬리팅 1:N) `roll_genealogy` 에 부모 → 자식 한 줄씩만 남기고, 추적은 그 기록을 따라가는 조회다.
완료 기준: **출하 롤 하나에서 원재료 LOT 까지 거슬러 올라갈 수 있어야 한다.**

## 먼저 읽는다

1. **`goal.md`** — 목표 · 수용 게이트 G-01~G-22 · 팀 편성 · 루프 프로토콜 · 에이전트 기동 프롬프트. **전원 필독. 사람만 고친다.**
2. `contracts/` — 코드 계약. **개발은 이것만 보고 만든다.** 계약에 없는 것을 혼자 정하지 않는다.
   - `function-list.md` 기능 100줄(화면 94 + 이관 배치 6) — ID · API · 쓰는 테이블 · 권한 · 계약 문장
   - `db-schema.md` 테이블 30 · 쓰기 경계 · `roll_genealogy` 설계 근거
   - `screen-map.md` 중메뉴 32 → 경로 · 담당 · 채널 · 파일 소유권
   - `interfaces.md` 공용 모듈 시그니처(`lineage` `numbering` `printing` `rbac` `erp` `stats`) · `api-contract.md` 오류 계약
3. `decisions.md` — 결정 대장 D-nn (`확정` / `가설` / `차단`). **여기 없는 것을 마음대로 정하지 않는다.**
4. `progress.md` — 검증된 현황의 유일한 진실. 실측값 + 검증 명령만 적는다.

계약과 코드가 다르면 **코드가 맞다** — 발견자가 계약을 고친다. 단 `schema.sql` · `nav.py` · `function-list.md` 는 아키텍트만 고친다(요청은 `progress-devN.md` §3).

## 정본 (읽기 전용)

- `엘컴화인_MES_설계도 복사본.html` — 그림 5 · 표 3. **고치거나 옮기지 않는다.** 메뉴 이름·기능 수·권한 칸·프로세스의 쓰는 저장소·입력 낱말·테이블 이름 4개가 여기서 온다.
- 설계도에 없는 것(컬럼 · 경로 · 기능 94개의 낱낱 · 채번 형식)은 전부 `가설` 이다. 「엘컴화인 MES 구축 기획서」·FP산정서 원본이 `docs/` 에 오면 그것이 우선한다.
- 검사 도구는 기대값을 설계도에서 직접 읽는다(`tools/design_doc.py`). 앱은 설계도를 읽지 않는다.

## 환경

- PostgreSQL 17 (unix socket `/tmp`), DB **`lcomfine_db`**. 포트 **8020** (8000 은 다른 사업이 쓴다).
- `uv` / Python 3.12. **명령은 전부 `uv run …`** — 시스템 `python3` 를 쓰지 않는다.
- 환경변수 접두 `LCOMFINE_` (`.env.example`). 비밀(세션 비밀 · 시드 비밀번호)은 로컬 `.env`(gitignore)에만 — **코드·문서에 값을 적지 않는다**(G-19). `make setup` 이 `.env` 를 난수로 만든다.
- **이 폴더 밖은 읽기만 한다.** 다른 사업 폴더와 그 DB 를 고치지 않는다. push · 배포 · 외부 전송 없음.

## 명령

`make setup` · `db-schema` · `db-seed` · `db-reset` · `contracts`(렌더본 다시 찍기) · `run` · `test` · `check-routes` · `check-trace` · `check-schema` · `check-data` · `check-security` · **`gate`**(G-01~G-22 판정표) · **`gate-full`**(시드 재실행 포함 — 종료 판정은 이것으로) · `backup`(pg_dump → `backups/`) · `restore-check`(임시 DB 에 복구해 행 수 대조 — 운영 DB 는 그대로).
시드와 스키마 재생성은 한 번에 하나만 돈다(`db-schema` 는 데이터를 전부 지운다 — 데이터가 있는 DB 의 스키마 변경은 `ALTER` 로 반영하고 `schema.sql` 과 맞춘다).
Docker: `docker compose up -d --build`(앱 + PostgreSQL 17 · 비밀 3개는 `.env` — D-31).

## 규모 (설계도에서 센 값 — `make check-trace`)

묶음 4 · 대메뉴 **12** · 중메뉴 **32** · 화면 기능 **94** + 이관 배치 **6** · 역할 **4** · 권한 **48칸**(입력 19 · 조회 24 · 없음 5) · 채널 4(관리자 Web · 현장 POP · 모바일 · 현황판) · 프로세스 P1~P10 · 저장소 D1~D8 → 테이블 30(D1~D8 23 + SYS 7).

| 담당 | 대메뉴 (모듈) | 기능 | 공용 모듈 |
|---|---|---|---|
| 개발1 | 기준정보 관리(bas) · 인쇄 기준 관리(prt) · 작업지시 관리(job) · 시스템 관리(sys) · 메인(home) | 46 | `numbering.py` |
| 개발2 | 생산 실적 POP(pop) · 자재·입고(mat) · 조색 기록(clr) · 후가공·슬리팅 롤 이력(rll) | 28 | `lineage.py` · `printing.py` |
| 개발3 | 품질 검사 기록(qua) · 출하(shp) · LOT 추적(trc) · 실적 현황(sta) + 이관 배치 | 20 + 6 | `erp.py` · `stats.py` · `migration/` |

## 코드 규약 (contracts/interfaces.md)

- 패키지 `lcomfine` (`src/lcomfine/{app,db}`). 라우터는 `app/routers/<모듈>.py` 에 `router = APIRouter()` — `main.py` 가 자동 include 한다. **개발자는 `main.py` 를 만지지 않는다.**
- 경로: `nav.path_of("BAS-01")`. 화면 GET 을 등록하면 그 경로의 placeholder 가 빠진다. 기능의 메서드·경로는 `function-list.md` 의 `API` 열과 글자 그대로.
- 권한: 화면 `rbac.require_screen("BAS-01")` · 기능 `rbac.require_fn("F-BAS-01")`. **쓰기 엔드포인트에 `require_fn` 이 빠지면 조회 역할의 쓰기가 통과한다.** 권한 표는 DB 데이터다 — 역할·칸을 코드에 박지 않는다.
- 세션: 사용자의 역할·상태는 쿠키가 아니라 **요청마다 DB 에서** 읽는다(`rbac.current_user`). 중지·잠금·로그아웃한 세션은 다음 요청부터 401, 역할 변경은 다음 요청부터 반영(D-26).
- DB: `conn.q / q1 / x / tx`. 함께 성공해야 하는 것은 `tx()` 하나에.
- 계보: `roll_genealogy` 에 쓰는 곳은 `lineage` 뿐. 번호를 만드는 곳은 `numbering` 뿐. 집계 SQL 은 `stats` 뿐. 라벨·바코드는 `printing` 뿐.
- 오류: `http.validation_error`(422) · `http.not_found`(404) · `http.undecided("D-nn")`(501). 쓰기 성공은 `http.saved(request, msg)`, 그 직후 `audit.log_change(...)`. 입력값 오류는 500 이 아니다 — DB 가 담을 수 없는 값(NUL · 자릿수 초과)도 422 이고, 사람이 읽을 문장은 라우터가 먼저 검사해서 준다.
- 스캔 화면: 스캔칸은 `ui.scan_box`(화면에 `data-scan` 하나). 스캔 진입 GET 에서 없는 번호는 **그 화면을 422 로 다시 그린다**(스캔칸 유지). 알림 중의 스캔·닫은 뒤의 포커스는 `static/app.js` 가 한다 — 템플릿에 스크립트를 넣지 않는다.
- 렌더: `templating.render(request, tpl, ctx, screen_id=...)` — 메뉴 · 계약 패널 · 채널 레이아웃 · 조회 로그 자동. 공용 매크로 `templates/home/_macros.html`.
- 테스트: 기능마다 하나 이상, `@pytest.mark.fn("F-BAS-01")` 표식.

## 작업 원칙

- **지어내지 않는다.** 고객명·품목명·규격값·채번 형식은 받은 적이 없다. 시드는 `(예시)` 를 붙인다. 데이터가 없으면 `미수집`, 정해지지 않았으면 `미확정 (D-nn)`.
- **조용한 실패 금지.** `try/except` 로 하드코딩 결과를 끼워넣지 않는다. 실패는 사용자에게 보인다.
- **쓰기 경계.** 프로세스는 자기 저장소에만 쓴다(`db-schema.md` §2). **P9 LOT 추적 · P10 실적 현황은 어떤 테이블에도 쓰지 않는다.** 추적·집계 결과를 캐시 테이블에 쌓지 않는다.
- **범위 밖 금지.** 설비 실시간 수집 · 비전 검사 · AI 분석은 메뉴·엔드포인트·테이블 어디에도 만들지 않는다. 설비는 기준정보(설비 관리)까지.
- **용어.** 이 회사 용어는 Job · Lot · Roll · 판사양 · 아니록스 · 잉크조성 · 조색 · 배합비 · ΔE · 후가공 · 슬리팅 · splice · COA · 현황판. 골격을 가져온 다른 사업의 용어·테이블·화면을 옮겨 오지 않는다.
- **한 파일은 한 사람만 만진다.** 소유권은 `decisions.md` D-22 · `screen-map.md` §3.
- **게이트를 낮추지 않는다.** 테스트를 지우거나 `skip` 하거나 수치를 내리지 않는다.
- 설계도의 결함이나 모순은 고치지 말고 `decisions.md` 에 적는다(예: D-12).
