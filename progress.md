# 진행 상태

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.

## 2026-10-09 메인 = IA 화면 (D-419 · 사람 요청 "메인 메뉴를 IA 를 보여 주는 화면으로, 설명도")

메인(`/`)이 설계도를 한 장으로 보여 준다: ① 업무 흐름(확장 수주 + P1~P10 · 쓰기/참조 저장소 · 메뉴 링크 · 설계도 표 그대로) → ② 메뉴(일하는 순서 카드 · 프로세스 · 중메뉴별 계약 기능명) → ③ 데이터(저장소 10 → 테이블 31) → ④ 계보(관계 5 · 번호 7종) → ⑤ 사용자 · 채널(사람 넷 · 역할 4 × 대메뉴 12 칸 수 · 채널 4) → ⑥ 확인 필요 7건. 설명 글은 `app/ia.py`(설계도에서 옮김), 수는 계약 · DB 에서 센다.

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 게이트 | `make gate-full` PASS 22 · FAIL 0 · WARN 0 · pytest **1633**(+4) · failed 0 | `make gate-full` (IA 화면 반영 뒤 1번째 실행 — 그 뒤 표 줄바꿈 CSS · 백틱 글자만 고치고 `tests/test_dev1_ia.py` · `test_dev1_home.py` 재실행 통과) |
| 설계도 대조 | `ia.PROCESSES` 10줄 = `tools/design_doc.processes()` (이름 · 주체 · 입력 · 쓰기 · 참조 · 출력물 글자 단위) | `tests/test_dev1_ia.py::test_process_table_is_the_design_doc_word_for_word` |
| 계약 대조 | 메뉴 ↔ 프로세스 = 기능 계약의 프로세스 열(BAS P1 · MAT P3·P5 · SYS 공통 · SAL 확장) · 저장소 → 테이블 30 + EXT 1 · 관계 5 = `lineage.RELATIONS` | `tests/test_dev1_ia.py` |
| 화면 | 관리자: 단 6 · 프로세스 11(확장+10) · 저장소 10 · 테이블 31 · 번호 7 모양(DB 형식 행) · 역할 4 · 채널 4 · 확인 필요 7 전부 표시. 현장: 열 수 없는 대메뉴(기준정보 관리 · LOT 추적 · 시스템 관리)는 흐름 띠에서 링크 없음 | `tests/test_dev1_ia.py` 4건 · 8020 playwright 캡처(관리자 1280 · 현장 1280 · 관리자 390 + 단별 6장) |
| 레이아웃 | 1280px · 390px 가로 스크롤 0 · 콘솔 오류 0 · IA 표는 쪽나눔 없음(`plain`) | playwright `scrollWidth == clientWidth` |

## 2026-10-08 메인 화면도 일하는 순서로 (D-417 보강 · 사람 요청 "메인 화면이 수정한 것을 반영하지 못했다")

메인의 묶음 4 패널과 뒤의 「확장」 패널을 없애고, 대메뉴 카드를 좌측 메뉴와 같은 순서(`nav.SIDEBAR`)로 한 줄씩 번호를 붙여 둔다. 영업관리 카드는 2번 자리(실적 현황 뒤 · 작업지시 앞)에 끼어 있고 확장 표시가 붙는다. 설계도 묶음 4(`nav.GROUPS` · `menu_tree`)는 그대로이고 이제 어느 화면에도 그리지 않는다.

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 게이트 | `make gate-full` PASS 22 · FAIL 0 · WARN 0 · pytest **1629** · failed 0 | `make gate-full` (메인 변경 뒤 1번째 실행) |
| 메인 카드 순서 | 관리자 STA → SAL → JOB → MAT → CLR → POP → RLL → QUA → SHP → TRC → BAS → PRT → SYS (13 · 번호 1~13) · 현장 10(기준정보 관리·LOT 추적·시스템 관리 숨김) · `data-group` 0 | `tests/test_dev1_home.py::test_main_shows_only_menus_of_the_role` · `tests/test_ext_sal.py` 메인 검사 · 8020 playwright 캡처 3장 |
| 카드 수 | 설계도 대메뉴 카드(`class="card"`) = 역할이 열 수 있는 대메뉴 수 그대로 · 확장 카드(`card-ext`) 1 | 같은 테스트 |
| 레이아웃 | 1280px · 390px 가로 스크롤 0 · 콘솔 오류 0 | playwright 캡처 (관리자 1280 · 현장 1280 · 관리자 390) |
| 검사기 변경 | 없음 (테스트 기대값만 새 배치로 — 순서 검사 추가, 뺀 검사 없음) | 코드 diff |

## 2026-10-08 좌측 메뉴 묶음 제거 · 영업관리(수주) 확장 (D-417 보강 · D-418)

좌측 메뉴는 묶음 없이 대메뉴 한 줄씩(메인 → 실적 현황 → 영업관리 → 작업지시 관리 → 자재 · 입고 → 조색 기록 → 생산 실적 (POP) → 후가공 · 슬리팅 롤 이력 → 품질 검사 기록 → 출하 → LOT 추적 → 기준정보 관리 → 인쇄 기준 관리 → 시스템 관리), 누르면 중메뉴가 펼쳐진다.
영업관리(수주 관리 · 수주 현황 · 거래처 이력)는 **설계도 밖 확장 계층**이다 — 설계도 수(12 · 32 · 94 · 48 · 30 · 번호 6종)는 그대로이고 게이트는 설계도 것만 센다.

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 게이트 | `make gate-full` PASS 22 · FAIL 0 · WARN 0 · pytest **1629**(+7) · failed 0 | `make gate-full` (D-418 반영 뒤 3번째 실행) |
| 설계도 수 | 대메뉴 12 · 중메뉴 32 · 기능 94+6 · 권한 48칸 · 테이블 D1~D8 23 + SYS 7 = 30 (DB 31 = 확장 EXT 1 제외 시 30) · 번호 6종 + 확장 1 | `check_trace` G-01·02 PASS · `check_schema` G-04 15/15 · `check_data` G-08 PASS |
| 확장 | 대메뉴 1(SAL) · 화면 3 · 기능 6(`X-SAL-01~06`, 쓰기 3) · 테이블 `sales_order` 1 · `job.sales_order_id` 컬럼 · `sys_number_rule` `SALES_ORDER` | `tests/test_ext_sal.py` 7건 · `contracts.ext_functions()` |
| 권한 | 영업관리 = 작업지시 관리 칸(관리자·생산 입력, 품질·현장 조회) · `sys_permission` 48행 그대로 | `rbac.cell('QC','SAL') == rbac.cell('QC','JOB')` · 권한 화면 perm-cell 48 |
| 화면 | 8020 에서 수주 등록 → 수주 화면 → 「이 수주로 작업지시 등록」 → 작업지시 폼 채움 · 수주 현황 · 거래처 이력 · 메인 확장 패널 캡처, 콘솔 오류 0 | playwright 캡처 7장 |
| 검사기 변경(낮춘 것 없음) | `check_schema` EXT 따로 세기 · `check_data` 정적 채번 검사에 `sales_order.order_no` 추가 · 동적 종류 대조는 설계도 6종 · `gen_contracts` EXT 단 · `test_dev1_numbering` 는 설계도 6종 + 확장 1 로 | 코드 diff |

## 2026-10-08 좌측 메뉴를 일하는 순서로 (D-417)

대시보드(메인 · 실적 현황) → 작업지시 → 입고 · 자재 → 공정(조색 → POP → 후가공·슬리팅) → 품질 → 출하 · 추적 → 기준정보 → 시스템. 설계도 묶음·순서(`nav.GROUPS` · `MENUS`)와 메인 화면은 그대로다.

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 게이트 | `make gate-full` PASS 22 · FAIL 0 · WARN 0 · pytest **1622**(+4) · failed 0 | `make gate-full` (D-417 반영 뒤) |
| G-01 | nav = 설계도 검사 9 전부 PASS — 설계도 순서는 건드리지 않았다 | `tools/check_trace.py` |
| 좌측 메뉴 | 관리자 묶음 8 · 대메뉴 12 · 중메뉴 32 링크 전부 · 메인 링크 맨 위 · 현장은 기준정보 관리·LOT 추적·시스템 관리 숨김 | `tests/test_arch_sidebar.py` 4건 · 8020 캡처(관리자 · 현장) |

## 2026-10-08 설계 정리 HTML (outputs/엘컴화인_MES_설계정리.html)

설계도(그림 5 · 표 3)를 사용자 → 업무 진행 → 데이터 흐름 → 계보 → 메뉴 → 아키텍처 → 확인 필요 → 게이트 순서로 다시 정리한 한 장. 기능 100줄 표는 `contracts/function-list.md` 에서 생성했다(손으로 옮기지 않음). 설계도는 고치지 않았다.

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 기능 표 | F- 94행 · B- 6행 · 대메뉴별 수 = 설계도 §5 | 생성기 assert (20·12·7·8·8·5·7·6·7·3·4·7) |
| HTML | 태그 균형 오류 0 · 외부 참조(CDN·링크) 0 · 128KB | `html.parser` 스택 검사 |
| 레이아웃 | 1280px · 390px 모두 가로 스크롤 0 · 콘솔 오류 0 | playwright 헤드리스 캡처 11장 확인 |
| 권한 칸 합 | 역할별 입력 5·6·3·5 = 19 · 조회 7·5·8·4 = 24 · 없음 0·1·1·3 = 5 | 설계도 §6 표를 손으로 셈 |

## 2026-10-08 시연 영상 4편 (test-video/ · outputs/video/시연-0N-*.mp4)

`node ~/.claude/skills/test_video_maker/bin/record.mjs` 로 실제 브라우저를 조작하며 녹화 — 단계마다 화면·DB 값을 검증하고 하나라도 틀리면 영상을 만들지 않는다. 개발 DB 는 읽기만(pg_dump 사본 `lcomfine_video` · 포트 8031 · 끝에 삭제).

| 편 | 흐름 | 길이 | 검증 |
|---|---|---|---|
| 01 관리자 | 퀵 로그인 → 메인 → 품목 등록 → 작업지시·작업지시서 → 사용자 등록 → 권한 표 48칸 → 접근 로그 | 2분 44초 | 14 |
| 02 현장 POP | 없는 번호 스캔 422 → 입고·LOT 라벨 → 입고검사(현장 비활성 · 품질 합격) → 작업 시작 → 자재 투입 → 조색·배합비 → 정지·재개·폐기 → 종료(인쇄 롤 + 계보 투입) → 롤 라벨 | 4분 38초 | 17 |
| 03 생산·품질 | 슬리팅 1→3 → splice 2→1 → 검사 합격·불합격 → 출하 등록·롤 스캔(불합격 롤 거부) → 승인·COA | 2분 14초 | 13 |
| 04 추적·현황·보안 | 역방향(출하 → 원재료 LOT)·정방향 추적 → 롤 이력 → 매핑 → 불량 집계 → 실적 현황 → 현황판 → 중지 계정 401 · 현장 403 → 접근 로그 | 2분 23초 | 14 |

- 합계 11분 59초 · 1920×1080 · 30fps · 평균 음량 -14.5~-16.8 dB · 검증 58건 전부 통과(검증 실패 0 — 느슨하게 고친 검증 없음).
- 격리 실측: 녹화 뒤 개발 DB 에 `VID-` 품목 0 · `vid_qc` 0 · 계정 104 그대로 · 8031 포트 비어 있음.
- 다시 녹화: `sh test-video/run_all.sh [--dry] [--from NN] [--only NN] [--keep]` — 편마다 사본 DB 덤프(`after-NN.dump`)를 남겨 한 편만 다시 돌릴 수 있다.
- 발견: 권한 차단(403 — 현장 계정의 승인 POST · `/sys/users` GET)은 `sys_access_log` 에 남지 않는다(로그인 실패·조회·변경만 남는다). G-18 범위 밖이라 결함은 아니나 운영 감사가 필요하면 결정이 필요하다.
- 음성(Yuna)은 들어 보지 못했다 — 발음·억양은 사람이 확인한다.

## 2026-10-07 로그인 상세 · 퀵 로그인 · 비밀번호 통일 (D-416)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 퀵 로그인 패널 | 역할 4 · 계정 단추 104(정상 96 · 잠금 5 · 중지 3 = 막힌 단추 8) · HTML 에 비밀번호 값 0 | `tests/test_arch_login.py` 6건 · `GET /login` 실측 |
| 퀵 로그인 판정 | 정상 계정 303(채널 유지 — field·pop → `/pop/work`) · 중지·미등록 401 · 운영(`prod`)·플래그 없음 404 | 같은 테스트 · 접근 로그 `detail` 끝 ` · 퀵 로그인` |
| 비밀번호 통일 | `make db-passwords` — 계정 104 · 바꾼 것 0(이미 전부 `.env` 값) | `tools/reset_passwords.py` 출력 |
| 게이트 | `make gate-full` PASS 22 · FAIL 0 · WARN 0 · pytest **1618**(+6) · failed 0 | `make gate-full` 11:4x |
| 화면 | Web 1100px 두 단 · 모바일 390px 한 단(넘침 없음) | 헤드리스 크롬 캡처(스크래치) |

켜는 법: `.env` 에 `LCOMFINE_QUICK_LOGIN=1`(이미 켜 둠). 운영 이미지(`LCOMFINE_ENV=prod`)에서는 켜도 꺼진다.

## 최종 보고 — 루프 종료 (2026-10-03 07:2x)

goal.md §4.4 의 종료 조건 셋을 동시에 만족해 루프를 멈춘다.

1. **게이트 G-01~G-22 전건 PASS** (`차단` 0) — 아래 판정표.
2. **QA 리포트 3종**(`outputs/qa1-기능계약.md` · `qa2-계보데이터.md` · `qa3-채널보안.md`) 존재 · 결함 누계 **22건 전부 해결 · 치명 0**.
3. **연속 2회전 변화 없음** — 06:5x 회전과 07:1x 회전의 `make gate-full` PASS 22 · pytest 1612 가 같다.

### 판정표 (`make gate-full` · 07:1x · 오케스트레이터 직접 실행)

```
G-01 메뉴 PASS · G-02 기능 PASS · G-03 화면 PASS · G-04 저장소 PASS · G-05 쓰기 경계 PASS
G-06 계보 재현 PASS · G-07 추적 PASS · G-08 키 연결 PASS · G-09 시드 멱등 PASS · G-10 집계 PASS
G-11 빈 화면 PASS · G-12 범위 밖 0 PASS · G-13 4채널 PASS · G-14 출력물 5종 PASS · G-15 이관 배치 PASS
G-16 ERP PASS · G-17 RBAC PASS · G-18 접근 로그 PASS · G-19 비밀 PASS · G-20 백업 PASS
G-21 빌드 PASS (pytest 1612 · failed 0 · check-routes PASS · /health 200) · G-22 브라우저 한 바퀴 PASS
PASS 22 · FAIL 0 · WARN 0 · BLOCKED 0 · 미검증 0 / 전체 22
```

### 만든 것 (실측)

| 항목 | 값 |
|---|---|
| 화면 | 중메뉴 32 + 공통 3, 전부 실 데이터 연동 · placeholder 0 · 4채널(Web · POP · 모바일 390px · 현황판) |
| 기능 | 계약 100줄(화면 94 + 이관 배치 6) ↔ 라우트 94/94 ↔ 테스트 표식 100/100 ↔ 배치 명령 6/6 |
| DB | 테이블 30(D1~D8 23 + SYS 7) · 컬럼 298 · `roll_genealogy` 순환 방지 트리거 · 뷰 2 |
| 계보 | 설계도 §3 예시 = `roll_genealogy` 10행(투입 3 · splice 2 · 슬리팅 3 · 출하 2) · 양방향 재귀 추적 · QA 독립 SQL 과 313건 불일치 0 · 막기 28/28 |
| 권한 | 48칸(입력 19 · 조회 24 · 없음 5) 데이터로 · 요청 686건 위반 0 |
| 출력물 | 작업지시서 · 라벨 3종 · COA — 인라인 SVG Code128, `zbarimg` 판독 5/5 |
| 테스트 | pytest **1612** (arch · dev1~3 · 시나리오 · QA1~3) · 검사기 `tools/check_{trace,routes,schema,screens,data,security}.py` · `make gate` |
| 브라우저 한 바퀴 | 16단계 전부 화면 조작 · 스캔 22회 타이핑+Enter · 우회 0 · 유실 0 · 캡처 `outputs/e2e/` |
| 코드 | `src/` 파이썬 7,770줄 · 템플릿 38 · 커밋 9(로컬 main, push 없음) |
| 결정 | `decisions.md` D 항목 80 — 전부 `가설`, `차단` 0 |

### 사람이 정해야 할 것 — 정해지면 바뀌는 곳

설계도 §7 「확인 필요」 7건과 구현 중 생긴 해석. 전부 `decisions.md` 에 `가설` 로 있고, 답이 오면 상태를 `확정` 으로 바꾸고 아래 한 곳만 고친다.

| D | 물음 | 지금 가설 | 바뀌면 |
|---|---|---|---|
| D-01 | 1안/2안 · 기존 MES 접근 경로 | 2안 · 표준 Import CSV 로 1회 이관 | 이관 파일 리더(`migration/`) · 과거 이력 적재 범위(`load-history` 는 규격까지) |
| D-02 | ERP 연계 범위·방식 | 없음 — 어댑터 + 501 명시 | `app/erp.py` 구현 |
| D-03 | 운영 환경 | 미정 — `Dockerfile` · `docker-compose.yml` 준비(**빌드·기동 미확인**, D-31) | 배포 설정 · 물리 구성도 · 쿠키 `Secure`(D-411) |
| D-04 | 스캐너·프린터 규격 · 롤 바코드 | 스캐너 = 키보드 입력 · 라벨 = 브라우저 인쇄 · 롤마다 Code128 | `app/printing.py` 어댑터 |
| D-05 / D-101 | 채번 규칙 | `J/L/M/R/S/C + YYMMDD- + 일련` (`sys_number_rule` 설정값) | `sys_number_rule` 6행 — 코드 수정 없음 |
| D-06 | 역할 4개로 충분한가 | 4역할 · 자재·출하 담당은 생산·현장이 겸함 | `sys_permission` 데이터 — 코드 수정 없음 |
| D-07 | LOT 추적·실적 현황 범위 | 포함 · PLC·비전·AI 제외 | — |
| D-10 / D-403 | 「Lot」 의 뜻 | Job 아래 생산 LOT(`job_lot`) · 추적 입력은 원재료 LOT·롤·출하 번호 | 추적 화면 입력(생산 LOT·Job 번호 받기) |
| D-12 | P8 출하가 D6 에 쓰는가 | 설계도 §3 그림을 따라 `출하` 화살표도 `roll_genealogy` 한 줄 | 설계도 §2 표 정정 또는 출하 롤 테이블 분리 |
| D-14 | 괄호 권한 해석 | 입고검사 등록은 품질만 · 출하 승인은 관리자만(생산·현장은 403) | `sys_permission.write_scope` 데이터 |
| D-16 / D-405 | 출하 LOT 1개 = Job 1개 · 출하가 걸린 Job 의 취소 | Job 1개 · 등록 상태 출하가 있어도 취소 가능 | `shp.py` · `job.py` 규칙 |
| D-17 | 미검사 롤 출하 | 허용 · COA 에 `미수집` · 불합격 롤은 422 | `lineage.ship_roll` 검사 |
| D-18 | 다색 인쇄의 색별 판사양·아니록스·잉크 | Job 당 하나씩 참조 | `job` 스키마 + 인쇄 기준 화면 |
| D-25 / D-301 / D-402 | 집계 산식 · 단위 섞인 수량 | `interfaces.md` §7 문장 · m+kg 를 그대로 더함 | `app/stats.py` 한 곳 |
| D-107 | 진행 중 실적이 있는 Job 마감 | 불가(422) — 실적 강제 종료 기능 없음 | `job.py update_order` |
| D-202 / D-406 | 입고량 초과 투입 | 막지 않음(단위·전량/부분의 뜻 미정) | `pop.py` 투입 검증 |
| D-208 | `완료` Job 의 재고 롤 후가공·슬리팅 | 불가 — `등록` 으로 되돌려야 함 | `lineage._assert_job_open` |
| D-209 | 배합비 합 100 판정 기준 | 저장되는 값(셋째 자리 반올림)의 합 | `clr.py` |
| D-303 / D-309 / D-311 / D-313 | 이관 파일 규격 · 되돌리기 · 변경 없음 | `migration-files.md` 16파일 · 실적 있는/취소 Job 은 값 같을 때만 통과 | `migration/files.py SPECS` |
| D-401 | 추적 화면에 경로 위 롤의 검사·실적 표시(설계도 §2 는 P9 가 D5·D7 참조) | 미표시(롤 이력 화면에서 봄) | `trc.py` 조회 |
| D-407 / D-412 / D-409 | 출하일·정지 시각 범위 · 슬리팅 분할 수 상한 | 막지 않음 | 각 입력 검증 한 줄 |
| D-408 / D-410 / D-411 / D-414 / D-415 | 미사용 역할 계정 로그인 · 403 접근 로그 · 쿠키 수명 14일·자동 로그아웃·실패 잠금·비밀번호 규칙 · 현황판 조회 로그 · 워커 여러 개 | 설계도에 없어 적용 안 함 / 미실측 | `auth.py` · `rbac.py` 설정 |

### 실 LOT 검증 절차 (도입 후 사람이 한다 — 설계도 §3 완료 기준)

루프는 `(예시)` 시드와 QA 가 만든 시나리오로만 검증했다. 실제 생산 LOT 으로는 다음을 한다.

1. 기준정보·인쇄 기준에 실제 품목·고객·판사양·아니록스·잉크조성을 넣는다(이관 파일 또는 화면).
2. 실제 작업지시 1건을 등록하고, 실제 원재료 LOT 라벨을 붙여 입고 → 입고검사 → 조색 → POP 인쇄(투입 스캔) → 후가공 → 슬리팅 → 검사 → 출하 승인 → COA 를 **현장 스캐너와 라벨 프린터로** 돈다(D-04 확인).
3. 출하된 롤 하나의 번호를 LOT 추적(역방향)에 넣어 원재료 LOT 까지 거슬러 올라가는지, 그 원재료 LOT 의 정방향 추적에 그 출하가 나오는지 본다.
4. `make backup` 과 `make restore-check` 를 운영 DB 에서 한 번 돌린다.

### 확인하지 못한 것

Docker 이미지 빌드·기동(데몬 꺼짐) · 워커 여러 개 · 실물 스캐너·프린터·터치 · 헤드리스 Chromium 외 브라우저 · HTTPS/프록시 · 장시간 현황판 · 백업 복구의 값 대조(행 수만).

### 재개하려면

`/re-begin` 또는 goal.md §0.1 의 한 줄. 사람이 D-번호에 답을 적은 뒤 돌리면, 바뀐 가설에 걸리는 게이트부터 다시 FAIL 로 잡힌다.

---

## 지금 해야 할 것

루프는 종료됐다. 남은 것은 사람의 결정(위 표)과 실 LOT 검증뿐이다.

## 2026-10-03 — 변화 없음 2회전 · 종료

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 22 · FAIL 0 / 22** — 직전 회전과 같음 → **연속 2회전 변화 없음** | `make gate-full` (07:1x) |
| pytest | **1612 passed** — 같음 | `uv run pytest -q` |
| 종료 조건 | §4.4 1·2·3 전부 충족 → 최종 보고 작성, 루프 정지 | 위 최종 보고 |

## 2026-10-03 — QA 마무리 재검 완료 · 변화 없음 1회전

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 새 결함 3건 재검 (QA) | **전부 해결** — DEF-QA2-004: 실서버 100쌍×2 둘 다 200 **0/100 · 0/100**(재검 전 41 · 35), 닫힌 Job 의 열린 실적 0, 교착 0 / DEF-QA3-010: 다른 값 rc 1 · 같은 값 「변경 없음」 · 건수 식 6/6 / DEF-QA3-011: 접속 문자열 4꼴 응답에 비밀번호·호스트·사용자·DB 0 | `outputs/qa2-계보데이터.md` DEF-QA2-004 · §10-8 · `outputs/qa3-채널보안.md` §9-9 |
| 같은 꼴 경합 (QA 독립 실측) | 8짝 × 50쌍 = 400쌍 · 순서 뒤집힘 0 · 5xx 0 · 교착 0 (생산 LOT 붙이기·수량 변경·비고 수정·마감·취소×취소·슬리팅·작업 종료 × 취소·마감) | `outputs/qa2-계보데이터.md` §10-8 |
| 새 결함 | **0건** · 결함 누계 **22건(QA1 7 · QA2 4 · QA3 11) 전부 해결 · 치명 0** | 리포트 3종 요약 표 |
| `make gate-full` (오케스트레이터) | **PASS 22 · FAIL 0 / 22** — 직전 회전과 같음 → **변화 없음 1회전** | `make gate-full` |
| pytest | **1612 passed · 0 failed** — 직전과 같음 | `uv run pytest -q` |
| 앱 무변경 | 재검 동안 `src` · `contracts` · `tools` · `tests` diff 0 (리포트 2종과 검사기가 다시 찍은 캡처만) | `git diff --stat HEAD -- src contracts tools tests` |

## 2026-10-03 — 웨이브 D 3차 · 오케스트레이터 재실측 (수정 담당 보고와 별도로 직접 실행)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 22 · FAIL 0 · 미검증 0 / 22** — 처음으로 전건 PASS | `make gate-full` (혼자 돌 때 직접 실행 06:3x) |
| pytest | **1612 passed · 0 failed** | `uv run pytest -q` |
| QA 파일 무변경 | 수정 라운드 동안 `tests/test_qa*.py` · `tools/check_*.py` · `tools/e2e/` diff 0 | `git diff --stat HEAD -- tests/test_qa*.py tools/check_*.py tools/e2e` |
| 잔여물 · 교착 | job 0 · roll 0 · work_result 0 · sys_user 4 · sys_permission 48 · `pg_stat_database.deadlocks` 0 | `psql -h /tmp -d lcomfine_db -Atc …` |

## 2026-10-03 — 웨이브 D 3차 완료 (수정 담당 1명 — 개발1·2·3·아키텍트 파일을 차례로) · 직접 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 22 · FAIL 0 · WARN 0 · BLOCKED 0 · 미검증 0 / 22** — G-21 FAIL → PASS | `make gate-full` (06:06 직접 실행 — 원문 아래) |
| pytest | **1612 passed · 0 failed** (직전 1588 · 6). 새 테스트 18건(개발1 6 · 개발2 10 · 개발3 1 · 아키텍트 1·5꼴) · QA 테스트·검사기 무변경 | `uv run pytest -q` |
| DEF-QA2-004 (중대) | `routers/pop.py` 작업 시작이 실적을 넣는 트랜잭션 안에서 Job 행 `for share` + 상태 재확인(D-211). 취소·마감(`for update`)과 겹치면 하나만 200. QA 테스트 30번 + 경합 테스트 25번 = 경합 5,650쌍 전부 통과 · 실서버 8021 에 400쌍(0~8ms 늦춤 포함) 둘 다 200 인 것 **0** · 두 순서 다 나옴 · 5xx 0 · `pg_stat_database.deadlocks` 0 | `tests/test_qa2_lineage.py::test_g08_work_start_racing_…` · `tests/test_dev2_pop.py -k "in_flight or racing"` · 스크래치 실서버 스크립트 |
| 같은 꼴 ⓐ~ⓓ | ⓐ 생산 LOT × 취소·마감 **창 있었음 → 닫음**(D-109 `share_job`) · ⓒ 품목·수량 변경 × 작업 시작 **창 있었음 → 닫음**(D-109 `lock_job` 뒤 재확인; 수정 × 취소 · 취소 × 취소도 함께) · ⓑ 후가공·슬리팅 × 마감 **창 없음**(D-208 — 테스트로 확인) · ⓓ 자재 투입·작업 종료 × 취소 **창 없음**(커밋된 실적이 전제 · 실적 있는 Job 의 취소는 422) | `tests/test_dev1_job.py -k "in_flight or two_cancels"` · `tests/test_dev2_rll.py -k in_flight` |
| DEF-QA3-010 (경미) | `load-jobs` — DB 에서 `취소` 인 Job 은 값이 전부 같으면 「변경 없음」, 하나라도 다르면 그 행 오류 · rc 1 (D-313). 계약 B-MIG-04 · `migration-files.md` §1·§5 반영 | `tests/test_qa3_ops.py::test_migration_does_not_change_a_cancelled_job` · `tests/test_dev3_migration.py` 19 passed · `gen_contracts.py --check` 렌더본 = 원본 |
| DEF-QA3-011 (경미) | `/health` 에서 `db.dsn` 을 **뺐다**(상태값·건수만, D-32) · `router_include_errors` 는 모듈·예외 종류만 · `conn` 이 `DbUnavailable` 사유에서 비밀번호를 가리고, 틀린 접속 문자열(드라이버가 조각을 되읊음)은 원문 없이 503. 접속 문자열 7꼴에서 응답에 비밀번호·호스트·사용자·DB 이름 0 · 서버 로그에 비밀번호 0 | `tests/test_qa3_ops.py -k health` 3 passed · `tests/test_arch_smoke.py -k health` 6 passed |
| D-209 배합비 사유 | 422 사유에 저장 자릿수 규칙 + 반올림된 행의 「입력 → 저장되는 값」 · 입력칸 `step="0.001"` · 판정 규칙 그대로 | `tests/test_dev2_clr.py` 9 passed |
| 변이 확인 | 잠금·재확인을 프로세스 안에서 빼면(변이 4종) 새 테스트가 각각 실패 — QA 2건 · 개발 11건 | 스크래치 변이 스크립트 (파일은 그대로) |
| 결정 | D-109(개발1) · D-211(개발2) · D-313(개발3) · D-32(아키텍트) 추가 · D-209 에 설명 한 줄 — 전부 가설, 차단 0 (D 항목 80) | `grep -c "^## D-" decisions.md` |
| 잔여물 | job 0 · roll 0 · work_result 0 · shipment 0 · job_lot 0 · sys_user 4 · sys_permission 48 · 포트 8021~8023 비어 있음 | `psql -h /tmp -d lcomfine_db -Atc "select count(*) from …"` · `lsof -iTCP:8021` |
| 미확인 | 워커 여러 개(D-415)에서의 경합 · Docker 컨테이너 로그(D-31) · PostgreSQL 서버 쪽 로그의 접속 정보 | — |

`make gate-full` 판정표 (원문):

```
게이트 판정 — 엘컴화인 MES · 2026-10-03 06:06 · 시드 재실행 포함

G-01  메뉴 — 묶음 4 · 대메뉴 12 · 중메뉴 32 (nav = 설계도)      PASS  검사 9 전부 PASS
G-02  기능 — 94 + 이관 6 · 계약 = API = 테스트 · 고아 0       PASS  검사 7 전부 PASS
G-03  화면 — 중메뉴 32 + 공통 3 전부 200 · placeholder 0    PASS  검사 7 전부 PASS
G-04  저장소 — D1~D8 ↔ 계약 ↔ 실제 DB                     PASS  검사 15 전부 PASS
G-05  쓰기 경계 — 프로세스별 쓰는 저장소 · P9·P10 쓰기 0           PASS  검사 9 전부 PASS
G-06  계보 재현 — §3 예시 roll_genealogy 10행 (API)       PASS  검사 6 전부 PASS
G-07  추적 — 역방향·정방향 재귀 조회 · 분기 5단 이상                PASS  검사 8 전부 PASS
G-08  키 연결 — 롤 번호 → 지시·조색·실적·검사·출하 · 채번 한 곳        PASS  검사 9 전부 PASS
G-09  시드 멱등 — 2회 실행 행 수 diff 0 · (예시) 표기           PASS  검사 3 전부 PASS
G-10  집계 — 생산·품질·납기 = 독립 SQL 재계산                   PASS  검사 6 전부 PASS
G-11  빈 화면 — 미수집 / 미확정 (D-nn)                      PASS  검사 14 전부 PASS
G-12  범위 밖 0 — PLC 수집 · 비전 · AI 없음                 PASS  검사 4 전부 PASS
G-13  4채널 — POP 스캔 · 모바일 390px · 현황판 새로고침          PASS  검사 15 전부 PASS
G-14  출력물 5종 — 작업지시서 · 라벨 3 · COA · 바코드            PASS  검사 8 전부 PASS
G-15  이관 배치 6 — Import 파일 · 멱등 · 리포트               PASS  검사 10 전부 PASS
G-16  ERP — 어댑터 + 501 명시 · 조용한 폴백 0                PASS  검사 4 전부 PASS
G-17  RBAC — 48칸 (입력 19 · 조회 24 · 없음 5) · 괄호 조건 2  PASS  검사 10 전부 PASS
G-18  접근 로그 — 로그인 · 조회 · 변경 · 로그 화면                PASS  검사 7 전부 PASS
G-19  비밀 — 저장소·문서에 비밀 값 없음                         PASS  검사 8 전부 PASS
G-20  백업 — make backup · restore-check             PASS  검사 2 전부 PASS
G-21  빌드 — pytest 전건 · check-routes · /health 200  PASS  pytest passed 1612 · failed 0 · check-routes PASS · /health 200
G-22  브라우저 한 바퀴 — outputs/e2e 캡처                   PASS  검사 1 전부 PASS · 출처 outputs/qa3-채널보안.md · outputs/e2e 파일 90개

PASS 22 · FAIL 0 · WARN 0 · BLOCKED 0 · 미검증 0 / 전체 22
※ WARN·미검증은 통과가 아니다. BLOCKED 는 decisions.md 에 D-번호와 사유가 있어야 종료 조건(goal.md §4.4)을 만족한다.
```

## 2026-10-03 — QA 재검 완료 (웨이브 D 뒤) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 21 · FAIL 1 / 22** — FAIL: G-21(pytest 6건 — 재검에서 나온 새 결함 3건을 드러내는 테스트). **G-22 가 FAIL → PASS** | `make gate-full` (혼자 돌 때 직접 실행) |
| pytest | **1588 passed · 6 failed** — DEF-QA2-004 2건 · DEF-QA3-010 1건 · DEF-QA3-011 3건. 직전의 QA1 자기 모순 1건은 QA 가 DEF-QA1-007 기대값(404)으로 정리해 통과 | `uv run pytest -q` |
| G-22 브라우저 한 바퀴 | **PASS** (QA 재검) — 헤드리스 Chromium, 16단계 전부 화면 조작 · API 대체 0 · 스캔 22회 전부 타이핑+Enter(알림이 뜬 채 7회) · **스캔칸 직접 누름(우회) 0 · 유실 0** · 계보 10행 · 역추적이 원재료 LOT ①② 도달 · 캡처 87장 | `outputs/qa3-채널보안.md` 의 `G-22` 행 · `outputs/e2e/` |
| 웨이브 C 결함 19건 | **전부 해결** (원래 재현 절차로 재검) | `outputs/qa{1,2,3}-*.md` 의 "재검 (웨이브 D 뒤)" 줄 |
| 새 결함 | **3건 — 치명 0 · 중대 1 · 경미 2**: DEF-QA2-004(작업 시작 × Job 취소·마감 경합) · DEF-QA3-010(이관이 취소 Job 갱신) · DEF-QA3-011(`/health` 의 접속 문자열 노출) | 위 pytest 실패 6건 |
| 검사기 보강 (QA) | 헐거웠던 4곳을 조임 — `check_screens` OpenAPI 행(관리자 세션으로 서버에서 읽고 읽은 양을 판정에) · `check_security` 현황판 행(noscript 의 meta 만 보고 통과하던 것 → `app.js` 까지) · 현황판 실측 주기 범위 · `check_data` G-08 에 D-208 문장. G-13 검사 14 → 15 | QA 재검 보고 |
| 앱 무변경 | 재검 동안 `src/` · 계약 · `gate.py` · 개발 테스트 diff 0 | `git diff --stat HEAD -- src contracts tools/gate.py tests/test_dev*.py tests/test_arch_*.py` |
| 잔여물 | roll 0 · job 0 · work_result 0 · sys_user 4 · sys_permission 48 | `psql -h /tmp -d lcomfine_db -Atc "select count(*) from …"` |

## 2026-10-03 — 웨이브 D 2차 완료 (개발1 · 개발3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 20 · FAIL 2 / 22** — FAIL: G-21(pytest 1건 — QA1 자기 모순) · G-22(리포트 판정이 재검 전) | `make gate-full` |
| pytest | **1587 passed · 1 failed** (직전 1580 · 2). 남은 1건 = `test_qa1_rbac.py::test_forbidden_comes_before_validation` | `uv run pytest -q` |
| 조용한 실패 정적 검사 | `qua.py` · `shp.py` · `trc.py` 의 스캔 422 처리를 `except` 없이 값으로 가름 → `test_static_scan_finds_no_unreviewed_swallowing_except` 통과 | `uv run pytest -q tests/test_qa3_ops.py` |
| Job 마감 (D-107) | 진행·정지 중인 작업 실적이 있는 Job 은 `완료` 422(사유에 열린 실적). 취소는 원래 실적 1건이라도 있으면 422 | `uv run pytest -q tests/test_dev1_job.py` |
| 이관 재실행 (D-311) | 실적 있는 Job 이라도 파일 값 = DB 값이면 「변경 없음」 통과(쓰지 않음), 다르면 오류 · `read = loaded + 변경 없음 + error` | `uv run pytest -q tests/test_dev3_migration.py` (17 passed) |
| 계약 반영 (오케스트레이터 직접) | `function-list.md` F-JOB-02(D-107) · B-MIG-04(D-311) · `migration-files.md` §1 · §5 #4 | `uv run python tools/gen_contracts.py --check` → "렌더본 = 원본" · `make check-trace` G-01·G-02 PASS |

## 2026-10-03 — 웨이브 D 1차 완료 (아키텍트 · 개발2 · 개발3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 20 · FAIL 2 · 미검증 0 / 22** — FAIL: G-21(pytest 2건 실패) · G-22(QA3 리포트의 판정이 아직 재검 전 FAIL). G-08 · G-13 · G-15 · G-19 · G-20 이 FAIL → PASS | `make gate-full` (혼자 돌 때 직접 실행) |
| pytest | **1580 passed · 2 failed** (직전 1522 · 39). QA 테스트·검사기는 수정하지 않음 | `uv run pytest -q` |
| 남은 실패 2건 | ① `test_qa1_rbac.py::test_forbidden_comes_before_validation` — QA1 의 두 테스트가 같은 요청(`POST /qua/inspections/abc/delete`)에 422 와 404 를 각각 기대(자기 모순). 개발3 은 DEF-QA1-007 대로 404 로 고침 ② `test_qa3_ops.py::test_static_scan_finds_no_unreviewed_swallowing_except` — 개발3 이 이번에 넣은 스캔 422 처리의 `except` 2곳 | 위와 같음 |
| 세션 무효화 (G-19) | 요청마다 `sys_user` 확인 · 로그아웃은 그 세션만 서버에서 무효 · 상태·비밀번호 변경은 DB 트리거가 세션 판 번호를 올려 전부 끊음. `sys_user` 컬럼 2개 추가(`session_epoch` · `revoked_sessions`) — `ALTER` 로 반영, 계약 컬럼 296 → **298** = DB | `make check-schema` (G-04 15/15) · `tests/test_qa3_channel_e2e.py -k "session or cookie"` |
| POP 스캔 (G-13) | 검사 14 전부 PASS — 알림 중 스캔 글자가 스캔칸으로, 닫으면 포커스 복귀(공용 `static/app.js`) · 검사·출하 화면의 없는 번호 스캔이 같은 화면 422 · 현황판이 오류·서버 끊김 뒤 스스로 복귀 | `uv run python tools/check_security.py` (gate-full 안에서) |
| G-08 키 연결 | 후가공·슬리팅 롤 이력에 조상 인쇄 롤의 생산 실적 · splice/후가공/슬리팅 롤이 붙는 Job 은 부모의 Job 이고 `등록` 상태여야 함(D-208) | `uv run python tools/check_data.py --only G-08` |
| G-15 이관 | 실적·롤·출하가 있는 Job 은 덮어쓰지 않고 오류 리포트(D-309) | gate-full 의 G-15 (10/10) |
| G-20 백업 | `make backup` → 덤프 + 행 수 · `make restore-check` → 임시 DB 복구 · 테이블 30개 행 수 일치 · 임시 DB 삭제 | gate-full 의 G-20 (2/2) |
| 결정 | D-26~D-31(아키텍트) · D-208~210(개발2) · D-308~310(개발3) · D-401~D-415(QA 「사람 확인」) 추가 — 전부 가설, 차단 0 | `grep -c "^## D-" decisions.md` |
| 미확인 | Docker 이미지 빌드·기동(데몬 꺼짐 — `docker compose config` 문법만) · 워커 여러 개 · 실물 스캐너·프린터 | 아키텍트 보고 |

## 2026-10-03 — 웨이브 C 완료 (QA 1·2·3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 15 · FAIL 6 · 미검증 1 / 22** — PASS: G-01~G-07 · G-09~G-12 · G-14 · G-16 · G-17 · G-18. FAIL: G-08 · G-13 · G-15 · G-19 · G-20 · G-21. 미검증: G-22(gate.py 가 리포트를 읽지 않음 — QA3 판정은 **FAIL**) | `make gate-full` (04:1x 직접 실행) |
| pytest | **1522 passed · 39 failed** — 실패 39 전부 QA 가 결함을 드러내려고 둔 테스트(QA1 26 · QA2 3 · QA3 10), skip/xfail 0 | `uv run pytest -q` |
| G-06 · G-07 계보 | QA2 가 개발 테스트를 쓰지 않고 API 로 직접 재현: `roll_genealogy` **10행**(투입 3 · splice 2 · 슬리팅 3 · 출하 2) = 설계도 화살표 10 · 화면 폼만으로도 10행 · 양방향 추적 화면 = 독립 재귀 SQL(임의 계보 5개 · 추적 313건 · 깊이 8~12단 · 불일치 0) · 막기 28/28 | `uv run python tools/check_data.py --only G-06,G-07` |
| G-10 집계 | 생산·품질·납기·불량 유형·현황판 화면값 = QA2 독립 SQL (대조 248칸 · 불일치 0) | `uv run python tools/check_data.py --only G-10` |
| G-17 권한 | 48칸 전수 — 요청 686건(화면 128 · 메뉴 48 · 읽기 160 · 쓰기 216 · 미로그인 134) 위반 0 · 괄호 조건 2 · 권한 표는 데이터 | `uv run python tools/check_screens.py` |
| G-14 출력물 | 5종 인쇄 화면 · 바코드 `zbarimg` 판독 5/5 · 외부 요청 0 · 디코드 값으로 스캔 진입 | `uv run python tools/check_security.py` |
| G-22 브라우저 한 바퀴 | **FAIL** (QA3) — 헤드리스 Chromium 으로 16단계 전부 화면 조작, 계보 10행·역추적까지 완주했으나 11(품질 검사)·12(출하 롤 스캔)단계에서 알림 중 스캔 유실 1건 + 포커스 상실로 손 조작 우회 7건. 캡처 86장 | `outputs/qa3-채널보안.md` · `outputs/e2e/` |
| 결함 | **19건 — 치명 0 · 중대 12 · 경미 7** (QA1 7: 중대 4 · 경미 3 / QA2 3: 중대 2 · 경미 1 / QA3 9: 중대 6 · 경미 3). 같은 원인 중복 포함(세션 무효화 · 스캔칸 사라짐) | `outputs/qa{1,2,3}-*.md` |
| 테스트 잔여물 | `Q1-` · `Q2-` · `Q3` 업무 행 0 (QA 보고) · sys_permission 48 · sys_user 4 | QA 리포트 · 다음 회전에서 재확인 |

## 2026-10-03 — 웨이브 B 완료 (개발 1·2·3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 5 · FAIL 1 · 미검증 16 / 22** — PASS: G-01 · G-02 · G-03 · G-04 · G-21. FAIL: G-20(백업 도구 없음). 미검증 16 은 QA 검사기 대기 | `make gate-full` (03:2x 직접 실행) |
| pytest | **369 passed** (arch 34 · dev1 127 · dev2 152 · dev3 56) | `uv run pytest -q` |
| G-02 기능 | 기능 ↔ 라우트 **94/94** · 고아 라우트 0 · 테스트 표식 **100/100** · 이관 배치 명령 **6/6** | `make check-trace` |
| G-03 화면 | HTTP 200 35/35 · placeholder **0** | `make check-routes` |
| 계보 시나리오 | `tests/test_lineage_scenario.py` 9 passed — 설계도 §3 예시 10행(투입 3 · splice 2 · 슬리팅 3 · 출하 2)을 화면 API 로 생성, 양방향 추적, 6단 이상 임의 계보. **G-06·G-07 판정은 QA2 대기(미검증)** | `uv run pytest -q tests/test_lineage_scenario.py` |
| 시드 멱등 | 재실행 행 수 diff 0 (테이블 29 · 행 98) | `make gate-full` 의 G-09 실측 |
| 테스트 잔여물 | roll 0 · roll_genealogy 0 · job 0 · shipment 0 · inspection 0 · sys_migration_log 0 · 시드만 남음(material_lot 4 · item 5 · sys_user 4 · sys_permission 48) | `psql -h /tmp -d lcomfine_db -Atc "select count(*) from roll"` 등 |
| 용어 오염 | 0건 | `grep -rnE "솥\|인분\|검식\|절임\|숙성\|염도\|needsfood" src tools tests contracts Makefile` |
| 게이트 도구 수정 | `tools/check_trace.py` 가 `include_router` 한 라우터를 펴지 못해 기능 ↔ 라우트가 항상 0/94, 고아 검사가 빈 집합으로 통과하던 것을 고침 (`all_routes`) — 게이트를 낮춘 것이 아니라 재는 방법을 바로잡음 (개발1 §3-1) | 수정 전 0/94 → 수정 후 94/94 · 고아 0 |
| 결정 | D-101~106(개발1) · D-201~207(개발2) · D-301~307(개발3) 추가, 전부 가설 · 차단 0 | `grep -c "^## D-" decisions.md` |
| 개발 보고 중 미확인 | 실제 브라우저 조작은 개발2 의 POP 헤드리스 한 바퀴뿐 · 모바일 390px 는 정적 HTML 측정 · 현황판 30초 새로고침 미실측 · 실물 스캐너/프린터 미확인(D-04) → QA3 G-13 · G-22 | `progress-dev{1,2,3}.md` |

## 2026-10-03 — Phase 0 오케스트레이터 재실측 · 웨이브 B 기동

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate` | **PASS 2 · FAIL 11 · 미검증 9 / 22** — 아키텍트 보고와 동일 (G-01 · G-04 PASS, G-03 placeholder 32) | `make gate` (오케스트레이터 직접 실행 02:27) |
| pytest | **34 passed** | `uv run pytest -q` |
| 시드 멱등 | 재실행 행 수 diff 0 (테이블 29 · 행 56) | `make gate-full` 의 G-09 실측 |
| 정본·메타프롬프트 | `goal.md` 33,604B · 설계도 50,360B — Phase 0 전과 같음 | `wc -c` |
| 웨이브 B | 개발 1·2·3 병렬 기동. 규칙: 커밋은 오케스트레이터만 · `make db-reset`/`db-schema` 금지(공유 DB) · 스키마·계약 변경은 `progress-devN.md` §3 요청 · 포트 8021/8022/8023 | goal.md §5 |

## 2026-10-03 — Phase 0 (아키텍트) 완료

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 설계도 수치 (goal.md §9) | 대메뉴 **12** · 중메뉴 **32** · 기능 **94** / 권한칸 **48** = 입력 **19** · 조회 **24** · 없음 **5** | goal.md §9 스니펫을 그대로 실행 (`uv run python - <<'EOF' …`) |
| 설계도 수치 (그 밖) | 묶음 4 · 프로세스 10(P1~P10) · §3 그림의 계보 화살표 **10** | `uv run python -c "import sys; sys.path.insert(0,'tools'); import design_doc as d; print(len(d.ia()['groups']), len(d.processes()), d.lineage_arrows())"` |
| 환경 | git 저장소(로컬 · main) · uv / Python 3.12 · DB `lcomfine_db` · `.env`(gitignore, 난수 비밀 2개) | `make setup` · `git check-ignore .env` |
| G-01 메뉴 | **PASS** — 검사 9 전부 PASS (nav 묶음 4 · 대메뉴 12 · 중메뉴 32 = 설계도 이름·순서·기능 수·채널, screen-map 렌더본 일치) | `make check-trace` |
| G-02 기능 | **FAIL(정상)** — 검사 10 중 7 PASS: 계약 100줄 = 화면 94 + 배치 6 · 대메뉴별 20·12·7·8·8·5·7·6·7·3·4·7 = 설계도 · 쓰는 저장소 ⊆ 설계도 §2 표(예외 2건 D-12) · 권한 열 = 설계도 §6. 3 FAIL: 기능 ↔ 라우트 0/94 · 테스트 표식 0/100 · 배치 명령 0/6 | `make check-trace` |
| G-03 화면 | **FAIL(정상)** — HTTP 200 **35/35**(중메뉴 32 + 공통 3) · placeholder **32**(개발1 13 · 개발2 11 · 개발3 8) | `make check-routes` |
| 권한 없음 = 403 | 역할 4 × 화면 32 = 128건 조회 검사, 없음 5칸 → 403 + 메뉴 숨김, 위반 **0** · 미로그인 브라우저 303 / 그 밖 401 | `make check-routes` |
| G-04 저장소 | **PASS** — 검사 7 전부 PASS. 계약 테이블 30 = DB 30 · 계약 컬럼 **296** = DB 296 · D1 9 · D2 2 · D3 1 · D4 2 · D5 4 · D6 2 · D7 2 · D8 1 (+ SYS 7) · 뷰 2 | `make check-schema` |
| 공통 시드 | 역할 4 · 권한 48칸(입력 19 · 조회 24 · 없음 5) · 계정 4 — **2회 실행 행 수 동일** (sys_permission 48 · sys_role 4 · sys_user 4) | `uv run python -m lcomfine.db.seed` ×2 · `make gate-full` 의 G-09 실측 "diff 0" |
| pytest | **34 passed** — `test_arch_smoke.py` 19(메뉴 수 · 계약 100줄 · 권한 48칸 · health · 303/401 · 로그인 401→303 · placeholder 32 · 권한 없음 403 5건 · 괄호 권한 2개 · ERP 501 · 404 · 채널 훅 · 접근 로그) + `test_arch_genealogy.py` 15 | `uv run pytest -q` |
| 계보 스키마 (SQL 직접) | 설계도 §3 예시 = **10행**(투입 3 · splice 2 · 슬리팅 3 · 출하 2) · 역방향 추적이 LOT ①② 에 닿음(9행) · 정방향이 출하 LOT 에 닿고 슬리팅 ③ 은 `재고` · 깊이 12단 사슬 추적 · DB 가 막는 것 10종(자기 자신 · 순환 · 재출하 · 소진 롤 출하 · 출하 롤 재사용 · 중복 · LOT→출하 · 관계 불일치 · 행 수정 · 다른 Job) — 각각 **그 제약으로** 막혔는지 확인 | `uv run pytest -q tests/test_arch_genealogy.py` (행은 전부 롤백 — DB 에 남지 않음) |
| 서버 기동 | 포트 8020 `/health` 200 `{"status":"ok", groups 4, menus 12, screens 32, functions 94, batch_functions 6, placeholders 32}` · `/login` 200 · `/static/style.css` 200 | `make run` 후 `curl -s localhost:8020/health` |
| 용어 오염 | 다른 사업의 용어·패키지명 **0건** (goal.md 자체 제외) | `grep -rnE "솥\|인분\|검식\|절임\|숙성\|염도\|needsfood" src tools tests contracts *.md Makefile` |
| 계약 | `contracts/{function-list,db-schema,screen-map,interfaces,api-contract}.md` — 렌더본(db-schema §4 · screen-map §1) = 원본 | `uv run python tools/gen_contracts.py --check` → "렌더본 = 원본" |
| 결정 | `decisions.md` D-01~D-07(설계도 §7, 전부 가설) + D-08~D-25(아키텍트 18건, 전부 가설) · 차단 0 | `grep -c "^## D-" decisions.md` → 25 |

`make db-reset && make gate` 판정표 (원문):

```
게이트 판정 — 엘컴화인 MES · 2026-10-03 02:25

G-01  메뉴 — 묶음 4 · 대메뉴 12 · 중메뉴 32 (nav = 설계도)      PASS  검사 9 전부 PASS
G-02  기능 — 94 + 이관 6 · 계약 = API = 테스트 · 고아 0       FAIL  검사 10 · 통과 못한 3 — 기능 94 ↔ 라우트 (API 열의 메서드·경로가 등록됨): 이어진 기능 0/94 · 미연결 예 ['F-BAS-01', 'F-BAS-02', 'F-BAS-03'] / 기능 100 ↔ 테스트 (@pytest.mark.fn 표식): 표식이 붙은 기능 0/100 · 테스트 파일 2 / 이관 배치 6 ↔ 명령 (lcomfine.migration.COMMANDS): 이어진 배치 0/6 · src/lcomfine/migration 없음 (개발3)
G-03  화면 — 중메뉴 32 + 공통 3 전부 200 · placeholder 0    FAIL  HTTP 200 35/35 · placeholder 32 (개발1 13 · 개발2 11 · 개발3 8)
G-04  저장소 — D1~D8 ↔ 계약 ↔ 실제 DB                     PASS  검사 7 전부 PASS
G-05  쓰기 경계 — 프로세스별 쓰는 저장소 · P9·P10 쓰기 0           미검증  tools/check_data.py 없음 (QA2) — 쓰기 라우터 0개
G-06  계보 재현 — §3 예시 roll_genealogy 10행 (API)       FAIL  tests/test_lineage_scenario.py 없음 (개발2 R1) · roll_genealogy 0행
G-07  추적 — 역방향·정방향 재귀 조회 · 분기 5단 이상                FAIL  app/lineage.py 스텁 — 미구현 — 담당 개발2 (app/lineage.py)
G-08  키 연결 — 롤 번호 → 지시·조색·실적·검사·출하 · 채번 한 곳        FAIL  app/numbering.py 스텁 — 미구현 — 담당 개발1 (app/numbering.py) · sys_number_rule 0행
G-09  시드 멱등 — 2회 실행 행 수 diff 0 · (예시) 표기           미검증  이 실행에서는 시드를 돌리지 않았다 — `make gate-full`
G-10  집계 — 생산·품질·납기 = 독립 SQL 재계산                   FAIL  app/stats.py 스텁 — 미구현 — 담당 개발3 (app/stats.py)
G-11  빈 화면 — 미수집 / 미확정 (D-nn)                      미검증  tools/check_data.py 없음 (QA2)
G-12  범위 밖 0 — PLC 수집 · 비전 · AI 없음                 미검증  tools/check_data.py 없음 (QA2)
G-13  4채널 — POP 스캔 · 모바일 390px · 현황판 새로고침          미검증  tools/check_security.py 없음 (QA3) — 채널 레이아웃 훅(body.ch-*)만 있다
G-14  출력물 5종 — 작업지시서 · 라벨 3 · COA · 바코드            FAIL  app/printing.py 스텁 — 미구현 — 담당 개발2 (app/printing.py)
G-15  이관 배치 6 — Import 파일 · 멱등 · 리포트               FAIL  src/lcomfine/migration 없음 (개발3) · 파일 규격 contracts/migration-files.md 없음
G-16  ERP — 어댑터 + 501 명시 · 조용한 폴백 0                미검증  자체 실측 /erp/status → 501 `ERP 연계 미확정 (D-02)` · 조용한 폴백 검사는 check_security(QA3) 대기
G-17  RBAC — 48칸 (입력 19 · 조회 24 · 없음 5) · 괄호 조건 2  미검증  자체 실측 DB 권한 표 48칸 = 설계도 §6 (입력 19 · 조회 24 · 없음 5) · 없음 칸 403 위반 0 · 쓰기 403 전수는 쓰기 API 가 생긴 뒤 check_security(QA3)·QA1
G-18  접근 로그 — 로그인 · 조회 · 변경 · 로그 화면                FAIL  sys_access_log 로그인 6 · 조회 151 · 변경 0 · 오류 0 · 로그 화면(SYS-03) placeholder — 조회 불가
G-19  비밀 — 저장소·문서에 비밀 값 없음                         미검증  자체 실측 저장소 대상 파일 70개 중 비밀 값이 든 파일 0 · .env gitignore 됨 · check_security(QA3) 대기
G-20  백업 — make backup · restore-check             FAIL  tools/backup.py 없음 — `make backup` · `make restore-check` 미구현
G-21  빌드 — pytest 전건 · check-routes · /health 200  FAIL  pytest passed 34 · failed 0 · check-routes FAIL · /health 200
G-22  브라우저 한 바퀴 — outputs/e2e 캡처                   미검증  outputs/e2e 파일 0개 — 브라우저 한 바퀴는 QA3 가 돌고 `outputs/qa3-채널보안.md` 에 판정을 적는다

PASS 2 · FAIL 11 · WARN 0 · BLOCKED 0 · 미검증 9 / 전체 22
※ WARN·미검증은 통과가 아니다. BLOCKED 는 decisions.md 에 D-번호와 사유가 있어야 종료 조건(goal.md §4.4)을 만족한다.
```

만든 것 —
`pyproject.toml`(uv · Python 3.12 · `lcomfine-mes`) · `Makefile` · `.env.example` · `CLAUDE.md` · `decisions.md` ·
`src/lcomfine/app/{main,nav,rbac,auth,templating,settings,contracts}.py` · `util/{http,audit,screen}.py` ·
`routers/home.py`(메인 최소 구현) + 12 모듈 빈 스텁 · 공용 모듈 스텁 `{numbering,lineage,printing,stats}.py`(시그니처) · `erp.py`(전부 501) ·
`templates/{base,login,_error,_placeholder}.html` + `home/{main,_macros}.html` · `static/{style.css,app.js}` ·
`db/{schema.sql,conn.py,seed.py}` · `tools/{gate,check_routes,check_trace,check_schema,gen_contracts,design_doc,init_env}.py` ·
`tests/{test_arch_smoke,test_arch_genealogy}.py`.

Phase 0 에서 만들지 않은 것 — `tools/backup.py`(G-20, Makefile 타깃은 실패로 나온다) · `Dockerfile`/`docker-compose.yml`(D-03) ·
`tools/{check_data,check_security,check_screens}.py`(QA 가 만든다 → 그때까지 해당 게이트는 `미검증`).

게이트 판정표에서 주의할 것 — G-16·G-17·G-19 는 `gate.py` 가 사실을 재서 실측 칸에 적지만 판정은 `미검증` 이다(D-24). PASS 는 QA3 의 `check_security.py` 가 준다.
`make check-routes` · `make check-trace` 는 지금 종료코드 1 이다(placeholder 32 · 기능 미연결) — 정상.

다음: 웨이브 B — 개발 1·2·3 병렬 기동 (goal.md §5).
