# 엘컴화인 MES v2 — 설계 스펙 (2026-10-21)

경영진 미팅 뒤 받은 새 기획서 「엘컴화인 MES 통합본 — 화면 구조(IA) · 부서 간 업무 변화 · 2026-10-21」(`elcomfine-mes-all_1.html`)을 **정본**으로 삼아 기획 · 디자인 · 개발 · QA 를 다시 한다.
이 문서는 사람과 합의한 설계다. 세부 계약은 Phase 0 에서 `contracts/` 로 전개한다.

## 0. 사람이 정한 것 (2026-10-21 · 확정)

| 번호 | 결정 |
|---|---|
| D-501 | 새 기획서가 정본이다. 옛 설계도(`엘컴화인_MES_설계도 복사본.html`)는 `docs/archive/` 로 옮겨 참고만 한다. 수 · 메뉴 · 권한의 기대값은 전부 새 정본에서 읽는다. |
| D-502 | Job-Lot-Roll 롤 계보(`roll` · `roll_genealogy` · splice · 슬리팅 · 조색 · 아니록스 · 판사양)는 **버린다**. 추적 단위는 기획서대로 LOT 다. |
| D-503 | 코드는 골격(rbac · templating · nav · conn · audit · http · numbering · 게이트 도구 · Docker · 테스트 하네스)만 남기고 도메인(스키마 · 라우터 · 템플릿 · 시드 · 테스트)은 새로 쓴다. 같은 저장소, 옛 코드는 git 이력으로 남는다. |
| D-504 | 데이터 질의(RPT-130)의 모델은 **OpenAI**. 키는 `.env` 의 `LCOMFINE_OPENAI_API_KEY`, 모델은 `LCOMFINE_OPENAI_MODEL`(기본 `gpt-4.1`). 코드 · 문서에 값을 적지 않는다. |
| D-505 | 기획서의 「AI 리포트」는 **「대시보드」로 바꾼다** — 리포트 초안 · 검토 · 확정 · 양식 · 스케줄 · 이력(RPT-090~120) 을 없애고, 8개 리포트(RPT-010~080)는 화면을 열 때 실시간 SQL 집계로 그리는 대시보드가 된다. 데이터 질의(RPT-130)만 AI 를 쓴다. 전 부서가 쓰고 캐시 테이블은 없다. 대메뉴 코드 `RPT` 와 화면 ID 는 정본 추적을 위해 유지하고 이름만 「대시보드」. |
| D-506 | 4 웨이브(핵심 흐름 → 수금 → 대시보드 → 문서 SSO)를 **멈추지 않고** 진행한다. 각 웨이브 끝에 QA → 결함 수정 → 게이트 PASS → 로컬 커밋. |

정본 기본 상태(개정 12 기준안)를 그대로 쓴다: 공정 메뉴 21 은 FINE_MES 에서 **새 MES 로 이관**, 수금리포트 · 대시보드 · 문서관리 SSO · 내 업무 · 통합 조회 전부 포함.

## 1. 정본과 문서 체계

- `docs/엘컴화인_MES_기획서_2026-10-21.html` — 정본(읽기 전용). 고치거나 옮기지 않는다.
- **기대값은 기계로 읽는다.** `tools/design_doc.py` 가 정본의 두 iframe(`srcdoc`) 안 `ROLES` · `BUNDLES` · `ORDER` · `IA`(l3 · logic · links · data · batch 포함) · `SELF_GRANTS` · `mapRoles` 규칙 · `FLOW` 를 node 로 평가해 `contracts/ia.json` 으로 뽑는다. `contracts/ia-overrides.json` 이 D-505 같은 사람 결정에 따른 편차를 D-번호와 함께 담는다. **게이트의 기대값 = ia.json + ia-overrides.json.** 앱은 둘 다 읽지 않는다 — `nav.py` 가 코드이고 게이트가 둘을 대조한다.
- `goal.md` · `CLAUDE.md` · `decisions.md` · `contracts/*` 를 새 정본 기준으로 다시 쓴다. 옛 결정 대장은 `decisions-v1.md` 로 보존하고 새 대장은 D-501 부터. 기획서가 비워 둔 것은 `가설`, 사람이 정할 것은 `차단`.
- `progress.md` 는 새로 시작한다(옛 내용은 `progress-v1.md`).

## 2. 규모 (정본 + D-505 편차에서 센 값)

묶음 8(⓪ 내 업무 ~ ⑦ 지원) · 대메뉴 **17** · 화면 **67**(정본 71 − RPT 4) · 부서(역할) **8** · 권한 칸 **260**(W 64 · R 196 / 536) · 채널 **1**(Web) · 알림 배치 9 · 업무 흐름 띠 7단계(수주 → 작업지시 → 자재 불출 → 생산·검사 → 제품 입고 → 출하 → 수금).

| 묶음 | 대메뉴(코드 · 화면 수) |
|---|---|
| ⓪ 내 업무 | HOME 내 업무 3 |
| ① 기준 | BAS 기준정보 3 · STD 인쇄 기준 6 |
| ② 수주·지시 | WO 작업지시 4 |
| ③ 자재·생산 | MAT 자재·입고 4 · PRD 생산일보 4 · INS 검사일보 4 |
| ④ 품질·재고 | QC 품질 검사 3 · INV 재고 3 |
| ⑤ 출하·수금 | SHP 출하 3 · COL 수금리포트 7 |
| ⑥ 추적·분석 | TRK 통합 조회 3 · LOT LOT 추적 2 · PRP 생산 보고서 3 · RPT 대시보드 9 |
| ⑦ 지원 | DOC 문서관리 2 · SYS 시스템 4 |

부서 8: 영업부 SL · 생산부 PR · 출하실 SH · 디자인·개발실 DS · 회계부 AC · 전략부 ST · 경영진 EX · 전산 관리자 ADM. 전산 관리자는 전 화면 R 이상(정본 규칙).

## 3. 구조

### 3.1 메뉴 · 경로 · 라우터
- 대메뉴 17 = 라우터 17 `app/routers/<code 소문자>.py`, `main.py` 자동 include(유지).
- 화면 ID 는 정본 그대로(`WO-010`). 경로는 `/<l1 소문자>/<영문 slug>`(예 `/wo/requests`, `/col/uploads`). slug 는 `nav.py` 가 정하고 `screen-map.md` 에 렌더한다. `nav.path_of("WO-010")`.
- 좌측 메뉴와 메인 카드는 정본의 **묶음 ⓪~⑦ 과 ORDER 순서 그대로**(이번 정본은 묶음을 그린다).
- 채널은 Web 하나. `?device=` · POP/모바일/현황판 레이아웃 · 스캔칸 규약은 없앤다. 반응형(1280 · 390 가로 스크롤 0)은 유지.

### 3.2 기능 목록(function-list.md) 전개 규칙 — `가설`
화면 유형에서 기능을 전개하고, 정본의 L3 · logic 문장을 각 기능의 계약 문장으로 옮긴다.

| 유형 | 기능 | 예 |
|---|---|---|
| 조회 · 리포트 · 출력 | 조회 1 | `GET` 하나 |
| 등록 | 등록 · 수정 · 조회 3 | |
| 목록·등록 | 등록 · 수정 · 삭제(또는 중지) · 조회 4 | 참조가 있으면 삭제 대신 사용 중지 |
| 등록·출력 | 등록 · 수정 · 조회 · 출력 4 | |
| 처리 | 처리 · 조회 2 | 출하 확정 · 생산순서 변경 |
| 설정 | 저장 · 조회 2 | |
| 외부 연계(SSO) | 진입(토큰 발급 · POST 폼) · 조회 2 | |

ID `F-<L1>-<nnn>`(예 `F-WO-011` = WO-010 의 첫 기능). 각 줄: ID · 대메뉴 · 화면 ID · 기능명 · 유형 · 쓰는 테이블 · 권한(W 부서) · API · 담당 · 계약. 유형이 `등록` 인데 정본 logic 이 수정을 막으면(예: 조정 이력 불변) 수정 기능을 전개하지 않고 그 이유를 계약에 적는다. 총 170줄 안팎 — FP 산정서 원본이 오면 교체.

### 3.3 권한
- `sys_role` = 부서 8 행. `sys_permission(role_code, screen_id, level)` level ∈ {W, R} — **260행 시드 데이터**(ia.json + overrides 에서 생성 · `tools/gen_permissions.py`). 행이 없으면 없음(메뉴 숨김 · 403).
- `rbac.require_screen("WO-010")` = R 이상, `rbac.require_fn("F-WO-011")` = 쓰기 기능이면 W. SYS-020 역할·권한 화면이 행을 바꾸면 `invalidate()`.
- 세션은 요청마다 DB 에서 사용자 상태 · 부서를 읽는다(유지). 비활성 사용자는 다음 요청부터 401 이고 SSO 토큰도 발급되지 않는다.
- 데이터 질의의 수금 뷰 접근은 영업 · 회계 · 전산 관리자 · 경영진만(정본) — 권한 표가 아니라 `dataquery` 의 뷰 허용 목록에 부서 조건으로 둔다.

## 4. 데이터

### 4.1 테이블 (약 37 + SYS 8)

| 영역 | 테이블 | 비고 |
|---|---|---|
| BAS | `item` `customer` `warehouse` `location` | 품목 코드 중복 금지 · 중지 품목은 입고 · 출하 지시에서 못 고름 · 재고 남은 위치 삭제 불가 |
| STD | `spec_sheet` `standard` `plate` `plate_usage` `artwork` `sample_sheet` `exception_item` | 표준관리 · 예외제품의 적용 규칙은 `차단`(FINE_MES 확인) |
| WO | `production_request` `work_order` `work_sequence` | 의뢰번호가 수주 키. 공정상태(WO-040)는 뷰 `v_work_order_status` |
| MAT | `material_receipt` `material_lot` `material_issue` `material_issue_line` `product_receipt` `product_lot` | 입고 LOT 자동 채번 · 검사 대기 LOT 는 불출 불가 · 제품 입고는 일보 완료 수량 기본값 |
| PRD · INS | `production_daily` `inspection_daily` | 지시 × 일자 × 설비. 로스율 산식 `차단` |
| QC | `incoming_inspection` `product_inspection` | 재판정은 새 행, 이전 판정 함께 표시. 합격 → 가용, 불합격 → 보류 |
| INV | `lot_stock` `stock_move` `stock_adjust` | 상태 가용/검사대기/보류 · 가용 = 현재고 − 출하 할당 · 분할 시 `-01` 순번 · 조정 이력 불변 |
| SHP | `shipment_order` `shipment_line` `shipment_adjust` | LOT 할당은 가용 안에서만 · 미판정/불합격 LOT 있으면 확정 차단 · 확정 후 정정은 반품·정정 행 |
| COL | `erp_upload_batch` `erp_upload_row` `erp_customer_map` `erp_column_map` | 같은 기준 기간 재업로드 = 새 회차로 교체(이전 회차 보존) · 오류 행 반영 제외 · MES 는 수금을 고치지 않음 |
| RPT | `data_query_log` | 대시보드는 테이블 없음(D-505) |
| DOC | `doc_account_map` `sso_token` | 토큰 jti · 만료 · 사용 여부 |
| HOME | `notification` `notification_setting` | 할 일은 저장하지 않고 질의로 센다 |
| SYS | `sys_role` `sys_user` `sys_permission` `sys_common_code` `sys_access_log` `sys_change_log` `sys_number_rule` `sys_number_seq` `sys_ai_call_log` | 공통코드: 설비 · 불량유형 · 수금수단 |

### 4.2 추적의 척추 (완료 기준)
`material_lot` →(`material_issue_line.work_order_id`)→ `work_order` →(`product_receipt.work_order_id`)→ `product_lot` →(`shipment_line.product_lot_id`)→ `shipment_order`.
LOT-020 역방향: 출하 번호 또는 제품 LOT 하나에서 원자재 LOT 목록까지. LOT-010 정방향: 원자재 LOT 에서 불출 → 지시 → 제품 입고 → 출하까지. 분할 LOT 는 `stock_move` 의 원 LOT 로 잇는다. 둘 다 **읽기만** 하는 `trace.py`.

### 4.3 쓰기 경계
- 화면은 자기 대메뉴의 테이블에만 쓴다. 예외는 계약에 적는다: 입고검사(QC-010)·제품검사(QC-020)가 `lot_stock.status` 를 바꾸는 것, 출하 지시가 `lot_stock` 의 할당량을 잡는 것, 쓰기 트랜잭션이 `notification` 을 넣는 것.
- TRK · LOT · PRP · RPT 대시보드 · 통합 조회는 **어떤 업무 테이블에도 쓰지 않는다**(데이터 질의는 `data_query_log` · `sys_ai_call_log` 만).
- 수금 데이터는 업로드 회차 교체로만 바뀐다.

### 4.4 채번 — `가설`
의뢰 · 지시 · 입고 LOT · 제품 LOT · 출하 · 업로드 회차 · 질의 로그 7종. 형식은 정본에 없다 → `sys_number_rule` 데이터 + `numbering.next(kind)` 한 곳. 접두 · 자릿수는 `(예시)` 로 시드하고 D-5xx `가설`.

## 5. 공용 모듈 (interfaces.md 에 시그니처)

| 모듈 | 역할 |
|---|---|
| `rbac` `templating` `nav` `conn` `audit` `http` `numbering` `settings` | 유지. 권한 키만 화면 단위로. `templating` 의 채널 분기 제거 |
| `trace.py` | 정·역방향 LOT 추적 조회(읽기만) — 옛 `lineage` 대체 |
| `notify.py` | 알림 9종. `emit(event, to_dept, link, key)` 를 **쓰기 트랜잭션 안**에서 부른다. 부서 단위 수신, 한 사람이 처리하면 같은 부서에 "처리됨". 알림을 눌러 연 화면에서 처리하면 닫힘. 납기 D-3 미출하는 `python -m lcomfine.jobs due-check` 배치. 메일·메신저는 `차단` |
| `erp_upload.py` | openpyxl 로 엑셀 읽기 → 열 매핑(처음 한 번 저장, 다음부터 자동) → 검증(필수 열 · 숫자/날짜 형식 · 거래처 코드 매핑) → 회차 반영/교체. 열 구성은 `차단`(매핑 화면이 흡수) |
| `dashboard.py` | 대시보드 8 의 집계 SQL 한 곳(읽기만). 기간 · 거래처 필터. 수금 대시보드는 최근 업로드 기준일을 함께 낸다. 납기 준수율은 출하 지시에 의뢰번호가 있을 때만 |
| `ai.py` | OpenAI 어댑터(httpx · Chat Completions). 키 없음/실패는 예외로 올리고 화면이 보여 준다(조용한 실패 금지). 호출마다 `sys_ai_call_log` |
| `dataquery.py` | 질문 → SQL(ai) → 검증: **SELECT 한 문장 · 허용 뷰(`v_dq_*`)만 · 부서별 뷰 제한 · 읽기 전용 DB 역할 · `statement_timeout` · 행 수 상한** → 실행 → `data_query_log` |
| `sso.py` | HMAC 서명 일회용 토큰(유효 60초 · jti 1회 · 사용자 활성 + 매핑 필수) → 새 창 자동 POST 폼. `LCOMFINE_DOC_SSO_URL` 없으면 `미확정 (D-nn)` 안내 화면. SAML/OIDC 는 `차단`. 호출 로그(사용자 · 시각 · 성공 여부) |
| `stats.py` | PRP 생산 보고서 · TRK 납기 · 통합 조회 집계 SQL(읽기만) |

이름을 만드는 곳은 `numbering` 뿐, 알림을 쓰는 곳은 `notify` 뿐, 집계 SQL 은 `dashboard` · `stats` 뿐, AI 를 부르는 곳은 `ai` 뿐.

## 6. 화면 디자인

- 정본의 시각 언어를 앱에 쓴다: IBM Plex Sans KR(+ 시스템 글꼴 대체) · 액센트 `--cyan #0b7a8a` · 라이트/다크 토큰(`:root` · `prefers-color-scheme` · `data-theme`) · 표 중심 밀도 · 상태 칩. `static/style.css` 를 새로 쓰고 `app.js` 는 폼 보조(확인 대화 · 포커스)만.
- 메인 `/` = **HOME-010 내 할 일**: 상단 업무 흐름 띠(FLOW 7단계 · 권한 있는 단계만 링크) → 부서별 대기 카드(건수 + 조건이 걸린 처리 화면 링크) → 납기 임박·지연 → 오늘 처리한 건.
- `/ia` 참고 화면: 계약(nav · 권한 표 · 기능 목록)에서 그린 사이트맵 · 권한 매트릭스. 정본 글은 옮기지 않고 수는 DB · 계약에서 센다.
- 대시보드 차트는 인라인 SVG(외부 차트 라이브러리 없음), 색은 토큰에서. 숫자는 표로도 함께 보여 준다.
- 모든 조회 0건 `미수집`, 미확정 값 `미확정 (D-nn)`, 시드 `(예시)`. 입력 오류는 422 로 사람이 읽는 문장.

## 7. 수용 게이트 (goal.md §2 에 옮긴다 · 24개)

| 구분 | 게이트 |
|---|---|
| 구조 | G-01 정본(ia.json + overrides) ↔ nav.py 대메뉴 17 · 화면 67 · 묶음 · 순서 · 이름 글자 단위 일치 / G-02 기능 목록 ↔ 라우트 ↔ 테스트 표식 1:1 / G-03 화면 67 + 공통 HTTP 200 · placeholder 0 / G-04 스키마 계약 ↔ 실제 DB |
| 흐름 | G-05 쓰기 경계(라우터별 쓰기 테이블) / G-06 **E2E: 의뢰 → 지시 → 입고 → 입고검사 → 불출 → 일보 → 제품 입고 → 판정 → 출하 지시 → 확정 1건을 화면 조작(HTTP)만으로** / G-07 **출하 1건에서 원자재 LOT 까지 역추적** / G-08 정방향 추적 / G-09 검사 대기·불합격 LOT 는 불출·출하 확정 차단 / G-10 가용 = 현재고 − 할당 재계산 일치 / G-11 알림 9종이 전부 발생하고 처리하면 닫힘 |
| 수금 | G-12 같은 기간 재업로드 = 회차 교체 · 이전 회차 보존 / G-13 오류 행 제외 · 미매핑 → 매핑 후 재반영 / G-14 출하 대비 수금이 월·거래처 단위로 맞음 |
| 대시보드·AI | G-15 대시보드 8 수치 = 독립 재계산 / G-16 데이터 질의: 비허용 SQL(쓰기 · 허용 밖 뷰 · 다중 문장) 거부 · 부서 제한 · 로그 / G-17 키 없을 때 명시적 오류(조용한 실패 없음) |
| SSO | G-18 토큰 재사용 · 만료 · 비활성 · 미매핑 거부 · 로그 |
| 보안·운영 | G-19 권한 없는 쓰기 403 전수(260 칸 밖) · 조회 부서의 쓰기 403 / G-20 세션 상태 요청마다 DB / G-21 비밀 코드 · 문서에 없음 · 시드 멱등 / G-22 변경 감사 로그 / G-23 백업·복구 대조 / G-24 Docker 기동 · `/health` |

옛 테스트 1,633 건은 도메인과 함께 삭제한다 — 정본이 바뀐 것이며 게이트를 낮추는 것이 아니다(D-503). 새 테스트는 기능마다 1 건 이상, `@pytest.mark.fn("F-WO-011")`.

## 8. 진행 — 4 웨이브 (D-506)

goal.md 루프 프로토콜 유지: 아키텍트(오케스트레이터) · 개발 3 · QA 3 서브에이전트 · 한 파일 한 사람 · 보고를 믿지 않고 게이트 직접 재실행 · 로컬 커밋만 · 밖으로 내보내지 않음.

| 웨이브 | 범위 | 분담 |
|---|---|---|
| **W1 핵심 흐름** | Phase 0: 정본 추출 · 계약 7종 · 스키마 · 시드(부서 8 · 권한 260 · 계정 8 · 공통코드) · 게이트 도구 · placeholder 67 · 새 CSS · 로그인/레이아웃. 이어 BAS · STD · WO · MAT · PRD · INS · QC · INV · SHP · LOT · PRP · TRK · HOME · SYS | 개발1 HOME · BAS · STD · WO · SYS · TRK(+ `numbering` `notify`) / 개발2 MAT · PRD · INS · QC · INV · LOT(+ `trace`) / 개발3 SHP · PRP(+ `stats`) |
| **W2 수금** | COL 7 · `erp_upload` · 통합 조회의 수금 칸 | 개발3 |
| **W3 대시보드** | RPT 9 · `dashboard` · `ai` · `dataquery` · 허용 뷰 | 개발3(대시보드 · 질의) + 개발1(공통코드·로그 화면 보강) |
| **W4 문서 SSO** | DOC 2 · `sso` · 사용자 비활성 연동 · 로그 | 개발1 |
| 매 웨이브 끝 | QA1 기능·계약 / QA2 흐름·데이터 / QA3 보안·E2E → 결함 수정 → `make gate-full` PASS → 커밋 | |

종료: 게이트 전건 PASS(`차단` 은 D-번호 필수) · QA 3종 치명 0 · 연속 2회전 변화 없음. 마지막에 `progress.md` 최종 보고와 사람이 정할 `차단` 목록, VPS 재배포 절차.

## 9. 사람이 정해야 할 것 (`차단` 으로 올릴 목록)

ERP 수금현황 엑셀의 열 구성(매출액 · 잔액 열 존재 여부 포함) · 문서관리 시스템의 SSO 주소와 방식(SAML/OIDC/서명 토큰) · 사번 동일 여부(매핑 생략 가능?) · 알림 메일·메신저 · FINE_MES 표준관리 · 예외제품 적용 규칙 · 생산/검사 로스율 산식 · 주문 흐름 병목 기준일 · 채번 형식 7종 · 알림 배치 시각.

## 10. 범위 밖

설비 실시간 수집 · 비전 검사 · 매출전표/세금계산서/발주/근태/품의/원가(FINE_MES · ERP 잔류) · 문서 저장(별도 시스템) · AI 해설 리포트(D-505) · POP/모바일/현황판 채널.
