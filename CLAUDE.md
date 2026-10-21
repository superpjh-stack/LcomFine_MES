# CLAUDE.md

**엘컴화인 MES v2** — 신규 웹 시스템(웹 애플리케이션 하나 + DB 하나). 정본은 2026-10-21 새 기획서(D-501).
이 시스템의 본체는 **생산의뢰 → 생산지시 → 자재 불출 → 생산·검사 → 제품 입고 → 판정 → 출하 → ERP 수금 흐름과 LOT 추적**이다. 부서마다 자기 일을 「내 할 일」과 알림으로 받는다.
완료 기준: **출하 1건에서 원자재 LOT 까지 거슬러 올라갈 수 있어야 한다**(`material_lot` → 불출 → `work_order` → 제품 입고 → `product_lot` → `shipment_order`).

## 먼저 읽는다

1. **`goal.md`** — 목표 · 수용 게이트 G-01~G-24 · 팀 · 웨이브 · 루프 프로토콜 · 기동 프롬프트. **전원 필독. 사람만 고친다.**
2. `contracts/` — 코드 계약. **개발은 이것만 보고 만든다.** 계약에 없는 것을 혼자 정하지 않는다.
   - `ia.json` · `ia-overrides.json` — 정본 기계 추출 + 사람 결정 편차(D-505). 게이트의 기대값. 이름은 여기서 복사한다
   - `function-list.md` 기능(D-508 전개) · `db-schema.md` 테이블 · 쓰기 경계 · `screen-map.md` 경로 · 담당 · `permission-matrix.md` 권한 260 칸
   - `interfaces.md` 공용 모듈 시그니처 · `api-contract.md` 오류 계약
3. `decisions.md` — 결정 대장 D-501~ (`확정` / `가설` / `차단`). **여기 없는 것을 마음대로 정하지 않는다.** 옛 대장 `decisions-v1.md` 는 효력 없음.
4. `progress.md` — 검증된 현황의 유일한 진실. 실측값 + 검증 명령만 적는다(옛 판 `progress-v1.md`).

계약과 코드가 다르면 **코드가 맞다** — 발견자가 계약을 고친다. 단 `schema.sql` · `nav.py` · `function-list.md` 는 아키텍트만 고친다(요청은 `progress-devN.md` §3).

## 정본 (읽기 전용)

- `docs/엘컴화인_MES_기획서_2026-10-21.html` — **고치거나 옮기지 않는다.** 묶음 · 대메뉴 · 화면 · 유형 · 부서 · 권한 칸 · L3 · logic · 업무 흐름 · 알림 배치가 여기서 온다.
- 설계 스펙 `docs/superpowers/specs/2026-10-21-mes-v2-design.md`. 옛 설계도는 `docs/archive/` — 참고만.
- 정본에 없는 것(컬럼 · 경로 · 기능 낱낱 · 채번 형식)은 전부 `가설` 이다. 기대값은 `tools/design_doc.py` 가 정본에서 직접 읽는다. 앱은 정본도 ia.json 도 읽지 않는다.

## 환경

- PostgreSQL 17 (unix socket `/tmp`), DB **`lcomfine_db`**. 포트 **8020** (8000 은 다른 사업이 쓴다).
- `uv` / Python 3.12. **명령은 전부 `uv run …`** — 시스템 `python3` 를 쓰지 않는다.
- 환경변수 접두 `LCOMFINE_` (`.env.example`). 비밀은 로컬 `.env`(gitignore)에만 — **코드·문서에 값을 적지 않는다**(G-21). `make setup` 이 `.env` 를 난수로 만든다.
  `LCOMFINE_OPENAI_API_KEY` · `LCOMFINE_OPENAI_MODEL`(기본 `gpt-4.1`) · `LCOMFINE_DOC_SSO_URL` · `LCOMFINE_SSO_SECRET` · `LCOMFINE_SEED_PASSWORD`.
- **이 폴더 밖은 읽기만 한다.** 다른 사업 폴더와 그 DB 를 고치지 않는다. push · 배포 · 외부 전송 없음(데이터 질의의 OpenAI 호출만 D-504 예외).

## 명령

`make setup` · `db-schema` · `db-seed` · `db-reset` · `contracts`(렌더본 다시 찍기) · `run` · `test` · `check-trace`(G-01 · 02) · `check-routes`(G-03) · `check-schema`(G-04) · `check-data`(G-05~15) · `check-security`(G-16~22) · **`gate`**(G-01~G-24 판정표) · **`gate-full`**(시드 재실행 포함 — 종료 판정은 이것으로) · `backup` · `restore-check`(G-23 · 임시 DB 에 복구해 행 수 대조).
배치: `uv run python -m lcomfine.jobs due-check`(납기 D-3 미출하 알림). Docker: `docker compose up -d --build` → `/health`(G-24).
시드와 스키마 재생성은 한 번에 하나만 돈다(`db-schema` 는 데이터를 전부 지운다 — 데이터가 있는 DB 의 스키마 변경은 `ALTER` 로 반영하고 `schema.sql` 과 맞춘다).

## 규모 (정본 + D-505 에서 센 값 — `make check-trace`)

묶음 **8**(⓪ 내 업무 ~ ⑦ 지원) · 대메뉴 **17** · 화면 **67**(정본 71 − RPT 4) · 부서 **8** · 권한 **260 칸**(W 64 · R 196 / 536) · 채널 **1**(Web) · 알림 **9** · 업무 흐름 **7**단계(수주 → 작업지시 → 자재 불출 → 생산·검사 → 제품 입고 → 출하 → 수금).
부서: 영업부 SL · 생산부 PR · 출하실 SH · 디자인·개발실 DS · 회계부 AC · 전략부 ST · 경영진 EX · 전산 관리자 ADM(전 화면 R 이상). 좌측 메뉴와 메인은 정본 묶음 ⓪~⑦ 과 순서 그대로. RPT 는 이름만 「대시보드」(D-505).

| 담당 | 대메뉴 (화면 수) | 화면 | 공용 모듈 |
|---|---|---|---|
| 개발1 | HOME 내 업무(3) · BAS 기준정보(3) · STD 인쇄 기준(6) · WO 작업지시(4) · SYS 시스템(4) · TRK 통합 조회(3) · DOC 문서관리(2, W4) | 25 | `jobs.py` · `sso.py` |
| 개발2 | MAT 자재·입고(4) · PRD 생산일보(4) · INS 검사일보(4) · QC 품질 검사(3) · INV 재고(3) · LOT LOT 추적(2) | 20 | `trace.py` |
| 개발3 | SHP 출하(3) · PRP 생산 보고서(3) · COL 수금리포트(7, W2) · RPT 대시보드(9, W3) | 22 | `stats.py` · `erp_upload.py` · `dashboard.py` · `ai.py` · `dataquery.py` |
| 아키텍트 | `schema.sql` · `nav.py` · `main.py` · `contracts/*` · `rbac` · `templating` · `notify` · `numbering` | — | |

웨이브(D-506): W1 핵심 흐름 → W2 수금 → W3 대시보드 → W4 문서 SSO. 각 끝에 QA 3 → 수정 → `make gate-full` PASS → 로컬 커밋.

## 코드 규약 (contracts/interfaces.md)

- 패키지 `lcomfine` (`src/lcomfine/{app,db}`). 라우터는 `app/routers/<대메뉴 코드 소문자>.py` 에 `router = APIRouter()` — `main.py` 가 자동 include 한다. **개발자는 `main.py` 를 만지지 않는다.**
- 경로: `nav.path_of("WO-010")` (`/<코드 소문자>/<slug>` · D-507). 화면 GET 을 등록하면 그 경로의 placeholder 가 빠진다. 기능의 메서드·경로는 `function-list.md` 의 `API` 열과 글자 그대로. 기능 ID `F-<L1>-<화면 두 자리><순번>`(WO-010 → `F-WO-011`).
- 권한: 화면 `rbac.require_screen("WO-010")`(R 이상) · 기능 `rbac.require_fn("F-WO-011")`(쓰기면 W). **쓰기 엔드포인트에 `require_fn` 이 빠지면 R 부서의 쓰기가 통과한다.** 권한 표는 DB 데이터(`sys_permission`) — 부서·칸을 코드에 박지 않는다.
- 세션: 사용자의 상태·부서는 쿠키가 아니라 **요청마다 DB 에서** 읽는다(`rbac.current_user`). 비활성·로그아웃한 세션은 다음 요청부터 401(SSO 토큰도 발급 안 됨).
- DB: `conn.q / q1 / x / tx`. 함께 성공해야 하는 것은 `tx()` 하나에.
- 한 곳 규칙: 번호는 `numbering.next(kind, cur)` 뿐 · 알림은 `notify.emit(cur, event, *, link, dedupe_key, text)` 뿐(**쓰기 트랜잭션 안에서** · 수신 부서마다 1행 · D-511) · LOT 추적은 `trace` 뿐(읽기만) · 집계 SQL 은 `dashboard` · `stats` 뿐 · AI 호출은 `ai` 뿐(호출마다 `sys_ai_call_log`) · 질의 검증은 `dataquery` 뿐 · SSO 토큰은 `sso` 뿐.
- 오류: `http.validation_error`(422) · `http.not_found`(404) · `http.undecided("D-nn")`(501). 쓰기 성공은 `http.saved(request, msg)`, 그 직후 `audit.log_change(...)`. 입력값 오류는 500 이 아니다 — DB 가 담을 수 없는 값도 422 이고, 사람이 읽을 문장은 라우터가 먼저 검사해서 준다.
- 렌더: `templating.render(request, tpl, ctx, screen_id=...)` — 메뉴 · 계약 패널 · 조회 로그 자동. 채널 분기 없음(반응형 1280 · 390 가로 스크롤 0). 공용 매크로 `templates/home/_macros.html`. 대시보드 차트는 인라인 SVG + 표, 색은 CSS 토큰. `static/app.js` 는 폼 보조(확인 대화 · 포커스)만 — 템플릿에 스크립트를 넣지 않는다.
- 테스트: 기능마다 하나 이상, `@pytest.mark.fn("F-WO-011")` 표식.

## 작업 원칙

- **지어내지 않는다.** 고객명·품목명·규격값·채번 형식은 받은 적이 없다. 시드는 `(예시)` 를 붙인다. 데이터가 없으면 `미수집`, 정해지지 않았으면 `미확정 (D-nn)`.
- **조용한 실패 금지.** `try/except` 로 하드코딩 결과를 끼워넣지 않는다. AI 키가 없거나 실패하면 그 사실이 화면에 보인다.
- **쓰기 경계.** 화면은 자기 대메뉴의 테이블에만 쓴다(예외는 `db-schema.md` 에 — QC 의 재고 상태 · 출하 지시의 할당 · `notification`). **TRK · LOT · PRP · RPT 는 어떤 업무 테이블에도 쓰지 않는다**(데이터 질의는 `data_query_log` · `sys_ai_call_log` 만). 추적·집계 결과를 캐시 테이블에 쌓지 않는다. 수금 데이터는 업로드 회차 교체로만 바뀐다.
- **범위 밖 금지.** 설비 실시간 수집 · 비전 검사 · 매출전표/세금계산서/발주/근태/품의/원가 · 문서 저장 · AI 해설 리포트 · Web 밖의 별도 채널은 메뉴·엔드포인트·테이블 어디에도 만들지 않는다.
- **용어.** 이 회사 용어는 생산의뢰 · 생산지시 · 불출 · 생산일보 · 검사일보 · 판정 · 재판정 · LOT · 분할 순번 · 출하 지시 · 출하 확정 · 회차 · 미수 연령 · 대시보드 · SSO. 옛 판(D-502)과 다른 사업의 용어·테이블·화면을 옮겨 오지 않는다.
- **한 파일은 한 사람만 만진다.** 소유는 `goal.md` §3.2 · §3.3.
- **게이트를 낮추지 않는다.** 테스트를 지우거나 `skip` 하거나 수치를 내리지 않는다.
- 정본의 결함이나 모순은 고치지 말고 `decisions.md` 에 적는다.
