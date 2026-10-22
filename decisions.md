# 결정 대장 (v2 · 2026-10-21 정본 기준)

> **에이전트는 이 파일을 읽고, 여기 없는 것을 마음대로 정하지 않는다.**
> 정본(`docs/엘컴화인_MES_기획서_2026-10-21.html`)이 비워 둔 것을 정해야 하면 추측으로 코드에 박지 말고 여기에 `가설` 로 올리고 `contracts/` 를 고친 뒤 쓴다.
> 사람 확인 없이는 못 가는 것은 `차단` 으로 올리고 화면에 `미확정 (D-nn)` 을 렌더링한 뒤 다음 일로 넘어간다.
> 사람이 정하면 상태를 `확정` 으로 바꾸고 근거를 적는다. 확정된 항목은 되돌리지 않는다.
> 옛 대장(설계도 기준 D-01~D-419)은 `decisions-v1.md` 에 그대로 있다. **v2 에서는 효력이 없다** — 옛 결정이 다시 필요하면 새 번호로 옮겨 적는다.

상태: `확정`(사람이 정함) / `가설`(잠정 채택, 현업 확인 대기) / `차단`(사람이 정할 때까지 진행 불가 — 화면은 `미확정 (D-nn)`)
번호 대역 — 사람 결정 · 아키텍트 `D-501~D-599` · 개발1 `D-6nn` · 개발2 `D-7nn` · 개발3 `D-8nn` · QA `D-9nn`
제목 줄 형식은 `## D-nnn 제목 · 상태: 가설` 로 고정한다 (`tools/gate.py` 가 `상태: 차단` 을 읽어 게이트 판정에 반영한다).

---

## 사람이 정한 것 (경영진 미팅 뒤 · 2026-10-21 · 스펙 §0)

## D-501 새 기획서가 정본이다 · 상태: 확정
- 정본 = `docs/엘컴화인_MES_기획서_2026-10-21.html`(「엘컴화인 MES 통합본 — 화면 구조(IA) · 부서 간 업무 변화 · 2026-10-21」). 읽기 전용 — 고치거나 옮기지 않는다.
- 옛 설계도(`엘컴화인_MES_설계도 복사본.html`)는 `docs/archive/` 로 옮겨 참고만 한다. 수 · 메뉴 · 권한의 기대값은 전부 새 정본에서 읽는다.
- 기대값은 기계로 읽는다: `tools/design_doc.py` → `contracts/ia.json`, 사람 결정에 따른 편차는 `contracts/ia-overrides.json`(D-번호와 함께). **게이트의 기대값 = ia.json + ia-overrides.json.** 앱은 둘 다 읽지 않는다.
- 정본 기본 상태(개정 12 기준안)를 그대로 쓴다: 공정 메뉴 21 은 FINE_MES 에서 새 MES 로 이관, 수금리포트 · 대시보드 · 문서관리 SSO · 내 업무 · 통합 조회 전부 포함.

## D-502 Job-Lot-Roll 롤 계보를 버린다 · 상태: 확정
- `roll` · `roll_genealogy` · splice · 슬리팅 · 조색 · 아니록스 · 판사양은 v2 에 없다. 추적 단위는 정본대로 **LOT** 다(스펙 §4.2 추적의 척추).

## D-503 골격만 남기고 도메인은 새로 쓴다 · 상태: 확정
- 남기는 것: `rbac` · `templating` · `nav` · `conn` · `audit` · `http` · `numbering` · `settings` · 게이트 도구 · Docker · 테스트 하네스.
- 새로 쓰는 것: 스키마 · 라우터 · 템플릿 · 시드 · 테스트. 같은 저장소이고 옛 코드는 git 이력으로 남는다.
- 옛 테스트 1,633 건은 도메인과 함께 지운다 — 정본이 바뀐 것이며 게이트를 낮추는 것이 아니다.

## D-504 데이터 질의의 모델은 OpenAI · 상태: 확정
- RPT-130 데이터 질의만 AI 를 쓴다. 키 `LCOMFINE_OPENAI_API_KEY`, 모델 `LCOMFINE_OPENAI_MODEL`(기본 `gpt-4.1`) — 값은 `.env` 에만. 코드 · 문서에 값을 적지 않는다(G-21).
- 부르는 곳은 `app/ai.py` 뿐. 키가 없거나 호출이 실패하면 예외로 올리고 화면이 그 사실을 보여 준다(G-17).

## D-505 「AI 리포트」를 「대시보드」로 바꾼다 · 상태: 확정
- RPT-090 리포트 생성·스케줄 · RPT-100 초안 검토·확정 · RPT-110 리포트 이력 · RPT-120 리포트 양식 관리를 없앤다(화면 71 → **67**).
- RPT-010~080 리포트 8개는 화면을 열 때 **실시간 SQL 집계**로 그리는 대시보드다. 캐시 테이블 · 초안 · AI 해설은 없다. 전 부서가 쓴다(권한 칸은 정본 그대로).
- 대메뉴 코드 `RPT` 와 화면 ID 는 정본 추적을 위해 유지하고 이름만 「대시보드」. 편차는 `contracts/ia-overrides.json` 에 있다.

## D-506 4 웨이브를 멈추지 않고 진행한다 · 상태: 확정
- W1 핵심 흐름 → W2 수금 → W3 대시보드 → W4 문서 SSO. 각 웨이브 끝에 QA → 결함 수정 → `make gate-full` PASS → 로컬 커밋. 사람을 기다리며 멈추지 않는다(`차단` 은 D-번호를 달고 넘어간다).

---

## 아키텍트 가설 (Phase 0 · 2026-10-21)

## D-507 화면 경로 slug · 상태: 가설
- 정본에 경로가 없다. 경로는 `/<대메뉴 코드 소문자>/<영문 slug>`, `HOME-010` 은 `/`. 원본은 `src/lcomfine/app/nav.py`, 렌더본은 `contracts/screen-map.md`. 코드에서는 `nav.path_of("WO-010")` 로만 얻는다.

| 코드 | slug (화면 순) |
|---|---|
| HOME | `` (=`/`) · `notifications` · `notification-settings` |
| BAS | `items` · `customers` · `warehouses` |
| STD | `spec-sheets` · `standards` · `plates` · `artworks` · `sample-sheets` · `exception-items` |
| WO | `requests` · `orders` · `sequence` · `status` |
| MAT | `receipts` · `issues` · `product-receipts` · `history` |
| PRD | `daily` · `daily/print` · `status` · `loss-rate` |
| INS | `daily` · `daily/print` · `status` · `loss-rate` |
| QC | `incoming` · `product` · `history` |
| INV | `stock` · `moves` · `adjustments` |
| SHP | `orders` · `confirm` · `history` |
| COL | `uploads` · `upload-history` · `customer-map` · `collections` · `receivables` · `aging` · `shipment-vs-collection` |
| TRK | `orders` · `due` · `customers` |
| LOT | `forward` · `backward` |
| PRP | `utilization` · `machines` · `completion` |
| RPT | `orders` · `production` · `quality` · `inventory` · `shipment` · `collection` · `order-flow` · `summary` · `query`(RPT-130) |
| DOC | `go` · `account-map` |
| SYS | `users` · `roles` · `codes` · `logs` |

- 공통 화면(`nav.COMMON`): 로그인 `/login` · 오류 `/error`. 참고 화면 `/ia`(계약에서 그린 사이트맵 · 권한 매트릭스)는 화면 67 에 세지 않는다. 바뀌면 고칠 곳: `nav.py` 한 곳.

## D-508 기능 목록 전개 규칙 · 상태: 가설
- 정본은 화면 67 과 그 유형만 준다. 기능은 화면 유형에서 전개하고, 정본의 L3 · logic 문장을 각 기능의 계약 문장으로 옮긴다(스펙 §3.2).

| 유형 | 기능 |
|---|---|
| 조회 · 리포트 · 출력 | 조회 1 |
| 등록 | 등록 · 수정 · 조회 3 |
| 목록·등록 | 등록 · 수정 · 삭제(참조가 있으면 사용 중지) · 조회 4 |
| 등록·출력 | 등록 · 수정 · 조회 · 출력 4 |
| 처리 | 처리 · 조회 2 |
| 설정 | 저장 · 조회 2 |
| 외부 연계(SSO) | 진입(토큰 발급 · POST 폼) · 조회 2 |

- ID 는 `F-<L1>-<화면 두 자리><순번>` — WO-010 의 첫 기능 `F-WO-011`, RPT-130 의 첫 기능 `F-RPT-131`.
- 정본 logic 이 수정을 막는 화면(예: INV-030 「조정 이력은 수정·삭제하지 않는다」)은 수정 기능을 전개하지 않고 그 이유를 계약에 적는다.
- 각 줄: ID · 대메뉴 · 화면 ID · 기능명 · 유형 · 쓰는 테이블 · 권한(W 부서) · API · 담당 · 계약. 총 **136줄** — 규칙 A 가 내는 수 133(「수정 없음」 INV-030 · COL-010 반영) · 예외 3(「유형 예외」: RPT-130 질의 실행 · SHP-020 반품·정정 등록 · HOME-020 알림 처리). 정본 칸에 W 가 없는 화면의 쓰기 기능 3(F-DOC-011 · F-RPT-132 · F-HOME-022)은 권한 칸 `R 이상(권한 예외)`. FP 산정서 원본이 오면 교체한다.

## D-509 채번 7종의 형식 · 상태: 가설
- 정본에 형식이 없다 — 현업 채번 규칙은 사람 확인 대기(스펙 §9). 규칙은 코드가 아니라 데이터 `sys_number_rule` 7행, 번호를 만드는 곳은 `numbering.next(kind, cur)` 한 곳.

| kind | 대상 | 형식 `(예시)` |
|---|---|---|
| `REQ` | 생산의뢰 번호(수주 키) | `REQ-YYMM-nnnn` |
| `WO` | 생산지시 번호 | `WO-YYMM-nnnn` |
| `MLOT` | 원자재 입고 LOT | `MLOT-YYMM-nnnn` |
| `PLOT` | 제품 LOT | `PLOT-YYMM-nnnn` |
| `SHP` | 출하 번호 | `SHP-YYMM-nnnn` |
| `ERP` | ERP 업로드 회차 | `ERP-YYMM-nnnn` |
| `DQ` | 데이터 질의 로그 | `DQ-YYMM-nnnn` |

- 접두 · 자릿수는 **예시일 뿐**이다. 화면 · 시드에 「이 회사 규칙」처럼 보이게 쓰지 않는다. 재고 이동으로 LOT 를 나누면 원 LOT 번호에 분할 순번 `-01` 을 붙인다(정본 INV-020) — 이것은 정본 문장이다.
- 바뀌면 고칠 곳: `sys_number_rule` 행만.

## D-510 재고 상태 4 · 상태: 가설
- 정본 INV-010 의 상태 필터는 가용 · 검사 대기 · 보류 셋이고, 「가용 수량 = 현재고 − 출하 지시 할당량」이다. 화면에 보이는 상태 칩은 **4**: `검사대기` · `가용` · `보류` · `할당`.
  - `lot_stock.status` ∈ {검사대기, 가용, 보류} — 입고 직후 검사대기, QC-010/020 합격 → 가용, 불합격 → 보류. 재판정은 새 행이며 상태를 다시 바꾼다.
  - `할당` 은 상태 칸이 아니라 수량이다: `lot_stock` 의 할당량(열 이름은 `contracts/db-schema.md`)을 SHP-010 출하 지시가 잡고, 가용 수량 = 현재고 − 할당. 가용 LOT 의 남은 가용 수량이 0 이면 칩을 `할당` 으로 보인다.
- 검사대기 · 보류 LOT 는 불출(MAT-020) · 출하 확정(SHP-020) 불가(G-09). 가용 재계산 일치는 G-10.

## D-511 알림 9종 — 키와 수신 부서 · 상태: 가설
- 아래 9종이 알림의 전부다. 구성(정본 HOME 배치 9 중 무엇을 빼고 무엇을 더했는가)은 D-523. 이벤트 표의 원본은 `app/notify.py` 의 `EVENTS`.

| 이벤트 키 | 정본 문장 | 수신 부서 |
|---|---|---|
| `request_created` | 의뢰 등록 → 생산부·디자인실 | PR · DS |
| `order_issued` | 지시 발행 → 생산부(불출 준비) | PR |
| `material_received` | 원자재 입고 → 생산부(입고검사) | PR |
| `product_received` | 제품 입고 → 생산부(제품검사) | PR |
| `judged` | 판정 완료 → 출하실·영업부 | SH · SL |
| `shipment_confirmed` | 출하 확정 → 영업부·회계부 | SL · AC |
| `erp_upload_error` | ERP 업로드 오류·미매핑 → 회계부 | AC |
| `due_d3_unshipped` | 납기 D-3 미출하 → 영업부·생산부 | SL · PR |
| `shipment_ordered` | 출하 지시 → 출하실 (정본 영업부 흐름 문장 · D-523) | SH |

- `notify.emit(cur, event, *, link, dedupe_key, text)` 는 **쓰기 트랜잭션 안**에서 부른다. 알림을 쓰는 곳은 `notify` 뿐.
- 알림은 수신 부서마다 1행이고 중복 방지 키는 D-522.
- 한 사람이 처리하면 같은 부서의 다른 사람에게 「처리됨」. 알림을 눌러 연 화면에서 처리하면 닫힌다(`notify.handle_by_link`). 알림이 가리키던 사실이 사라지면(ERP 회차 교체 · 재해석으로 오류 0) 누가 바꿨든 수신 부서와 무관하게 닫힌다(`notify.resolve_by_link` · Ruling 27 · DEF-QA1-006). 알림함에서 직접 처리하는 기능은 F-HOME-022 `POST /home/notifications/{id}/handle`(같은 부서 수신 행 전부 처리 · 권한 `R 이상(권한 예외)`). 납기 D-3 미출하는 배치 `uv run python -m lcomfine.jobs due-check`(시각은 D-520).
- 부서 기본 알림은 끌 수 없고 개인 추가 알림만 켜고 끈다(정본 HOME-030). 메일 · 메신저는 D-518.

## D-512 대시보드 8 의 집계 정의 · 상태: 가설
- 집계 SQL 은 `app/dashboard.py` 한 곳(읽기만). 공통 필터: 기간 · 거래처. 0건이면 `미수집`. 차트는 인라인 SVG 이고 숫자는 표로도 함께 보인다. 원천과 항목은 정본 RPT-010~080 의 L3 · logic 그대로:

| 화면 | 원천 | 수치 |
|---|---|---|
| RPT-010 수주 | `production_request` · `work_order` | 기간별 의뢰 건수·수량 · 거래처 상위 · 납기 분포 · 미착수(의뢰는 있고 지시가 없는 건) |
| RPT-020 생산 | `production_daily` · `work_order` · 공통코드 설비 | 지시 대비 생산 실적 · 생산 로스율(산식 D-519) · 가동률 · 기계별 |
| RPT-030 품질 | `inspection_daily` · `incoming_inspection` · `product_inspection` | 검사 로스율(산식 D-519) · 입고·제품 불합격 LOT · 재판정 |
| RPT-040 재고·창고 | `material_receipt` · `material_issue` · `lot_stock` · `stock_move` · `stock_adjust` | 입고·불출 · 재고 변동 상위 · 장기 체류 LOT · 실사 차이 |
| RPT-050 출하 | `shipment_order` · `shipment_line` | 출하 건수·수량 · 거래처별 · 납기 준수율(출하 지시에 생산의뢰 번호가 있을 때만) |
| RPT-060 수금 | `erp_upload_row`(반영 회차만) · `erp_customer_map` | 월별 수금액 · 출하 대비 수금 · 미수 연령 · 90일 초과 거래처 · **가장 최근 업로드 기준일 명시** |
| RPT-070 주문 흐름 | 생산의뢰 번호 키로 의뢰 → 지시 → 생산 완료 → 제품 입고 → 출하 | 단계 소요일 · 병목(기준일 D-520) · 거래처·월별 수금(건 단위로 짝짓지 않음) |
| RPT-080 경영 요약 | 위 7 의 핵심 수치 | 일일 = 창고·출하 중심, 주간·월간 = 수주·생산·수금 추가. 해설 문장은 없다(D-505) |

- 정답 대조: QA2 가 따로 짠 SQL 재계산과 일치해야 한다(G-15).

## D-513 데이터 질의 — 허용 뷰와 부서 제한 · 상태: 가설
- RPT-130 은 질문 → SQL(`ai`) → 검증 → 실행 → `data_query_log`. 검증은 `app/dataquery.py` 한 곳: **SELECT 한 문장 · 허용 뷰 `v_dq_*` 만 · 부서별 뷰 제한 · 읽기 전용 DB 역할 · `statement_timeout` · 행 수 상한**. 어긋나면 실행하지 않고 422 로 이유를 보인다(G-16).
- 허용 뷰는 8: `v_dq_orders` · `v_dq_work_orders` · `v_dq_stock` · `v_dq_shipments` · `v_dq_quality` · `v_dq_production_daily` · `v_dq_collections` · `v_dq_receivables` (`schema.sql`). 열은 `contracts/db-schema.md` §5.
- 수금 뷰 `v_dq_collections` · `v_dq_receivables` 는 영업부(SL) · 회계부(AC) · 전산 관리자(ADM) · 경영진(EX)만 — 정본 「영업·경리·관리자·경영진」. 권한 표가 아니라 `dataquery` 의 뷰 허용 목록에 부서 조건으로 둔다. 화면 자체(RPT-130)의 권한 칸은 정본 그대로.
- 모든 질의(거부 포함)는 `data_query_log`, 모든 AI 호출은 `sys_ai_call_log`. 데이터 질의는 그 둘 말고 어떤 테이블에도 쓰지 않는다.
- 질의 실행(F-RPT-132)은 쓰기 기능이지만 정본이 RPT-130 에 R 만 주므로 화면 R 이상이 실행한다(`R 이상(권한 예외)`).

## D-514 문서관리 SSO 토큰 규격 · 상태: 가설
- 정본: 서명된 일회용 토큰 · 유효 60초 · 한 번만 사용 · POST 로 넘긴다. 방식은 문서관리 시스템의 표준(SAML 2.0/OIDC)을 먼저 쓰고 안 되면 서명 토큰(D-517).
- 기본값: **HMAC-SHA256** 서명 토큰(비밀 `LCOMFINE_SSO_SECRET`), 담는 것 = 문서관리 계정 ID · 발급 시각 · 만료(60초) · `jti`. `sso_token` 에 jti · 만료 · 사용 여부를 남겨 재사용을 막는다. 새 창에서 자동 POST 폼으로 `LCOMFINE_DOC_SSO_URL` 에 보낸다 — 토큰이 주소창에 남지 않는다.
- 발급 거부: 사용자 비활성 · 계정 매핑 없음 → 「관리자에게 계정 연결을 요청하세요」. `LCOMFINE_DOC_SSO_URL` 이 없으면 `미확정 (D-517)` 안내 화면. 호출(사용자 · 시각 · 성공 여부)은 로그에 남는다(G-18).
- 모듈 `app/sso.py` 한 곳.
- SSO 진입(F-DOC-011)은 쓰기 기능(`sso_token` · 로그)이지만 정본이 DOC-010 에 R 만 주므로 화면 R 이상이 진입한다(`R 이상(권한 예외)`).

## D-515 재판정 뒤의 출하 처리 · 상태: 가설
- 정본: 「재판정 건은 이전 판정을 함께 보여 준다」(QC-030) · 「미판정·불합격 제품 LOT 는 출하 확정 불가」(QC-020) · 「확정 후 정정은 반품·정정 행」(SHP-020). 그 사이는 비어 있다.
- 기본값:
  1. 재판정은 `product_inspection` 의 **새 행**이다. LOT 의 판정 = 그 LOT 의 가장 최근 행.
  2. 출하 확정 전 재판정이 불합격이면 그 LOT 가 걸린 출하 지시는 확정할 수 없다(G-09). 할당은 풀지 않고 화면에 「재판정 불합격」을 보인다 — 할당 해제는 출하 지시 수정으로 사람이 한다.
  3. 출하 확정 후의 재판정은 이미 나간 출하를 바꾸지 않는다. 그 LOT 의 남은 재고 상태만 바꾸고, 나간 수량의 처리는 `shipment_adjust` 반품·정정 행으로 사람이 남긴다. 그 기능은 F-SHP-023 반품·정정 등록 `POST /shp/confirm/{id}/adjust`(출하실 · 전산 관리자). 구분·수량 규약은 가설(D-515) — 구분(반품 · 정정) · 수량 · 사유를 남기고 재고는 바꾸지 않는다(재고 반영은 미확정).
  4. 불합격 → 합격 재판정은 `보류` → `가용` 으로 되돌린다.


## D-521 G-04 의 기대값은 테이블 이름 집합이다 · 상태: 가설
- 판정: G-04 의 기대값은 **스펙 §4.1 표의 테이블 이름 집합**(현재 업무 39 + SYS 9 = 48)이지 수가 아니다. 스펙의 「약 37 + SYS 8」이나 「45」 같은 수로 판정하지 않는다. 뷰(`v_work_order_status` · `v_dq_*`)는 테이블 수에 세지 않고 따로 대조한다.
- 근거: 스펙 §4.1 머리의 수는 어림이고, 표에 적힌 이름을 세면 48 이다. 이름이 계약 · DB 와 맞는지가 G-04 의 뜻이다.
- 영향: 테이블을 더하거나 빼면 스펙 §4.1 표와 `contracts/db-schema.md` 를 같이 고친다. `tools/check_schema.py` 는 이름 집합으로 비교한다.

## D-522 `notification` 중복 방지 키 — (dedupe_key, to_role) 쌍으로 유일 · 상태: 가설
- 판정: 알림은 **수신 부서마다 1행**이다. `notification` 은 `(dedupe_key, to_role)` 쌍으로 유일하다 — 같은 키로 두 번 emit 해도 부서마다 1행만 남고, 두 부서에 가는 이벤트는 2행이다.
- 근거: 정본 HOME-020 「알림은 부서 단위로 가고, 한 사람이 처리하면 같은 부서의 다른 사람에게는 "처리됨"」.
- 영향: `schema.sql` 의 유일 제약 · `notify.emit` 반환값(만든 행 수) · G-11 의 「같은 키 재발생 무시」 판정.

## D-523 알림 9종 구성 — 정본 batch 9 − 리포트 초안(D-505) + 출하 지시 → 출하실 · 상태: 가설
- 판정: 알림은 9종을 유지한다. 구성 = 정본 HOME 배치 9줄 − 「리포트 초안 → 작성 부서」 + 「출하 지시 → 출하실」(`shipment_ordered` → SH).
- 근거: 「리포트 초안」은 D-505 로 리포트 초안 · 검토 화면(RPT-090~120)이 사라져 보낼 일이 없다. 「출하 지시 → 출하실」은 정본 영업부 흐름 문장(영업부가 출하 지시를 직접 등록하고 확정은 출하실)에서 왔다 — 배치 목록에는 없지만 정본에 있는 부서 간 넘김이다.
- 영향: 이 판정이 틀리면 `notify.EVENTS` 에서 `shipment_ordered` 를 지우고 G-11 의 기대값은 **8종**이 된다. 맞으면 SHP-010 출하 지시 등록 트랜잭션이 `notify.emit("shipment_ordered", …)` 를 부른다.

---

## D-524 앱 DB 역할은 superuser 가 아니다 · 상태: 가설
- QA3 DEF-QA3-003: 로컬 · Docker(`POSTGRES_USER`) 모두 앱이 superuser 로 붙어 불변 이력 트리거(`stock_adjust` · `shipment_adjust`)를 `session_replication_role` 로 우회할 수 있고, 개발2 · 개발3 테스트 정리가 그 우회에 기댄다.
- 가설: 운영의 앱 역할은 **테이블 소유자도 superuser 도 아닌** 별도 역할(`lcomfine_app` · 업무 테이블 SELECT/INSERT/UPDATE/DELETE · 불변 이력은 INSERT 만). 스키마 적용 · 시드 · 백업은 소유자 역할. 테스트 정리는 소유자 역할 또는 테스트 전용 DB 로 — W4(운영 · Docker G-24) 에서 `docker_init.py` · `compose` · 테스트 픽스처를 함께 바꾼다. W1~W3 은 로컬 개발 역할 그대로 둔다.
- 사람 확인: 운영 DB 역할 이름 · 비밀번호 보관 위치(`.env` 만).
- **W4 구현(아키텍트 · 2026-10-22)**: `src/lcomfine/db/roles.py` `roles.apply(cur, role, password)` — LOGIN · NOSUPERUSER · NOCREATEDB · NOCREATEROLE · NOBYPASSRLS · public 스키마 CREATE 없음 · 업무 표 SELECT/INSERT/UPDATE/DELETE · **불변 이력 · 감사 로그 6 표(`stock_adjust` · `shipment_adjust` · `sys_change_log` · `sys_access_log` · `sys_ai_call_log` · `data_query_log`)는 SELECT · INSERT 만**. `tools/docker_init.py` 가 시드 뒤 소유자 연결로 부른다. `docker-compose.yml` · `deploy/hostinger/docker-compose.yml` 의 `app` 은 `lcomfine_app` 으로, `seed`(스키마 · 시드 · 역할 · 백업 · 복구 검사)는 소유자 `lcomfine` 으로 붙는다. 비밀 `LCOMFINE_APP_DB_PASSWORD`(`make setup` 이 난수).
- 검증: `tests/test_arch_roles.py` — 한 트랜잭션 안에서 역할을 만들어 `set local role` 로 쓰기 · 읽기 · 불변 표 UPDATE/DELETE 거부 · `session_replication_role` 거부 · DDL 거부를 보고 되돌린다(클러스터에 역할이 남지 않음). 로컬 개발 역할(superuser)은 그대로 — 테스트 정리의 replica 우회는 로컬 소유자 역할에서만 돈다. 실기동 검증은 D-525(Docker).

## 사람이 정할 것 (`차단` · 스펙 §9)

## D-516 ERP 수금현황 엑셀의 열 구성 · 상태: 차단
- 모르는 것: 실제 열 이름 · 순서, **매출(청구)액 · 잔액 열이 있는가**(COL-050 거래처별 미수의 전제 — 정본도 「확인 필요」).
- 그동안: COL-010 열 매핑 화면이 흡수한다(처음 한 번 저장, 다음부터 자동 — `erp_column_map`). 매출액 · 잔액 열이 매핑되지 않으면 COL-050 · COL-060 은 `미확정 (D-516)`.
- 정해지면 바뀌는 것: `erp_upload.py` 의 필수 열 목록과 시드 매핑 한 벌.

## D-517 문서관리 SSO 주소 · 방식 · 사번 동일 여부 · 상태: 차단
- 모르는 것: SSO 진입 주소, 방식(SAML 2.0 / OIDC / 서명 토큰), MES 사번과 문서관리 계정 ID 가 같은가(같으면 DOC-020 매핑 없이 사번을 넘길 수 있다 — 정본 「설계 때 확정」).
- 그동안: D-514 서명 토큰. 주소(`LCOMFINE_DOC_SSO_URL`)가 없으면 DOC-010 은 `미확정 (D-517)`. 매핑은 필수로 둔다.

## D-518 알림 메일 · 메신저 · 상태: 차단
- 모르는 것: 메일 서버 · 메신저 종류와 연동 방식(정본 HOME-030 「확인 필요」).
- 그동안: 알림은 MES 안(알림함)만. 알림 설정의 메일 · 메신저 칸은 `미확정 (D-518)` 로 보이고 저장되지 않는다.

## D-519 표준관리 · 예외제품 적용 규칙 · 로스율 산식 · 상태: 차단
- 모르는 것: FINE_MES 표준관리(STD-020) · 예외제품관리(STD-060)가 지시 · 생산에 어떻게 적용되는가, 생산/검사 로스율(PRD-040 · INS-040) 산식.
- 그동안: STD-020 · STD-060 은 등록 · 조회만 하고 다른 화면에 적용하지 않는다. 로스율은 화면에 `미확정 (D-519)` 와 원 수량(지시 · 생산 · 양품 · 불량)을 함께 보인다.

## D-520 주문 흐름 병목 기준일 · 알림 배치 시각 · 상태: 차단
- 모르는 것: RPT-070 의 단계별 병목 기준일 수(정본 「설계 때 확정」), 납기 D-3 미출하 배치(`jobs due-check`)를 하루 언제 돌릴지.
- 그동안: 병목 칸은 `미확정 (D-520)` 이고 단계 소요일만 보인다. 배치는 수동 실행(`uv run python -m lcomfine.jobs due-check`)만 하고 스케줄을 걸지 않는다.

---

## D-525 G-24 실기동 — Docker 데몬이 꺼져 있어 잴 수 없다 · 상태: 차단
- 2026-10-21 실측: `docker info` → `failed to connect to the docker API at unix:///Users/gerardo92/.docker/run/docker.sock`. `docker compose config -q` 는 rc 0, Dockerfile COPY 원본 결함(DEF-QA3-001)은 고쳤다(정적 PASS).
- 사람이 할 것: Docker Desktop 을 켠 뒤 `docker compose up -d --build` → `curl -s localhost:8020/health`(로컬 앱이 8020 을 쓰고 있으면 먼저 내리거나 `LCOMFINE_HOST_PORT` 를 바꾼다). 200 이 나오면 `progress.md` G-24 를 실측으로 바꾼다. 그때까지 G-24 는 `미검증`(FAIL 로 센다).

## D-526 HOME-030 「개인 추가 알림」이 무엇인가 · 상태: 차단
- 정본 HOME-030 logic: 「부서 기본 알림은 끌 수 없고, 개인 추가 알림만 켜고 끈다」. 그런데 알림은 부서 단위(D-511 · 9종 · 수신 부서 고정)이고 Ruling 24 는 다른 부서 이벤트 구독을 범위 밖으로 정했다. 그러면 켜고 끌 「개인 추가 알림」이 남지 않는다 — 정본 문장과 D-511 이 서로 맞지 않는다(정본 결함 기록 · 고치지 않는다).
- 지금(W1): HOME-030 은 자기 부서가 받는 이벤트를 「부서 기본 · 끌 수 없음」으로 보여 주기만 하고, 다른 부서 이벤트 · 부서 기본 끄기 · 메일 · 메신저(D-518)는 저장하지 않는다(422 · 501). 화면에 `미확정 (D-526)` 을 적는다.
- 사람이 정할 것: ① 개인 추가 알림 = 자기 부서 수신 이벤트 중 **나에게만** 끄기(개인 뮤트) 인가 ② 다른 부서 이벤트를 개인이 더 받는 것인가 ③ 메일 · 메신저 수단 선택(D-518)만을 뜻하는가. 정해지면 F-HOME-031 계약 한 행과 `notify.unread` 의 필터만 바뀐다.

## 개발 · QA 결정 (웨이브마다 이 아래에 덧붙인다)

<!-- 개발1 D-6nn · 개발2 D-7nn · 개발3 D-8nn · QA D-9nn -->

## D-701 QC 재판정 경로의 키 · 분할 LOT 의 판정 · 상태: 가설
- 계약은 `POST /qc/incoming/{id}` · `POST /qc/product/{id}` 의 `{id}` 가 무엇인지 적지 않았다. **재판정할 LOT 의 id**(QC-010 `material_lot.id` · QC-020 `product_lot.id`)로 둔다 — 재판정은 LOT 의 새 차수 행이다(D-515).
- 분할 LOT(INV-020)은 자기 판정이 없으면 원 LOT 의 판정을 따른다: 판정은 그 LOT 과 자기 판정이 없는 분할 자식의 `lot_stock.status` 에 함께 적용하고, `trace` 의 현재 판정도 자기 → 원 LOT 순으로 가장 가까운 판정이다.
- 바뀌면 고칠 곳: `routers/qc.py` `_judge` · `trace._judgements`.

## D-702 「출하 후 불합격」 표시 기준 · 상태: 가설
- D-515 3 의 표시를 이렇게 판정한다: **확정된** 출하에 들어간 제품 LOT 의 현재 판정(가장 큰 seq)이 `불합격` 이고 그 판정 시각 > 출하 확정 시각. 그 뒤 다시 합격으로 재판정하면 표시는 사라진다(이력은 QC-030).
- 출하 · 할당 · 반품·정정은 건드리지 않는다. 표시는 `trace.backward/forward` 의 `rejected_after_shipment` 와 LOT-010/020 · QC-020 화면.

## D-703 입고 · 불출 수정과 취소의 범위 · 상태: 가설
- MAT-010 · MAT-030 수정: 수량을 고치거나 취소할 수 있는 LOT 은 **입고 그대로인 LOT**(불출 · 이동 · 분할 · 할당 · 조정 · 출하가 없는 LOT)뿐이다 — 아니면 422(재고 조정은 INV-030). 취소는 입고 행에 `canceled_at` 을 남기고 그 LOT 의 `lot_stock` 행을 지운다.
- MAT-020 수정: 불출일 · 비고 · **불출 전체 취소**(재고를 되돌리고 `stock_move` `불출 취소` 행)만 한다. LOT 을 바꾸려면 취소 뒤 다시 불출한다.
- INV-020 수정: `이동` 행만 고친다(옛 이동을 되돌리고 새 값으로 다시 옮긴다). 분할 · 불출 · 출하 행은 고치지 않는다.

## D-704 라벨 출력 · 엑셀 · 알림 링크 · 상태: 가설
- MAT-010 라벨 = 같은 화면의 `?label=<입고 id>`(읽기) — LOT 번호 글자만 찍는다. 라벨 · 바코드 규격은 미수집.
- MAT-040 엑셀 = 같은 조회의 `?format=csv`(UTF-8 BOM CSV — 엑셀이 연다). xlsx 생성 라이브러리는 들이지 않았다.
- 알림 링크(개발2 가 emit 하는 것): `material_received` → `/qc/incoming?receipt=<입고 id>`(그 입고의 LOT 이 모두 판정되면 닫힘) · `product_received` → `/qc/product?lot=<제품 LOT>`(판정하면 닫힘) · `judged` → `/shp/orders?lot=<제품 LOT>`(dedupe `judged:<LOT>:<seq>`). 불출 등록은 `/mat/issues?wo=<지시번호>` 와 `/mat/issues` 링크를 닫는다 — 개발1 의 `order_issued` 링크가 이 꼴이면 불출에서 닫힌다.

## D-801 PRP-010 월별 가동률 산식 · 상태: 가설 (개발3)
- 정본은 「월 단위 설비 가동률」만 주고 산식이 없다. 원천 열은 `production_daily.run_minutes`(가동 시간 · 「가동률 원천」) · `stop_minutes`(정지 시간)뿐이다.
- 기본값: **가동률(%) = Σ가동 분 ÷ (Σ가동 분 + Σ정지 분) × 100** (설비 × 월, 소수 1자리). 분모를 달력 시간 · 계획 시간으로 잡는 산식은 그 값의 원천이 없어 쓰지 않는다.
  가동 · 정지가 모두 비어 있으면(또는 합이 0) `미수집` — 0 % 로 지어내지 않는다. 화면에 산식 문장과 원 분 값을 함께 보인다.
- 바뀌면 고칠 곳: `app/stats.py` 의 `_rate` · `UTILIZATION_FORMULA` 한 곳(W3 대시보드 RPT-020 의 가동률도 같은 산식을 따른다).
- 아키텍트 판정: 가설 유지 · 화면에 「산식 가설 D-801」 표기 · 사람 확인 대상(최종 보고).

## D-601 HOME-010 — 전산 관리자의 대기 카드 = 전 부서 카드 · 상태: 가설 (개발1)
- 정본 HOME-010 logic 은 부서 7(영업 · 생산 · 출하 · 디자인·개발 · 회계 · 전략·경영)의 카드만 적고 전산 관리자는 적지 않는다.
- 기본값: 전산 관리자는 모든 부서의 카드를 부서별로 묶어 본다(전 화면 R 이상 규칙과 같은 결). 카드 링크는 그 화면 칸이 있을 때만 건다.
- 「90일 초과 미수」(회계부)는 수금 집계 W2 전까지 `미수집`, 「확정 대기 리포트」(전략부·경영진)는 리포트 초안 화면이 없어(D-505) 건수 없이 안내만.
- 바뀌면 고칠 곳: `routers/home.py` 의 `CARDS` · `cards_for`.

## D-602 시안 이미지 형식 · 크기 · 상태: 가설 (개발1)
- 정본 STD-040 「시안 이미지 등록」 — 형식 · 크기 규정이 없다. 기본값: PNG · JPEG · GIF · WEBP 만(파일 머리 바이트까지 확인), 한 장 5MB 이하. 그 밖은 422 「이미지 형식 오류」.
- 이미지는 `artwork.image`(bytea) 에 두고 화면은 data URI 로 그린다(계약 밖 이미지 전용 경로를 만들지 않는다 — G-02 고아 ②).
- 바뀌면 고칠 곳: `routers/std.py` 의 `IMAGE_MAGIC` · `IMAGE_MAX_BYTES`.

## D-603 `request_created` 알림의 link = 생산의뢰서(WO-010) · 상태: 가설 (개발1)
- 수신 부서 PR · DS 중 DS 는 WO-020 칸이 없다(permission-matrix). 한 link 를 두 부서가 다 열 수 있게 `nav.path_of("WO-010") + "?q=<의뢰번호>"` 로 둔다.
- 지시서 작성(F-WO-021)이 같은 트랜잭션에서 `notify.handle_by_link(cur, 그 link, 생산부 사용자)` 로 생산부 행을 닫는다. 디자인·개발실 행은 알림함에서 처리한다.

## D-604 의뢰 상태 전이 · 「지시 대기」 판정 · 상태: 가설 (개발1)
- `확인대기`(등록) → `확정`(F-WO-012 · 단가·납기 확인) → `지시완료`(F-WO-021 지시서 작성이 바꾼다 — 사람이 고를 수 없다) / `취소`(F-WO-012).
- 취소 아닌 지시가 있는 의뢰는 상태 · 거래처 · 제품을 바꾸지 않는다(422). 지시서는 확인대기 · 확정 · 지시완료 의뢰에서 만들 수 있고 한 의뢰에 여럿 가능 · 취소 의뢰는 422.
- 「지시 대기 의뢰」(HOME 생산부 카드) = `status = '확정'`. 「불출 대기 지시」 = 발행·진행 지시 중 취소 안 된 불출 행이 없는 것. 공표는 progress-dev1 §1.
- 사용 중지 거래처도 의뢰에서 고를 수 없다(정본은 품목만 적었다 — 같은 뜻으로 넓혔다).

## D-605 BAS-030 창고·위치를 한 API 로 · 상태: 가설 (개발1)
- 기능 목록은 창고·위치 등록 · 수정 · 삭제를 각각 한 경로(`/bas/warehouses` …)로 준다. 폼 칸 `target` = `warehouse`(기본) | `location` 으로 대상을 고른다. 경로의 `{id}` 는 그 대상의 id.
- 창고 삭제: 재고(qty > 0)가 남은 위치가 있으면 422, 위치가 있으면 창고와 그 위치를 사용 중지, 없으면 삭제.

## D-606 SYS 보호 규칙 · 상태: 가설 (개발1)
- SYS-020: 전산 관리자 칸은 「없음」으로 바꿀 수 없다(goal §6 「전 화면 R 이상」) · 전산 관리자의 SYS-020 칸은 W 여야 한다(아니면 아무도 권한을 고칠 수 없다) — 어기면 422. 보낸 칸만 바꾼다(부분 저장).
- SYS-010: 자기 계정의 부서 · 상태 변경과 자기 비활성은 422(다른 관리자가 한다). 「비활성」 = `status = '중지'`(행은 지우지 않는다).
- SYS-030: 「저장」 한 기능이 등록(`id` 없음) · 수정(`id`) · 삭제(`action=delete` — 참조가 있으면 사용 중지)를 한다. 코드 그룹은 정본 3(설비 · 불량유형 · 수금수단)만. 참조 = 설비: 지시 · 생산일보 · 작업 순서 / 불량유형: 검사일보 defects 키 / 수금수단: ERP 행 parsed.method.

## D-607 TRK 단계 · 납기 구분 · 상태: 가설 (개발1)
- 단계 6 의 수량: 의뢰 수량 · 취소 아닌 지시 수량 합 · 생산일보 양품 합 · 검사일보 검사 수량 합 · 취소 아닌 제품 입고 합 · 확정 출하 수량 합(제품 LOT → 지시 → 의뢰). 지금 단계 = 수량이 있는 마지막 단계 · 남은 수량 = 의뢰 수량 − 확정 출하.
- 납기 구분: 완료(확정 출하 ≥ 의뢰 수량, 마지막 확정일 ≤ 납기) · 지연 완료(확정일 > 납기) · 지연(미완료 · 납기 지남) · D-3(0~3일) · D-7(4~7일, 필터 「D-7」 은 D-3 을 포함) · 여유.
- 조회 SQL 은 W1 동안 `routers/trk.py` 안에 있다 — `stats` 가 공표되면 옮긴다(progress-dev1 §3).
- 아키텍트 Ruling 26 (W2): 의뢰별 진행 · 단계 · 임박 · 지연 조회 SQL 은 라우터에 둔다(읽기만 · 집계가 아니라 행 조회). `stats` 는 수치 집계(준수율 · 수금 · 미수 연령)만. 계약 F-TRK-011 · 021 · 031 문장을 그에 맞게 고쳤다 — 더 옮기지 않는다.

## D-608 TRK · HOME 이 `stats` 공표를 붙이는 방식 (W2) · 상태: 가설 (개발1)
- 정본 TRK-020 은 「납기 준수율」 낱말만, TRK-030 은 「수금·미수 (ERP 업로드 기준일 표시)」, HOME-010 회계부는 「90일 초과 미수」 낱말만 준다. 수치는 전부 개발3 공표(`stats.due_compliance` · `customer_receivable` · `erp_asof` · `aging` — D-804 · D-803 · D-516)로 세고 화면은 그 반환을 그대로 적는다.
- **TRK-020 준수율 기간** = 조회 인자 `period`(`YYYY-MM` · 비면 이번 달). 화면의 D-3 · D-7 · 지연 표는 오늘 기준이고 준수율만 기간 기준이다(정본에 기간 낱말이 없다). `rate` None 은 `미수집` — 0 % 로 적지 않는다. 산식 문장(D-804 가설) 을 수치 옆에 보인다.
- **TRK-030** 미수 잔액 = `customer_receivable["receivable_amount"]`(Σ매출 − Σ수금 · D-803 · 기간 제한 없음) · 기준일 = `asof`(= `stats.erp_asof()`). `status` 가 `미수집` · `미확정 (D-516)` 이면 그 글자를 칸에 그대로 쓴다(수금 합은 `미확정` 이어도 수치).
- **HOME-010 회계부 「90일 초과 미수」** = `len(stats.aging(asof)["over90"])`(90일 초과 순액 > 0 인 거래처 수 · 기준일 = `erp_asof()`) · 반영 회차가 없으면 `미수집`(오늘 기준으로 빈 집계를 돌리지 않는다) · `undecided` 면 `미확정 (D-516)`. 링크 COL-060. `erp_upload_error` 알림의 미처리 건수는 **따로 카드를 두지 않고** 「업로드 오류 행」 카드의 note 에 적는다 — 오류 행 · 미매핑 거래처 카드가 같은 사실을 이미 센다.
- 라우터 `routers/trk.py` 에 남은 집계 SQL 은 의뢰별 진행 · 단계(D-607)만 — 개발3 이 그 함수를 공표하면 옮긴다(progress-dev1 §3-2).

## D-802 ERP 수금현황 업로드의 처리 규칙 (열 매핑 · 검증 · 회차 교체 · 재해석) · 상태: 가설 (개발3)
- 정본 COL-010 은 흐름(열 매핑 저장 → 검증 → 오류 행 제외 → 회차 교체 → MES 는 고치지 않음)만 주고 열 구성(D-516 차단)과 세부 규칙을 주지 않는다. 그동안 `app/erp_upload.py` 가 아래 기본값으로 흡수한다.
- **항목 7** = `db-schema.md` 의 `erp_upload_row.parsed` 키 그대로(`customer_code` 거래처코드 · `txn_date` 일자 · `sales_amount` 매출액 · `collected_amount` 수금액 · `balance_amount` 잔액 · `method` 수단 · `bill_due_date` 어음 만기). **열 단위 필수** = 거래처코드 · 일자 · (매출액 또는 수금액 중 하나 이상). 그 밖은 선택 — 매출액 · 잔액이 매핑되지 않으면 COL-050 · COL-060 · TRK-030 의 매출 · 미수 칸은 `미확정 (D-516)`(수금 합은 그대로).
- **읽기**: 첫 시트 · 1행 = 열 이름(중복 열 이름 · 빈 1행은 422) · 완전히 빈 줄은 세지 않는다 · 20MB 이하 · `.xlsx`(openpyxl) 만. 원문은 `raw` 에 글자로 보존(날짜 셀은 ISO).
- **값 형식**: 날짜 `YYYY-MM-DD` · `YYYY.MM.DD` · `YYYY/MM/DD` · `YYYYMMDD` · 엑셀 날짜 셀 / 금액 = 쉼표 · 공백 제거, `(1,000)` 은 음수, 빈 칸 = 값 없음, numeric(16,2) 범위. 행 단위 필수 = 거래처코드 · 일자. 어긋난 항목은 `error` 에 「항목: 사유」로 모두 적고(한 행에 여럿) `parsed` 에는 해석된 항목만 남긴다.
- **거래처 코드 미매핑 = 오류 행**(반영 제외 · `error` 머리 「거래처 코드 미매핑: 코드」). **미매핑 목록(COL-030)** = 반영 회차 행의 `parsed.customer_code` 중 사용 중(`use_yn='Y'`) 매핑이 없는 코드(교체 회차는 세지 않는다). 매핑을 등록 · 사용 재개하면 **반영 회차**의 그 코드 행만 지금 열 매핑 · 거래처 매핑으로 다시 해석한다(`remap` — 교체 회차는 이력이라 건드리지 않는다 · 회차 `error_count` 갱신). 사용 중지 · 삭제는 매핑만 바꾸고 행은 건드리지 않는다(계약 F-COL-033). 삭제의 「참조」 = 어느 회차든 `erp_upload_row.parsed.customer_code` 가 그 코드인 행.
- **회차 교체**: 같은 (기준 기간 시작, 끝)의 `반영` 회차가 있으면 새 회차 `round_no = 최대 + 1` 로 `반영`, 이전 회차는 `교체` + `replaced_by`(행 보존). 제약(`반영` 기간당 하나 · `교체 ⇔ replaced_by`)을 지키려고 새 회차를 `교체(→이전)` 로 넣고 → 이전을 `교체(→새)` 로 → 새 회차를 `반영` 으로 바꾸는 세 단계를 한 트랜잭션에서 한다. 기준 기간은 사람이 고른 날짜 둘(겹치는 기간은 서로 다른 회차로 올라온 그대로 센다 — `v_dq_collections` 의 「알려진 한계」와 같다).
- **알림** `erp_upload_error`(→ 회계부): 오류 · 미매핑 행이 1 이상인 회차마다 1행 · link `COL-020?batch=<회차 id>` · dedupe `erp_upload_error:<회차 번호>` · 문장에 오류 행 수와 미매핑 코드(최대 3개). 닫힘 = 그 기간을 다시 올려 교체되거나, 매핑 뒤 재해석으로 오류가 0 이 될 때(같은 쓰기 트랜잭션 · `handle_by_link`).
- **화면 동작**(F-COL-011 `POST /col/uploads` 하나 · 폼 `action`): `map` 열 매핑 저장(처음 한 번 · 다시 저장하면 바꾼다 · 빈 항목은 지운다) · `preview` 검증만(아무것도 쓰지 않는다 · 브라우저는 미리보기 화면, JSON 은 건수 · 행) · `apply`(기본) 반영. 매핑이 없거나 매핑된 열이 파일에 없으면 422 로 항목 이름을 짚고, 브라우저 미리보기는 파일의 열 이름을 보여 매핑부터 받는다.
- **시드**(`db/seed_dev3.py`): 열 매핑 한 벌 — 값은 정본 문장의 낱말(거래처코드 · 일자 · 매출액 · 수금액 · 잔액 · 수단 · 어음 만기) 그대로이고 이미 행이 있으면 건드리지 않는다. 수금 행 · 거래처 매핑은 시드하지 않는다(실데이터를 지어내지 않는다).
- COL-040 「엑셀」 = 같은 조회의 `?format=xlsx`(openpyxl · 화면과 같은 행). 수금수단 선택지 = 공통코드(그룹 수금수단) ∪ 반영 행에 나온 수단 글자.
- 바뀌면 고칠 곳: `erp_upload.FIELDS · REQUIRED_FIELDS · AMOUNT_FIELDS · parse_date · parse_amount · apply · remap` · `seed_dev3.COLUMN_MAP` · 템플릿 `col/uploads.html`.

## D-803 거래처별 미수 · 미수 연령의 산식 · 상태: 가설 (개발3)
- 정본 COL-050 은 「거래처별 매출·수금·미수 잔액 · ERP 수금현황에 매출(청구)액과 잔액 열이 있다는 가정(확인 필요)」, COL-060 은 「매출일 기준 경과일로 30 · 60 · 90 · 90 초과」만 준다. 건 단위 청구 ↔ 수금 대사 정보가 없다.
- **미수 잔액 = Σ매출액 − Σ수금액**(기준일 이하 `txn_date` · 반영 회차 · 사용 중 매핑 · `v_dq_receivables` 와 같은 정의). 기준일 기본값 = ERP 업로드 기준일(반영 회차의 마지막 기준 기간 끝 · `stats.erp_asof()`), 없으면 오늘. 미수 0 거래처는 기본 숨김(정본). **ERP 잔액 열**은 매핑되었을 때만 「기준일 이전 마지막 행(일자 → 회차 → 행 순)의 값」을 참고로 보인다 — 합하지 않는다.
- **미수 연령**: 구간 = 0~30 · 31~60 · 61~90 · 91일 이상(경과일 = 기준일 − 매출일 `txn_date`). **구간 금액 = 그 구간에 든 행들의 Σ매출 − Σ수금**(행 단위 순액 · FIFO 대사는 하지 않는다 · 수금만 있는 행이 많은 구간은 음수가 될 수 있다 — 화면에 산식을 적는다). 「90일 초과 거래처」 = 91일 이상 구간 순액 > 0.
- 매출액 열이 매핑되지 않으면 둘 다 `미확정 (D-516)`(수금 합만 보인다). 정해지면(열 구성 · 대사 방식) `stats.receivables · aging · AGING_BUCKETS` 한 곳만 고친다.

## D-804 납기 준수율 산식 (TRK-020 · `stats.due_compliance`) · 상태: 가설 (개발3)
- 정본 TRK-020 은 「납기 준수율」 낱말만 준다(산식 없음 · Ruling 23 으로 개발3 `stats` 가 공표).
- 모집단 = 납기(`production_request.due_date`)가 기간 안인 취소 아닌 생산의뢰. 의뢰마다(D-607 의 낱말과 같다): **완료** = 확정 출하 수량 합 ≥ 의뢰 수량 · 완료일 = 마지막 확정 출하일(`max(confirmed_at)::date`).
  `납기 안 완료`(완료일 ≤ 납기) · `지연 완료`(완료일 > 납기) · `지연`(미완료 · 납기 < 오늘) · `진행`(미완료 · 납기 ≥ 오늘).
- **준수율(%) = 납기 안 완료 ÷ (납기 안 완료 + 지연 완료 + 지연) × 100**, 소수 1자리. 진행 중은 분모에 넣지 않는다(아직 판정할 수 없다). 분모 0 이면 None = `미수집`(0 % 로 지어내지 않는다). 반품 · 정정은 빼지 않는다(D-515).
- 바뀌면 고칠 곳: `stats.due_compliance` · `DUE_COMPLIANCE_FORMULA` 한 곳.

## D-609 SYS-040 로그 탭의 전개 (W3 · 업로드·AI 호출 로그 · SSO) · 상태: 가설 (개발1)
- 정본 SYS-040 의 L3 는 「접속 로그 · 변경 감사 로그 · 업로드·AI 호출 로그」 셋이고 logic 은 ERP 업로드 회차·교체 · AI 호출 건수·실패·응답 시간 · 문서관리 SSO 호출의 사용자·시각·성공 여부를 「남긴다」 고만 적는다 — 어느 표를 어떻게 보이는지는 주지 않는다.
- 탭 6 = `access`(sys_access_log) · `change`(sys_change_log) · `erp`(erp_upload_batch — 회차 · 반영/교체 · 교체한 회차 번호 · 올린 사람 `created_by` · 읽은 행 · 오류·미매핑 행) · `ai`(sys_ai_call_log — 머리 건수 · 실패 · 평균 ms) · `dq`(data_query_log — 거부 포함 · 머리 건수 · 거부 · 평균 ms · D-513) · `sso`(sys_access_log 의 `log_type = 'SSO'` 행 — W4 F-DOC-011 이 남긴다 · D-514). 「업로드·AI 호출 로그」 L3 하나를 표 셋(erp · ai · dq)으로 펼쳤다.
- 열 = `contracts/db-schema.md` 의 컬럼만(새 열 · 캐시 없음). 화면이 표 밑에 원본 표 이름과 컬럼 이름을 적는다. `ok` 는 AI 탭 「성공/실패」, 질의 탭 「허용/거부」 글자로 보인다(값은 그대로 boolean).
- 필터는 탭 공통 — 사용자(`login` · AI · 질의는 `sys_user.login_id` 로 이어서, ERP 는 `created_by`) · 기간(`date_from` · `date_to` — 각 표의 일시 열) · 구분 `log_type` 하나(접속 구분 · 기능 ID · 회차 상태 · 호출 용도 · 허용/거부 · 성공/실패 — 선택지 밖은 422). 머리 수치는 **같은 필터**로 센다. 행 0 = `미수집`(0 으로 지어내지 않는다).
- 전부 읽기만(쓰기 0 · `sys_access_log` 의 조회 로그 한 행은 `templating.render` 가 남긴다). 바뀌면 고칠 곳: `routers/sys.py` `LOG_TABS` · `LOG_SOURCES` · `templates/sys/logs.html`.
- 공통코드 그룹 3(설비 · 불량유형 · 수금수단)의 기본 행은 공통 시드 `seed.py` `COMMON_CODES`(아키텍트) 가 넣는다. `seed_dev1.run()` 은 **빈 그룹에만** `(예시)` 코드 하나를 더해 다른 라우터의 선택지가 비지 않게 한다(멱등 · 반환 `code_group` · `code_added`).

## D-805 대시보드 8 의 집계 세부 정의 (`dashboard.py` · D-512 의 빈칸) · 상태: 가설 (개발3)
- 정본 RPT-010~080 은 항목 이름(L3)과 원천(logic)만 주고 모집단 · 날짜 기준 · 구간 · 상위 N 을 주지 않는다. D-512 표의 빈칸을 아래로 채운다 — QA2 의 G-15 독립 재계산은 이 정의로 센다.
- **공통**: `period` = `"YYYY-MM"` 또는 `(시작일, 종료일)`(양끝 포함). 구간(series) = 기간이 31일 이하면 **일**, 넘으면 **월**(`to_char` `YYYY-MM-DD` / `YYYY-MM`). 행이 없는 구간은 **None = 미수집**(0 으로 지어내지 않는다). KPI 도 0건이면 None. 상위 N = 10. 거래처 필터는 정본에 「기간·거래처」가 있는 RPT-010 · 050 · 060 · 070 에만 적용(020 · 030 · 040 은 기간만).
- **RPT-010 수주**: 모집단 = `request_date` 가 기간 안 · `status <> '취소'`. 미착수 = 취소 아닌 `work_order` 가 없는 의뢰. 납기 분포 = 납기 **월**별 건수. 거래처 상위 = 건수 → 수량 내림차순.
- **RPT-020 생산**: 모집단 = `production_daily.work_date` 가 기간 안. 지시 수량 = 일보가 있는 지시의 `work_order.qty` 합. 가동률 = D-801(Σ가동 ÷ (Σ가동 + Σ정지)). 기계별 = `stats.machine_stats`(같은 SQL). 로스율 = `미확정 (D-519)` 글자.
- **RPT-030 품질**: 검사일보(`work_date` 기간 안) 검사 · 불량 수량 · 불량유형(`defects` jsonb 키 합). 판정 = 입고검사 ∪ 제품검사의 `inspected_at` 기간 안 행. 불합격 LOT = 그 기간 `불합격` 판정이 있는 (종류, LOT) 수. 재판정 = `seq > 1` 행(이전 판정 `lag`). 검사 로스율 = `미확정 (D-519)`.
- **RPT-040 재고·창고**: 원자재 입고 = `material_receipt.received_on` 기간 안 · 취소 아님 · 분할 아닌(`parent_lot_id is null`) LOT 수량 합. 불출 = `material_issue.issued_on` 기간 안 · 취소 아님 · 행 수량 합. 제품 입고 = `product_receipt` 취소 아님. 재고 변동 상위 = `stock_move.moved_at` 기간 안 LOT 별 수량 합 상위 10. **장기 체류 LOT = 현재고 > 0 인 LOT 의 체류일(오늘 − LOT 생성일) 내림차순 상위 10 — 「장기」 기준일 수는 정본에 없어 정하지 않는다**(기간과 무관). 실사 차이 = `stock_adjust.adjusted_at` 기간 안 · 차이 합 = Σ(실사 − 장부).
- **RPT-050 출하**: 모집단 = `status='확정'` · `confirmed_at` 기간 안. 수량 = `shipment_line.qty` 합(반품·정정은 빼지 않는다 D-515). 납기 준수율 = `stats.due_compliance((f, t))`(D-804 · 납기가 기간 안인 의뢰 · 의뢰번호 있는 출하만) — 거래처 필터는 그 행을 거른 뒤 다시 센다.
- **RPT-060 수금**: `asof = stats.erp_asof()`(반영 회차의 마지막 기준 기간 끝)을 화면 머리와 KPI 에 명시 · 없으면 `미수집`. 월별 수금 · 출하 대비 수금 = `stats.shipment_vs_collection(첫 달, 끝 달, 거래처)`. 미수 연령 · 90일 초과 = `stats.aging(asof)`(D-803). 매출 열 미매핑 → `미확정 (D-516)`.
- **RPT-070 주문 흐름**: 모집단 = RPT-010 과 같다. 지시일 = 취소 아닌 지시의 첫 `created_at` · 생산 완료일 = 그 지시들의 마지막 일보 `work_date` · 제품 입고일 = 취소 아닌 제품 입고의 마지막 `received_on` · 출하일 = 확정 출하의 마지막 `confirmed_at`. 단계 5(의뢰→지시 · 지시→생산 완료 · 생산 완료→제품 입고 · 제품 입고→출하 · 의뢰→출하) 소요일 = 뒤 − 앞(하나라도 없으면 None). 병목 = `미확정 (D-520)` 글자. 수금 = 거래처 · 월(`stats.shipment_vs_collection`).
- **RPT-080 경영 요약**: 탭 일일 = 기준일 하루 · 주간 = 기준일까지 7일 · 월간 = 기준일의 달 1일~기준일. 일일 = RPT-040 + RPT-050 핵심 KPI, 주간·월간 = + RPT-010 · 020 · 060. 해설 문장 없음(D-505).
- 바뀌면 고칠 곳: `app/dashboard.py` 의 그 함수 한 곳(`TOP_N` · `DAY_BUCKET_MAX_DAYS` · `FLOW_STAGES`).

## D-806 데이터 질의의 검증 · 실행 · 응답 규칙 (`dataquery.py` · `ai.py` · D-513 의 세부) · 상태: 가설 (개발3)
- **검증(`validate_sql`) — 전부 거부(422 「허용되지 않는 질의 — 이유」 · 실행하지 않는다)**: 빈 질의 · NUL · 4000자 초과 / 끝의 세미콜론 하나는 떼고 그 밖의 세미콜론 = 다중 문장 / 주석(`--` `/*`) · 달러 따옴표 · 큰따옴표 식별자 · 닫히지 않은 문자열 / `SELECT` 로 시작하지 않는 문장 · **CTE(`with`) 금지**(뷰 이름 검사를 단순하게) · 쓰기 · DDL · 세션 명령(`set` `show` …) · `into` · `for`(update/share) · `lateral` / 카탈로그(`pg_*` · `information_schema` · `current_setting` · `version()` · `lo_*` …) / **함수는 허용 목록만**(집계 · 날짜 · 글자 · 수 함수 — `pg_sleep` · `md5` 등 거부) / `from` · `join` 뒤의 대상(쉼표 조인 · 별칭 포함)이 허용 뷰 `v_dq_*` 가 아니면 거부(스키마 한정 `public.x` 도) · 허용 뷰를 하나도 읽지 않는 질의도 거부. 문자열 리터럴 속 글자는 검사에서 비운다(`'%;--%'` 는 문장이 아니다).
- **부서 제한**: `v_dq_collections` · `v_dq_receivables` 는 SL · AC · ADM · EX 만(`dataquery.VIEWS` · D-513). 그 밖 부서의 수금 뷰 질의는 검증에서 거부(422 「이 부서가 질의할 수 없는 뷰」). AI 에 주는 스키마 설명도 그 부서의 허용 뷰만.
- **실행**: 별도 연결 · `set transaction read only` · `statement_timeout` 5초 · 행 상한 200(넘으면 잘림 표시) · 끝에 rollback. 읽기 전용 **DB 역할**은 D-524(W4) 가 정한다 — 그때까지는 트랜잭션 읽기 전용으로 막는다. DB 오류(없는 열 등)는 422 「실행 실패 — 사유」.
- **로그**: 질의마다 `data_query_log` 1행(거부 · 실패 · 키 없음 포함 · `numbering.next("DQ")`) · AI 호출마다 `sys_ai_call_log` 1행(키 없음도 실패로 1행 · 키 값은 적지 않는다). 둘 다 F-RPT-132 의 쓰기 트랜잭션 안. 실행 결과 행은 저장하지 않는다(row_count 만).
- **응답**: JSON(테스트)은 `http.saved` 200 + `{query_no, sql, columns, rows, row_count, truncated, ms}`. **브라우저는 같은 화면(RPT-130)을 200 으로 다시 그려 SQL 과 결과 표를 보인다**(결과 행을 저장하지 않아 303 뒤에 다시 보일 수 없다 — api-contract §2 「쓰기 성공 = 303」의 예외 · 변경 로그 `sys_change_log` 는 그대로 1행). 거부 · 실패는 422(브라우저는 303 + 알림 · `fields` 에 질의 번호 · SQL) — 사유는 최근 질의 목록에도 남는다.
- **AI**(`ai.complete(system, user, *, kind, cur=None, user_id=None)`): 계약 §9 시그니처에 `user_id`(로그의 사용자) 를 더했다 · `cur` 없으면 자체 연결로 로그. 키 없음 → `ai.NotConfigured("AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY")` · 호출 실패 → `ai.CallFailed(사유)` · 둘 다 로그 뒤 올린다. OpenAI 호출은 표준 라이브러리 `urllib`(Chat Completions · temperature 0 · 30초) — 새 패키지 없음. 테스트는 `ai.set_client(fake)`.
- 바뀌면 고칠 곳: `dataquery.ALLOWED_FUNCTIONS · FORBIDDEN · CATALOG_PATTERNS · MAX_ROWS · STATEMENT_TIMEOUT_MS · VIEWS` · `ai.OPENAI_URL · TIMEOUT_SECONDS` · 라우터 `run_query` 의 HTML 분기.

## D-610 문서관리 SSO 진입의 토큰 모양 · 응답 · 설정 없음 처리 (W4 · D-514 의 세부) · 상태: 가설 (개발1)
- 토큰 = `base64url(JSON 본문).base64url(HMAC-SHA256(LCOMFINE_SSO_SECRET, 본문 글자))` · 본문 `{"v":1, "sub": 문서관리 계정 ID, "iat", "exp"(= iat + 60), "jti"(uuid)}` (epoch 초). 토큰 글자는 DB · 로그 어디에도 저장하지 않는다 — `sso_token` 은 jti · 사용자 · 계정 ID · 발급 · 만료 · 사용 시각만.
- 1회 사용 = `update sso_token set used_at … where jti … and used_at is null and expires_at > … returning`(동시 사용도 하나만). `consume` 은 사용 처리 뒤 사용자 상태(`정상` 만) · 매핑(사용 중 · 같은 계정 ID)을 DB 에서 다시 본다 — 발급 뒤 비활성 · 매핑 사용 중지 · 계정 ID 변경이면 거부. 서명 비교 `hmac.compare_digest`. 비활성 = `sys_user.status <> '정상'`(잠금 · 중지).
- 거부 예외: 발급 `sso.NotMapped(사유)` · 검증 `sso.Invalid(사유)` · 비밀 없음 `sso.NotConfigured`(발급 · 검증 모두 안 함).
- `POST /doc/go` 응답: 브라우저 = **같은 화면 200** 의 POST 폼(`action = LCOMFINE_DOC_SSO_URL` · hidden `token` · 사람이 「문서관리 열기」를 누른다 — `static/app.js` 에 자동 제출 보조가 생기면 `form[data-auto-submit]` 으로 바로 넘어간다) — api-contract §2 「쓰기 성공 = 303」의 예외(토큰을 세션 · 주소에 담지 않으려면 303 뒤에 보일 수 없다 · F-RPT-132 와 같은 이유). JSON = 200 `{ok, message, jti, ttl_seconds, method, field}` — **토큰은 싣지 않는다**.
- 주소(`LCOMFINE_DOC_SSO_URL`) 또는 비밀이 없으면 발급하지 않고 **422** `「… 미확정 (D-517) — 토큰을 발급하지 않았습니다」`(fields `SSO 설정`) — 501 이 아닌 까닭: G-19 는 칸이 있는 부서의 쓰기 기능에 5xx 를 실패로 보고, RPT 의 「AI 키 없음 = 422」(D-806)와 같은 규칙. GET `/doc/go` 는 같은 사실을 `미확정 (D-517)` 안내 화면으로 보인다.
- 미매핑 · 비활성 거부 = 422 `「관리자에게 계정 연결을 요청하세요 — 사유」`(fields `계정 매핑`). 모든 호출(성공 · 거부 · 설정 없음)은 `sys_access_log` 구분 SSO 1행(`screen_id` DOC-010 · `function_id` F-DOC-011 · `result` · `detail` 사유 · 성공은 `target = sso_token:<jti>`) — 트랜잭션 밖 자체 연결이라 거부도 남는다. 성공은 `sys_change_log` 1행.
- 바뀌면 고칠 곳: `app/sso.py`(TTL_SECONDS · VERSION · 본문 키) · `routers/doc.py` `go` · `templates/doc/go_post.html`. 문서관리 시스템의 방식(SAML/OIDC)이 정해지면(D-517) 이 결정을 다시 쓴다.

## D-611 DOC-020 계정 매핑의 1:1 · 수정 · 삭제 · 엑셀 일괄 규칙 · 상태: 가설 (개발1)
- 1:1 은 **사용 중지 매핑도 자리를 차지한다** — `schema.sql` 의 유니크 2 개(`doc_account_map_user_uq` · `_account_uq`)가 `active` 와 무관하기 때문. 라우터가 먼저 사람 문장 422(`MES 사용자` 「이미 계정이 연결된 사용자입니다 (… · 사용 중지 매핑 — 그 행을 수정해 다시 쓰세요)」 · `문서관리 계정 ID` 「다른 사용자(…)에 이미 연결된 계정 ID 입니다」).
- 수정(F-DOC-022)은 계정 ID · 사용 여부만 — 매핑의 MES 사용자는 바꾸지 않는다(422 · 지우고 새로 등록).
- 삭제(F-DOC-023)의 「참조」= 그 사용자 · 계정 ID 로 발급한 `sso_token` 행(FK 가 아니라 이력). 있으면 `active = false`, 없으면 지운다.
- 엑셀 일괄 등록(F-DOC-021 · `file`): 첫 시트 · 1행 헤더 `사번`(= `sys_user.login_id`) · `문서관리 계정 ID`(열 순서 무관 · 다른 열 무시) · 메모리에서만 읽는다 · 5MB · 5,000 행. 행마다 검사(빈 칸 · 없는 사번 · 파일 안 중복 · DB 의 매핑과 1:1 · 200자) — **오류 행이 하나라도 있으면 아무것도 등록하지 않고** 422 에 행마다 사유(`fields` 이름 `n행`). 빈 줄은 세지 않는다.
- 미연결 사용자 목록 = 사용 중 매핑이 없는 모든 사용자(상태 무관 · 사용 중지 매핑이 있으면 그 계정 ID 를 비고에). 사번 동일 방식은 `미확정 (D-517)` 문장만 · 매핑 필수.
- 시드: 시드 계정 8 → `doc-<login_id> (예시)`(그 사용자 · 계정 ID 에 매핑이 없을 때만 · 멱등).
