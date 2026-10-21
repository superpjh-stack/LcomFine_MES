-- 엘컴화인 MES v2 — DB 스키마 (PostgreSQL 17 · DB lcomfine_db)
--
-- 이 파일이 테이블·컬럼의 **원본**이다. `contracts/db-schema.md` §4 는 이 파일과 실제 DB 의 렌더본이다(`make contracts`).
-- 고치는 사람은 아키텍트뿐이다. 개발자는 `progress-devN.md` §3 에 요청을 남긴다.
-- 테이블 이름 집합은 스펙 §4.1 표 그대로다(D-521) — 업무 39 + SYS 9 = 48 · 뷰 9.
--
-- 작성 규칙 — `tools/gen_contracts.py` 가 이 형식을 읽는다:
--   · 테이블 앞 한 줄:  `-- @` 다음에 `table <이름> | <영역> | <설명>`   영역 = 대메뉴 코드(nav.py) 또는 SYS
--   · 뷰 앞 한 줄:      `-- @` 다음에 `view <이름> | <설명>`
--   · 컬럼 한 줄에 하나, 줄 끝에 `-- 설명`. 제약 줄은 constraint 로 시작하고 한 줄에 하나.
--   · 공통 컬럼: id bigserial pk · created_at · created_by · updated_at · updated_by (맨 끝).
--     불변 행(조정 · 반품·정정)과 로그 테이블은 updated_* 를 두지 않는다. 자연키가 분명한 곳은 그 키가 pk 다.
--   · 코드 text · 수량 numeric(14,3) · 금액 numeric(16,2) · 날짜 date · 시각 timestamptz · 상태는 한글 check.
--   · 데이터가 있는 DB 에 컬럼을 더할 때는 ALTER 로 반영하고 여기서도 그 테이블의 맨 끝에 적는다.
--
-- 영역 → 테이블 (스펙 §4.1)
--   BAS  기준정보    item · customer · warehouse · location
--   STD  인쇄 기준   spec_sheet · standard · plate · plate_usage · artwork · sample_sheet · exception_item
--   WO   작업지시    production_request · work_order · work_sequence
--   MAT  자재·입고   material_receipt · material_lot · material_issue · material_issue_line · product_receipt · product_lot
--   PRD  생산일보    production_daily
--   INS  검사일보    inspection_daily
--   QC   품질 검사   incoming_inspection · product_inspection
--   INV  재고        lot_stock · stock_move · stock_adjust
--   SHP  출하        shipment_order · shipment_line · shipment_adjust
--   COL  수금리포트  erp_upload_batch · erp_upload_row · erp_customer_map · erp_column_map
--   RPT  대시보드    data_query_log
--   DOC  문서관리    doc_account_map · sso_token
--   HOME 내 업무     notification · notification_setting
--   SYS  시스템      sys_role · sys_user · sys_permission · sys_common_code · sys_access_log · sys_change_log
--                    sys_number_rule · sys_number_seq · sys_ai_call_log
--
-- 추적 척추 (완료 기준 — 스펙 §4.2):
--   material_lot ─(material_issue_line.material_lot_id · work_order_id)→ work_order
--   work_order   ─(product_receipt.work_order_id · product_lot_id)→ product_lot
--   product_lot  ─(shipment_line.product_lot_id · shipment_order_id)→ shipment_order
--   분할 LOT = product_lot.parent_lot_id(material_lot.parent_lot_id) + stock_move(분할) 행

-- ════════════════════════════════════════════════════════════════════
-- SYS 시스템 — 역할 · 사용자 (업무 테이블이 참조하므로 먼저 만든다)
-- ════════════════════════════════════════════════════════════════════

-- @table sys_role | SYS | 역할(부서) — 정본 8부서. 역할을 늘리려면 행을 넣는다
create table sys_role (
    role_code   text primary key,                                    -- 부서 코드 (SL · PR · SH · DS · AC · ST · EX · ADM)
    role_name   text not null,                                       -- 부서 이름 (영업부 · 생산부 · …)
    sort_no     integer not null default 0,                          -- 표시 순서 (권한 표의 열 순서)
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint sys_role_name_uq unique (role_name),
    constraint sys_role_use_chk check (use_yn in ('Y', 'N'))
);

-- @table sys_user | SYS | 사용자 계정 — 퇴사자는 지우지 않고 중지로 둔다(SYS-010)
create table sys_user (
    user_id           bigint generated always as identity primary key, -- 내부 키
    login_id          text not null,                                 -- 로그인 ID (사번)
    user_name         text not null,                                 -- 이름
    password_hash     text not null,                                 -- 비밀번호 해시 (PBKDF2 · 화면에 내보내지 않는다)
    role_code         text not null references sys_role (role_code), -- 부서(역할) — 요청마다 DB 에서 읽는다
    status            text not null default '정상',                  -- 정상 | 잠금 | 중지. 정상만 로그인한다
    fail_count        integer not null default 0,                    -- 연속 로그인 실패 횟수
    last_login_at     timestamptz,                                   -- 마지막 로그인
    session_epoch     integer not null default 0,                    -- 세션 판 번호 — 상태·비밀번호가 바뀌면 트리거가 +1. 로그인 때의 값과 다른 세션은 무효
    revoked_sessions  jsonb not null default '{}'::jsonb,            -- 로그아웃한 세션 ID → 로그아웃 시각(epoch 초)
    created_at        timestamptz not null default now(),            -- 등록 일시
    created_by        text,                                          -- 등록자 login_id
    updated_at        timestamptz,                                   -- 수정 일시
    updated_by        text,                                          -- 수정자 login_id
    constraint sys_user_login_uq unique (login_id),
    constraint sys_user_status_chk check (status in ('정상', '잠금', '중지'))
);

-- ════════════════════════════════════════════════════════════════════
-- BAS 기준정보 — 품목 · 거래처 · 창고 · 위치
-- ════════════════════════════════════════════════════════════════════

-- @table item | BAS | 품목 — 제품과 원자재를 한 테이블에 구분으로. 품목 코드는 바꾸지 않는다
create table item (
    id          bigserial primary key,                               -- 내부 키
    item_code   text not null,                                       -- 품목 코드 (중복 금지 · 수정 불가)
    item_name   text not null,                                       -- 품목명
    item_type   text not null,                                       -- 구분: 제품 | 원자재
    spec        text,                                                -- 규격 (글자 그대로 — 값은 받은 적 없다)
    unit        text,                                                -- 단위
    note        text,                                                -- 비고
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N — N 이면 의뢰·입고·출하 지시에서 고를 수 없다
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint item_code_uq unique (item_code),
    constraint item_type_chk check (item_type in ('제품', '원자재')),
    constraint item_use_chk check (use_yn in ('Y', 'N'))
);

-- @table customer | BAS | 거래처 — 의뢰·출하의 상대. ERP 거래처와는 erp_customer_map 으로 잇는다
create table customer (
    id             bigserial primary key,                            -- 내부 키
    customer_code  text not null,                                    -- 거래처 코드 (중복 금지 · 수정 불가)
    customer_name  text not null,                                    -- 거래처명
    contact_name   text,                                             -- 담당자
    phone          text,                                             -- 연락처
    address        text,                                             -- 주소
    note           text,                                             -- 비고
    use_yn         text not null default 'Y',                        -- 사용 여부 Y | N
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint customer_code_uq unique (customer_code),
    constraint customer_use_chk check (use_yn in ('Y', 'N'))
);

-- @table warehouse | BAS | 창고
create table warehouse (
    id              bigserial primary key,                           -- 내부 키
    warehouse_code  text not null,                                   -- 창고 코드 (중복 금지 · 수정 불가)
    warehouse_name  text not null,                                   -- 창고명
    note            text,                                            -- 비고
    use_yn          text not null default 'Y',                       -- 사용 여부 Y | N
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text,                                            -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint warehouse_code_uq unique (warehouse_code),
    constraint warehouse_use_chk check (use_yn in ('Y', 'N'))
);

-- @table location | BAS | 위치(랙·구역) — 창고 아래에 둔다. 재고(lot_stock)가 남은 위치는 지울 수 없다
create table location (
    id             bigserial primary key,                            -- 내부 키
    warehouse_id   bigint not null references warehouse (id),        -- 창고
    location_code  text not null,                                    -- 위치 코드 (창고 안에서 중복 금지)
    location_name  text not null,                                    -- 위치명
    use_yn         text not null default 'Y',                        -- 사용 여부 Y | N
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint location_code_uq unique (warehouse_id, location_code),
    constraint location_use_chk check (use_yn in ('Y', 'N'))
);

-- ════════════════════════════════════════════════════════════════════
-- STD 인쇄 기준 — 사양 · 표준 · 판 · 시안 · 견본서 · 예외제품 (판 사용 이력은 WO 뒤에)
-- ════════════════════════════════════════════════════════════════════

-- @table spec_sheet | STD | 제조사양기준서 — 제품별 인쇄 사양. 생산지시서가 불러온다
create table spec_sheet (
    id          bigserial primary key,                               -- 내부 키
    item_id     bigint not null references item (id),                -- 제품 (BAS-010)
    revision    integer not null default 1,                          -- 개정 차수
    title       text not null,                                       -- 제목
    content     jsonb not null default '{}'::jsonb,                  -- 사양 항목 → 값 (양식 미수집 — 항목 이름을 정하지 않는다)
    note        text,                                                -- 비고
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N — N 이면 지시서에서 불러오지 않는다
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint spec_sheet_rev_uq unique (item_id, revision),
    constraint spec_sheet_use_chk check (use_yn in ('Y', 'N'))
);

-- @table standard | STD | 표준 조건 — 등록·조회만 한다. 적용 규칙은 미확정 (D-519)
create table standard (
    id             bigserial primary key,                            -- 내부 키
    standard_code  text not null,                                    -- 표준 코드 (중복 금지)
    standard_name  text not null,                                    -- 표준명
    content        jsonb not null default '{}'::jsonb,               -- 조건 항목 → 값 (FINE_MES 화면 미수집)
    note           text,                                             -- 비고
    use_yn         text not null default 'Y',                        -- 사용 여부 Y | N
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint standard_code_uq unique (standard_code),
    constraint standard_use_chk check (use_yn in ('Y', 'N'))
);

-- @table plate | STD | 인쇄 판 — 보유 판. 사용 이력은 plate_usage
create table plate (
    id          bigserial primary key,                               -- 내부 키
    plate_code  text not null,                                       -- 판 코드 (중복 금지 · 수정 불가)
    plate_name  text not null,                                       -- 판 이름
    item_id     bigint references item (id),                         -- 제품 (없을 수 있다)
    made_on     date,                                                -- 제작일
    storage     text,                                                -- 보관 위치 (글자)
    note        text,                                                -- 비고
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint plate_code_uq unique (plate_code),
    constraint plate_use_chk check (use_yn in ('Y', 'N'))
);

-- @table artwork | STD | 시안 이미지 — 제품에 연결해 작업지시와 함께 본다
create table artwork (
    id            bigserial primary key,                             -- 내부 키
    item_id       bigint not null references item (id),              -- 제품
    title         text not null,                                     -- 시안 이름
    version       integer not null default 1,                        -- 시안 차수
    file_name     text not null,                                     -- 올린 파일 이름
    content_type  text not null,                                     -- 이미지 형식 (MIME — 이미지가 아니면 422)
    image         bytea not null,                                    -- 이미지 바이트
    note          text,                                              -- 비고
    use_yn        text not null default 'Y',                         -- 사용 여부 Y | N
    created_at    timestamptz not null default now(),                -- 등록 일시
    created_by    text,                                              -- 등록자 login_id
    updated_at    timestamptz,                                       -- 수정 일시
    updated_by    text,                                              -- 수정자 login_id
    constraint artwork_ver_uq unique (item_id, version),
    constraint artwork_image_chk check (content_type like 'image/%'),
    constraint artwork_use_chk check (use_yn in ('Y', 'N'))
);

-- @table sample_sheet | STD | 표준견본서 — 제품별로 만들고 출력한다
create table sample_sheet (
    id          bigserial primary key,                               -- 내부 키
    item_id     bigint not null references item (id),                -- 제품
    title       text not null,                                       -- 제목
    content     jsonb not null default '{}'::jsonb,                  -- 견본서 항목 → 값 (양식 미수집)
    issued_on   date,                                                -- 작성일
    note        text,                                                -- 비고
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint sample_sheet_use_chk check (use_yn in ('Y', 'N'))
);

-- @table exception_item | STD | 예외제품 지정 — 지정·조회만 한다. 적용 규칙은 미확정 (D-519)
create table exception_item (
    id          bigserial primary key,                               -- 내부 키
    item_id     bigint not null references item (id),                -- 제품 (한 제품에 한 행)
    reason      text not null,                                       -- 예외 사유
    note        text,                                                -- 비고
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint exception_item_uq unique (item_id),
    constraint exception_item_use_chk check (use_yn in ('Y', 'N'))
);

-- ════════════════════════════════════════════════════════════════════
-- WO 작업지시 — 의뢰(=수주 키) → 지시 → 작업 순서
-- ════════════════════════════════════════════════════════════════════

-- @table production_request | WO | 생산의뢰 — IA 전체의 「수주」. 의뢰번호가 지시 → 일보 → 제품 입고 → 출하의 연결 키
create table production_request (
    id            bigserial primary key,                             -- 내부 키
    request_no    text not null,                                     -- 의뢰번호 numbering.next("REQ") (형식 D-509 · 수정 불가)
    request_date  date not null default current_date,                -- 의뢰일
    customer_id   bigint not null references customer (id),          -- 거래처
    item_id       bigint not null references item (id),              -- 제품 (사용 중지 품목은 고를 수 없다)
    qty           numeric(14,3) not null,                            -- 의뢰 수량
    due_date      date not null,                                     -- 납기
    status        text not null default '확인대기',                  -- 확인대기 → 확정 → 지시완료 | 취소
    note          text,                                              -- 비고 (발주 내용 요약 — 발주서는 FINE_MES 에 남는다)
    created_at    timestamptz not null default now(),                -- 등록 일시
    created_by    text,                                              -- 등록자 login_id
    updated_at    timestamptz,                                       -- 수정 일시
    updated_by    text,                                              -- 수정자 login_id
    constraint production_request_no_uq unique (request_no),
    constraint production_request_qty_chk check (qty > 0),
    constraint production_request_status_chk check (status in ('확인대기', '확정', '지시완료', '취소'))
);
create index production_request_customer_idx on production_request (customer_id);
create index production_request_due_idx on production_request (due_date);

-- @table work_order | WO | 생산지시서 — 의뢰 한 건에서 만든다. 지시번호는 불출·제품 입고에서 고르는 값
create table work_order (
    id              bigserial primary key,                           -- 내부 키
    work_order_no   text not null,                                   -- 지시번호 numbering.next("WO") (형식 D-509 · 수정 불가)
    request_id      bigint not null references production_request (id), -- 생산의뢰 (수정 불가)
    item_id         bigint not null references item (id),            -- 제품 (의뢰에서 복사)
    spec_sheet_id   bigint references spec_sheet (id),               -- 불러온 제조사양기준서 (STD-010)
    artwork_id      bigint references artwork (id),                  -- 불러온 시안 (STD-040)
    qty             numeric(14,3) not null,                          -- 지시 수량
    equipment_code  text,                                            -- 설비 (sys_common_code 그룹 설비)
    planned_on      date,                                            -- 생산 예정일
    status          text not null default '발행',                    -- 발행 → 진행 → 완료 | 취소
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text,                                            -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint work_order_no_uq unique (work_order_no),
    constraint work_order_qty_chk check (qty > 0),
    constraint work_order_status_chk check (status in ('발행', '진행', '완료', '취소'))
);
create index work_order_request_idx on work_order (request_id);

-- @table work_sequence | WO | 작업 순서 — 설비별로 지시의 순서를 정한다. 같은 설비 안에서 옮긴다
create table work_sequence (
    id              bigserial primary key,                           -- 내부 키
    work_order_id   bigint not null references work_order (id),      -- 생산지시 (한 지시에 한 행)
    equipment_code  text not null,                                   -- 설비 (sys_common_code 그룹 설비)
    seq_no          integer not null,                                -- 설비 안의 순서 (1부터)
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text,                                            -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint work_sequence_order_uq unique (work_order_id),
    constraint work_sequence_slot_uq unique (equipment_code, seq_no) deferrable initially deferred,
    constraint work_sequence_seq_chk check (seq_no > 0)
);

-- @table plate_usage | STD | 판 사용 이력 — 판을 쓴 지시·날짜 한 행 (지시를 참조하므로 WO 뒤에 만든다)
create table plate_usage (
    id             bigserial primary key,                            -- 내부 키
    plate_id       bigint not null references plate (id),            -- 판
    work_order_id  bigint references work_order (id),                -- 사용한 생산지시 (없을 수 있다)
    used_on        date not null,                                    -- 사용일
    note           text,                                             -- 비고
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text                                              -- 수정자 login_id
);
create index plate_usage_plate_idx on plate_usage (plate_id);

-- ════════════════════════════════════════════════════════════════════
-- MAT 자재·입고 — 원자재 입고 LOT · 불출 · 제품 LOT · 제품 입고 (추적 척추의 몸통)
-- 입고 행 자체가 사실이라 상태가 없다. 취소는 지우지 않고 canceled_at 으로 남긴다(MAT-040)
-- ════════════════════════════════════════════════════════════════════

-- @table material_receipt | MAT | 원자재 입고 헤더 — 공급사 · 입고일. LOT 는 material_lot 행
create table material_receipt (
    id             bigserial primary key,                            -- 내부 키
    supplier_name  text not null,                                    -- 공급사 (글자 — 공급사 기준정보는 정본에 없다)
    received_on    date not null default current_date,               -- 입고일
    note           text,                                             -- 비고
    canceled_at    timestamptz,                                      -- 취소 일시 (지우지 않고 표시만 — MAT-040)
    canceled_by    text,                                             -- 취소자 login_id
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text                                              -- 수정자 login_id
);

-- @table material_lot | MAT | 원자재 입고 LOT — 추적 척추의 맨 앞. 입고 직후 lot_stock 에 검사대기로 잡힌다
create table material_lot (
    id               bigserial primary key,                          -- 내부 키
    lot_no           text not null,                                  -- 입고 LOT 번호 numbering.next("MLOT") · 분할 LOT 는 원 번호 + -01 (D-509 · 수정 불가)
    receipt_id       bigint not null references material_receipt (id), -- 입고 헤더
    item_id          bigint not null references item (id),           -- 원자재 품목
    qty              numeric(14,3) not null,                         -- 입고 수량 (분할 LOT 는 나눈 수량). 현재고는 lot_stock
    supplier_lot_no  text,                                           -- 공급사 LOT 번호
    parent_lot_id    bigint references material_lot (id),            -- 분할 원 LOT (INV-020) — 없으면 입고 LOT
    canceled_at      timestamptz,                                    -- 취소 일시
    canceled_by      text,                                           -- 취소자 login_id
    created_at       timestamptz not null default now(),             -- 등록 일시
    created_by       text,                                           -- 등록자 login_id
    updated_at       timestamptz,                                    -- 수정 일시
    updated_by       text,                                           -- 수정자 login_id
    constraint material_lot_no_uq unique (lot_no),
    constraint material_lot_qty_chk check (qty > 0),
    constraint material_lot_parent_chk check (parent_lot_id is distinct from id)
);
create index material_lot_receipt_idx on material_lot (receipt_id);
create index material_lot_parent_idx on material_lot (parent_lot_id);

-- @table material_issue | MAT | 불출 헤더 — 불출일. LOT·지시·수량은 material_issue_line
create table material_issue (
    id           bigserial primary key,                              -- 내부 키
    issued_on    date not null default current_date,                 -- 불출일
    note         text,                                               -- 비고
    canceled_at  timestamptz,                                        -- 취소 일시 (지우지 않고 표시만 — MAT-040)
    canceled_by  text,                                               -- 취소자 login_id
    created_at   timestamptz not null default now(),                 -- 등록 일시
    created_by   text,                                               -- 등록자 login_id
    updated_at   timestamptz,                                        -- 수정 일시
    updated_by   text                                                -- 수정자 login_id
);

-- @table material_issue_line | MAT | 불출 행 — 원자재 LOT → 생산지시. 추적 척추 첫 고리 (가용 LOT 만 · 가용 수량 안에서)
create table material_issue_line (
    id               bigserial primary key,                          -- 내부 키
    issue_id         bigint not null references material_issue (id), -- 불출 헤더
    material_lot_id  bigint not null references material_lot (id),   -- 불출한 원자재 LOT (검사대기·보류 LOT 는 422)
    work_order_id    bigint not null references work_order (id),     -- 생산지시 (지시서 목록에서 고른다)
    location_id      bigint not null references location (id),       -- 꺼낸 위치 (lot_stock 의 키)
    qty              numeric(14,3) not null,                         -- 불출 수량 (가용 수량 이하)
    created_at       timestamptz not null default now(),             -- 등록 일시
    created_by       text,                                           -- 등록자 login_id
    updated_at       timestamptz,                                    -- 수정 일시
    updated_by       text,                                           -- 수정자 login_id
    constraint material_issue_line_qty_chk check (qty > 0)
);
create index material_issue_line_issue_idx on material_issue_line (issue_id);
create index material_issue_line_lot_idx on material_issue_line (material_lot_id);
create index material_issue_line_wo_idx on material_issue_line (work_order_id);

-- @table product_lot | MAT | 제품 LOT — 지시번호와 묶여 LOT 추적에 쓰인다. 분할 LOT 는 parent_lot_id + stock_move
create table product_lot (
    id             bigserial primary key,                            -- 내부 키
    lot_no         text not null,                                    -- 제품 LOT 번호 numbering.next("PLOT") · 분할 LOT 는 원 번호 + -01 (D-509 · 수정 불가)
    item_id        bigint not null references item (id),             -- 제품 품목
    work_order_id  bigint not null references work_order (id),       -- 생산지시 (분할 LOT 는 원 LOT 의 지시 · 수정 불가)
    parent_lot_id  bigint references product_lot (id),               -- 분할 원 LOT (INV-020) — 없으면 입고 LOT
    qty            numeric(14,3) not null,                           -- 생성 수량 (분할 LOT 는 나눈 수량). 현재고는 lot_stock
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint product_lot_no_uq unique (lot_no),
    constraint product_lot_qty_chk check (qty > 0),
    constraint product_lot_parent_chk check (parent_lot_id is distinct from id)
);
create index product_lot_wo_idx on product_lot (work_order_id);
create index product_lot_parent_idx on product_lot (parent_lot_id);

-- @table product_receipt | MAT | 제품 입고 — 생산지시 → 제품 LOT. 추적 척추 둘째 고리. 기본 수량 = 일보 완료 수량
create table product_receipt (
    id              bigserial primary key,                           -- 내부 키
    work_order_id   bigint not null references work_order (id),      -- 생산지시 (수정 불가)
    product_lot_id  bigint not null references product_lot (id),     -- 만든 제품 LOT (입고 한 건에 LOT 하나)
    location_id     bigint not null references location (id),        -- 입고 위치 (lot_stock 의 키)
    qty             numeric(14,3) not null,                          -- 입고 수량
    received_on     date not null default current_date,              -- 입고일
    note            text,                                            -- 비고
    canceled_at     timestamptz,                                     -- 취소 일시 (지우지 않고 표시만 — MAT-040)
    canceled_by     text,                                            -- 취소자 login_id
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text,                                            -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint product_receipt_lot_uq unique (product_lot_id),
    constraint product_receipt_qty_chk check (qty > 0)
);
create index product_receipt_wo_idx on product_receipt (work_order_id);

-- ════════════════════════════════════════════════════════════════════
-- PRD 생산일보 · INS 검사일보 — 지시 × 일자 (× 설비)
-- ════════════════════════════════════════════════════════════════════

-- @table production_daily | PRD | 생산일보 — 지시 × 일자 × 설비 한 행. 로스율 산식은 미확정 (D-519)
create table production_daily (
    id              bigserial primary key,                           -- 내부 키
    work_order_id   bigint not null references work_order (id),      -- 생산지시 (수정 불가)
    work_date       date not null,                                   -- 일자 (수정 불가)
    equipment_code  text not null,                                   -- 설비 (sys_common_code 그룹 설비 · 수정 불가)
    produced_qty    numeric(14,3) not null default 0,                -- 생산 수량 (투입 기준)
    good_qty        numeric(14,3) not null default 0,                -- 완료(양품) 수량 — 제품 입고의 기본값
    loss_qty        numeric(14,3) not null default 0,                -- 로스 수량
    run_minutes     integer,                                         -- 가동 시간(분) — 가동률 원천
    stop_minutes    integer,                                         -- 정지 시간(분)
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text,                                            -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint production_daily_key_uq unique (work_order_id, work_date, equipment_code),
    constraint production_daily_qty_chk check (produced_qty >= 0 and good_qty >= 0 and loss_qty >= 0),
    constraint production_daily_min_chk check (coalesce(run_minutes, 0) >= 0 and coalesce(stop_minutes, 0) >= 0)
);
create index production_daily_date_idx on production_daily (work_date);

-- @table inspection_daily | INS | 검사일보 — 공정 검사(지시 × 일자). 입고검사·제품검사 판정(QC)과는 다른 기록
create table inspection_daily (
    id             bigserial primary key,                            -- 내부 키
    work_order_id  bigint not null references work_order (id),       -- 생산지시
    work_date      date not null,                                    -- 일자
    inspected_qty  numeric(14,3) not null default 0,                 -- 검사 수량
    defect_qty     numeric(14,3) not null default 0,                 -- 불량 수량 (합)
    defects        jsonb not null default '{}'::jsonb,               -- 불량유형 코드(sys_common_code 그룹 불량유형) → 수량
    note           text,                                             -- 비고
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint inspection_daily_key_uq unique (work_order_id, work_date),
    constraint inspection_daily_qty_chk check (inspected_qty >= 0 and defect_qty >= 0 and defect_qty <= inspected_qty)
);
create index inspection_daily_date_idx on inspection_daily (work_date);

-- ════════════════════════════════════════════════════════════════════
-- QC 품질 검사 — 판정은 새 행. LOT 의 판정 = 가장 큰 seq 행 (D-515)
-- ════════════════════════════════════════════════════════════════════

-- @table incoming_inspection | QC | 입고검사 판정 — 원자재 LOT 마다 차수(seq). 합격 → lot_stock 가용, 불합격 → 보류
create table incoming_inspection (
    id               bigserial primary key,                          -- 내부 키
    material_lot_id  bigint not null references material_lot (id),   -- 원자재 LOT
    seq              integer not null,                               -- 판정 차수 (1 = 첫 판정, 2 이상 = 재판정)
    result           text not null,                                  -- 합격 | 불합격
    items            jsonb not null default '{}'::jsonb,             -- 검사 항목 → 값 (항목 미수집)
    inspected_at     timestamptz not null default now(),             -- 판정 일시
    inspector        text,                                           -- 판정자 login_id
    note             text,                                           -- 비고
    created_at       timestamptz not null default now(),             -- 등록 일시
    created_by       text,                                           -- 등록자 login_id
    updated_at       timestamptz,                                    -- 수정 일시 (판정 행은 고치지 않는다 — 재판정은 새 행)
    updated_by       text,                                           -- 수정자 login_id
    constraint incoming_inspection_seq_uq unique (material_lot_id, seq),
    constraint incoming_inspection_seq_chk check (seq > 0),
    constraint incoming_inspection_result_chk check (result in ('합격', '불합격'))
);

-- @table product_inspection | QC | 제품검사 판정 — 제품 LOT 마다 차수(seq). 미판정·불합격 LOT 는 출하 확정 불가
create table product_inspection (
    id              bigserial primary key,                           -- 내부 키
    product_lot_id  bigint not null references product_lot (id),     -- 제품 LOT
    seq             integer not null,                                -- 판정 차수 (1 = 첫 판정, 2 이상 = 재판정)
    result          text not null,                                   -- 합격 | 불합격
    items           jsonb not null default '{}'::jsonb,              -- 검사 결과 항목 → 값 (항목 미수집)
    inspected_at    timestamptz not null default now(),              -- 판정 일시
    inspector       text,                                            -- 판정자 login_id
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text,                                            -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시 (판정 행은 고치지 않는다 — 재판정은 새 행)
    updated_by      text,                                            -- 수정자 login_id
    constraint product_inspection_seq_uq unique (product_lot_id, seq),
    constraint product_inspection_seq_chk check (seq > 0),
    constraint product_inspection_result_chk check (result in ('합격', '불합격'))
);

-- ════════════════════════════════════════════════════════════════════
-- INV 재고 — LOT × 위치의 현재고 · 이동 · 조정(불변)
-- ════════════════════════════════════════════════════════════════════

-- @table lot_stock | INV | LOT 재고 — (구분, LOT, 위치) 한 행. 가용 수량 = qty − allocated_qty (D-510)
create table lot_stock (
    id             bigserial primary key,                            -- 내부 키
    lot_kind       text not null,                                    -- LOT 구분: 원자재 (material_lot.id) | 제품 (product_lot.id)
    lot_id         bigint not null,                                  -- LOT 키 — lot_kind 가 가리키는 테이블의 id (다형 키라 FK 없음)
    location_id    bigint not null references location (id),         -- 위치
    qty            numeric(14,3) not null,                           -- 현재고 — 입고 +, 불출·이동·출하 확정 −, 조정은 실사 수량으로
    allocated_qty  numeric(14,3) not null default 0,                 -- 출하 지시 할당량 (SHP-010 이 잡고 SHP-020 확정이 qty 와 함께 줄인다)
    status         text not null default '검사대기',                 -- 검사대기 → 가용 | 보류 (QC 판정 · 재판정이 바꾼다)
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text,                                             -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint lot_stock_key_uq unique (lot_kind, lot_id, location_id),
    constraint lot_stock_kind_chk check (lot_kind in ('원자재', '제품')),
    constraint lot_stock_status_chk check (status in ('가용', '검사대기', '보류')),
    constraint lot_stock_qty_chk check (qty >= 0),
    constraint lot_stock_alloc_chk check (allocated_qty >= 0 and allocated_qty <= qty)
);
create index lot_stock_location_idx on lot_stock (location_id);

-- @table stock_move | INV | 재고 이동 — 불출 · 위치 이동 · LOT 분할 · 출하 확정 한 행씩. 분할 LOT 는 source_lot_id 로 원 LOT 에 잇는다
create table stock_move (
    id                bigserial primary key,                         -- 내부 키
    move_kind         text not null,                                 -- 불출 | 불출 취소 | 이동 | 분할 | 출하
    lot_kind          text not null,                                 -- LOT 구분: 원자재 | 제품
    lot_id            bigint not null,                               -- 옮긴 LOT (분할이면 새 LOT)
    source_lot_id     bigint,                                        -- 분할 원 LOT (분할일 때만)
    from_location_id  bigint references location (id),              -- 출발 위치 (없으면 밖에서 들어옴)
    to_location_id    bigint references location (id),              -- 도착 위치 (없으면 밖으로 나감 — 불출·출하)
    qty               numeric(14,3) not null,                        -- 이동 수량 (가용 수량 이하)
    ref_table         text,                                          -- 원천 행의 테이블 (material_issue_line · shipment_order …)
    ref_id            bigint,                                        -- 원천 행의 id
    moved_at          timestamptz not null default now(),            -- 이동 일시
    note              text,                                          -- 비고
    created_at        timestamptz not null default now(),            -- 등록 일시
    created_by        text,                                          -- 등록자 login_id
    updated_at        timestamptz,                                   -- 수정 일시
    updated_by        text,                                          -- 수정자 login_id
    constraint stock_move_kind_chk check (move_kind in ('불출', '불출 취소', '이동', '분할', '출하')),
    constraint stock_move_lot_kind_chk check (lot_kind in ('원자재', '제품')),
    constraint stock_move_qty_chk check (qty > 0),
    constraint stock_move_where_chk check (from_location_id is not null or to_location_id is not null),
    constraint stock_move_split_chk check ((move_kind = '분할') = (source_lot_id is not null))
);
create index stock_move_lot_idx on stock_move (lot_kind, lot_id);
create index stock_move_source_idx on stock_move (lot_kind, source_lot_id) where source_lot_id is not null;

-- @table stock_adjust | INV | 재고 조정 — 실사 수량 · 차이 사유(필수). 불변 이력: UPDATE · DELETE 는 트리거가 막는다
create table stock_adjust (
    id           bigserial primary key,                              -- 내부 키
    lot_kind     text not null,                                      -- LOT 구분: 원자재 | 제품
    lot_id       bigint not null,                                    -- LOT 키
    location_id  bigint not null references location (id),           -- 위치
    book_qty     numeric(14,3) not null,                             -- 조정 전 장부 수량 (lot_stock.qty)
    actual_qty   numeric(14,3) not null,                             -- 실사 수량 — lot_stock.qty 가 이 값이 된다
    diff_qty     numeric(14,3) generated always as (actual_qty - book_qty) stored, -- 차이 = 실사 − 장부
    reason       text not null,                                      -- 차이 사유 (필수 — 빈 글자 금지)
    adjusted_at  timestamptz not null default now(),                 -- 조정 일시
    created_at   timestamptz not null default now(),                 -- 등록 일시
    created_by   text,                                               -- 등록자 login_id
    constraint stock_adjust_kind_chk check (lot_kind in ('원자재', '제품')),
    constraint stock_adjust_qty_chk check (book_qty >= 0 and actual_qty >= 0),
    constraint stock_adjust_reason_chk check (btrim(reason) <> '')
);
create index stock_adjust_lot_idx on stock_adjust (lot_kind, lot_id);

-- ════════════════════════════════════════════════════════════════════
-- SHP 출하 — 출하 지시(할당) → 확정 · 확정 후 반품·정정(불변)
-- ════════════════════════════════════════════════════════════════════

-- @table shipment_order | SHP | 출하 지시 — 영업부가 등록하고 출하실이 확정한다. 의뢰번호가 있으면 납기 준수율을 낸다
create table shipment_order (
    id            bigserial primary key,                             -- 내부 키
    shipment_no   text not null,                                     -- 출하 번호 numbering.next("SHP") (형식 D-509 · 수정 불가)
    request_id    bigint references production_request (id),         -- 생산의뢰 (공정 이관 시 — 없을 수 있다)
    customer_id   bigint not null references customer (id),          -- 거래처
    due_date      date not null,                                     -- 납기
    status        text not null default '지시',                      -- 지시 → 확정 | 취소 (확정된 출하는 고치지 않는다)
    confirmed_at  timestamptz,                                       -- 확정 일시
    confirmed_by  text,                                              -- 확정자 login_id
    note          text,                                              -- 비고
    created_at    timestamptz not null default now(),                -- 등록 일시
    created_by    text,                                              -- 등록자 login_id
    updated_at    timestamptz,                                       -- 수정 일시
    updated_by    text,                                              -- 수정자 login_id
    constraint shipment_order_no_uq unique (shipment_no),
    constraint shipment_order_status_chk check (status in ('지시', '확정', '취소')),
    constraint shipment_order_confirm_chk check ((status = '확정') = (confirmed_at is not null))
);
create index shipment_order_request_idx on shipment_order (request_id);
create index shipment_order_customer_idx on shipment_order (customer_id);

-- @table shipment_line | SHP | 출하 행 — 출하 지시 → 제품 LOT(위치). 추적 척추 마지막 고리. 할당 = 이 행의 qty
create table shipment_line (
    id                 bigserial primary key,                        -- 내부 키
    shipment_order_id  bigint not null references shipment_order (id), -- 출하 지시
    product_lot_id     bigint not null references product_lot (id),  -- 할당한 제품 LOT
    location_id        bigint not null references location (id),     -- 할당한 위치 (lot_stock 의 키)
    qty                numeric(14,3) not null,                       -- 할당·출하 수량 (가용 수량 이하)
    created_at         timestamptz not null default now(),           -- 등록 일시
    created_by         text,                                         -- 등록자 login_id
    updated_at         timestamptz,                                  -- 수정 일시
    updated_by         text,                                         -- 수정자 login_id
    constraint shipment_line_lot_uq unique (shipment_order_id, product_lot_id, location_id),
    constraint shipment_line_qty_chk check (qty > 0)
);
create index shipment_line_lot_idx on shipment_line (product_lot_id);

-- @table shipment_adjust | SHP | 반품·정정 — 확정 후 정정은 이 행으로만. 불변 이력 · 재고는 바꾸지 않는다 (D-515)
create table shipment_adjust (
    id                 bigserial primary key,                        -- 내부 키
    shipment_order_id  bigint not null references shipment_order (id), -- 원 출하 (확정된 출하만)
    kind               text not null,                                -- 구분: 반품 | 정정
    qty                numeric(14,3) not null,                       -- 수량 — 음수 = 반품(줄어든 수량), 양수 = 정정으로 늘어난 수량
    reason             text not null,                                -- 사유 (필수 — 빈 글자 금지)
    product_lot_id     bigint references product_lot (id),           -- 대상 제품 LOT (없을 수 있다)
    created_at         timestamptz not null default now(),           -- 등록 일시
    created_by         text,                                         -- 등록자 login_id
    constraint shipment_adjust_kind_chk check (kind in ('반품', '정정')),
    constraint shipment_adjust_qty_chk check (qty <> 0),
    constraint shipment_adjust_reason_chk check (btrim(reason) <> '')
);
create index shipment_adjust_order_idx on shipment_adjust (shipment_order_id);

-- ════════════════════════════════════════════════════════════════════
-- COL 수금리포트 — ERP 수금현황 업로드 회차 · 행 · 매핑. MES 는 수금을 고치지 않는다
-- ════════════════════════════════════════════════════════════════════

-- @table erp_upload_batch | COL | ERP 업로드 회차 — 같은 기준 기간을 다시 올리면 새 회차가 반영, 이전 회차는 교체로 남는다
create table erp_upload_batch (
    id           bigserial primary key,                              -- 내부 키
    batch_no     text not null,                                      -- 회차 번호 numbering.next("ERP") (형식 D-509)
    period_from  date not null,                                      -- 기준 기간 시작
    period_to    date not null,                                      -- 기준 기간 끝
    round_no     integer not null,                                   -- 그 기간의 회차 (1부터)
    status       text not null default '반영',                       -- 반영 → 교체 (새 회차가 올라오면)
    replaced_by  bigint references erp_upload_batch (id),            -- 이 회차를 교체한 새 회차
    source_file  text not null,                                      -- 올린 파일 이름
    row_count    integer not null default 0,                         -- 읽은 행 수
    error_count  integer not null default 0,                         -- 오류·미매핑 행 수 (반영에서 뺀다)
    uploaded_at  timestamptz not null default now(),                 -- 업로드 일시
    created_at   timestamptz not null default now(),                 -- 등록 일시
    created_by   text,                                               -- 등록자 login_id
    updated_at   timestamptz,                                        -- 수정 일시 (교체 표시)
    updated_by   text,                                               -- 수정자 login_id
    constraint erp_upload_batch_no_uq unique (batch_no),
    constraint erp_upload_batch_round_uq unique (period_from, period_to, round_no),
    constraint erp_upload_batch_status_chk check (status in ('반영', '교체')),
    constraint erp_upload_batch_period_chk check (period_from <= period_to),
    constraint erp_upload_batch_replace_chk check ((status = '교체') = (replaced_by is not null))
);
create unique index erp_upload_batch_live_uq on erp_upload_batch (period_from, period_to) where status = '반영';

-- @table erp_upload_row | COL | ERP 업로드 행 — 원문(raw) · 매핑 적용 값(parsed) · 오류. error 가 있으면 반영에서 뺀다
create table erp_upload_row (
    id          bigserial primary key,                               -- 내부 키
    batch_id    bigint not null references erp_upload_batch (id),    -- 업로드 회차
    row_no      integer not null,                                    -- 엑셀 행 번호
    raw         jsonb not null,                                      -- 원문 열 이름 → 글자 (양식 변환 없이 그대로)
    parsed      jsonb,                                               -- erp_column_map 적용 값 (customer_code · txn_date · sales_amount · collected_amount · balance_amount · method · bill_due_date — D-516)
    error       text,                                                -- 오류 사유 (필수 열 · 형식 · 거래처 미매핑). 있으면 반영 제외
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시 (매핑 뒤 재반영)
    updated_by  text,                                                -- 수정자 login_id
    constraint erp_upload_row_no_uq unique (batch_id, row_no)
);

-- @table erp_customer_map | COL | ERP 거래처코드 ↔ MES 거래처 — 출하(MES)와 수금(ERP)을 잇는 유일한 키
create table erp_customer_map (
    id           bigserial primary key,                              -- 내부 키
    erp_code     text not null,                                      -- ERP 거래처코드 (ERP 코드 하나에 MES 거래처 하나)
    erp_name     text,                                               -- ERP 거래처명 (참고)
    customer_id  bigint not null references customer (id),           -- MES 거래처
    use_yn       text not null default 'Y',                          -- 사용 여부 Y | N
    created_at   timestamptz not null default now(),                 -- 등록 일시
    created_by   text,                                               -- 등록자 login_id
    updated_at   timestamptz,                                        -- 수정 일시
    updated_by   text,                                               -- 수정자 login_id
    constraint erp_customer_map_code_uq unique (erp_code),
    constraint erp_customer_map_use_chk check (use_yn in ('Y', 'N'))
);

-- @table erp_column_map | COL | ERP 엑셀 열 매핑 — 처음 한 번 저장하면 다음 업로드부터 자동 적용 (열 구성 미확정 D-516)
create table erp_column_map (
    id           bigserial primary key,                              -- 내부 키
    field        text not null,                                      -- MES 항목 (customer_code · txn_date · sales_amount · collected_amount · balance_amount · method · bill_due_date)
    column_name  text not null,                                      -- ERP 엑셀의 열 이름
    created_at   timestamptz not null default now(),                 -- 등록 일시
    created_by   text,                                               -- 등록자 login_id
    updated_at   timestamptz,                                        -- 수정 일시
    updated_by   text,                                               -- 수정자 login_id
    constraint erp_column_map_field_uq unique (field)
);

-- ════════════════════════════════════════════════════════════════════
-- SYS 시스템 — 권한 · 공통코드 · 로그 · 채번 · AI 호출
-- ════════════════════════════════════════════════════════════════════

-- @table sys_permission | SYS | 권한 칸 — 부서 × 화면 한 칸이 한 행 (W | R). 행이 없으면 권한 없음. 코드가 아니라 데이터다
create table sys_permission (
    role_code   text not null references sys_role (role_code) on delete cascade, -- 부서
    screen_id   text not null,                                       -- 화면 ID (nav.py · 정본 그대로)
    level       text not null,                                       -- W = 처리·조회 | R = 조회
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint sys_permission_pk primary key (role_code, screen_id),
    constraint sys_permission_level_chk check (level in ('W', 'R'))
);

-- @table sys_common_code | SYS | 공통코드 — 설비 · 불량유형 · 수금수단. 참조가 있으면 지우지 않고 사용 중지
create table sys_common_code (
    id          bigserial primary key,                               -- 내부 키
    group_code  text not null,                                       -- 코드 그룹 (설비 · 불량유형 · 수금수단)
    code        text not null,                                       -- 코드 값 (그룹 안에서 중복 금지)
    code_name   text not null,                                       -- 코드 이름
    sort_no     integer not null default 0,                          -- 표시 순서
    note        text,                                                -- 비고
    use_yn      text not null default 'Y',                           -- 사용 여부 Y | N
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint sys_common_code_uq unique (group_code, code),
    constraint sys_common_code_use_chk check (use_yn in ('Y', 'N'))
);

-- @table sys_access_log | SYS | 접근 로그 — 로그인 성공·실패 · 화면 조회 · SSO 진입 · 오류 (G-18)
create table sys_access_log (
    log_id       bigint generated always as identity primary key,    -- 내부 키
    logged_at    timestamptz not null default now(),                 -- 일시 (언제)
    log_type     text not null,                                      -- 구분: 로그인 | 조회 | 변경 | 오류 | SSO
    login_id     text,                                               -- 누가 (실패한 로그인은 입력한 ID)
    role_code    text,                                               -- 그때의 부서
    method       text,                                               -- HTTP 메서드
    path         text,                                               -- 경로
    screen_id    text,                                               -- 화면 ID (nav.py)
    function_id  text,                                               -- 기능 ID (function-list.md)
    target       text,                                               -- 무엇을 (테이블·업무 번호)
    result       text not null,                                      -- 성공 | 실패
    detail       text,                                               -- 내용
    client_ip    text,                                               -- 접속 IP
    constraint sys_access_log_type_chk check (log_type in ('로그인', '조회', '변경', '오류', 'SSO')),
    constraint sys_access_log_result_chk check (result in ('성공', '실패'))
);
create index sys_access_log_at_idx on sys_access_log (logged_at desc);

-- @table sys_change_log | SYS | 데이터 변경 로그 — 쓰기 성공 직후 audit.log_change 가 한 행 (누가 · 언제 · 무엇을)
create table sys_change_log (
    id           bigserial primary key,                              -- 내부 키
    changed_at   timestamptz not null default now(),                 -- 일시
    login_id     text not null,                                      -- 누가
    role_code    text,                                               -- 그때의 부서
    function_id  text not null,                                      -- 기능 ID (function-list.md)
    screen_id    text,                                               -- 화면 ID
    method       text,                                               -- HTTP 메서드
    path         text,                                               -- 경로
    target       text not null,                                      -- 무엇을 (`테이블:업무 번호`)
    detail       text,                                               -- 내용
    client_ip    text                                                -- 접속 IP
);
create index sys_change_log_at_idx on sys_change_log (changed_at desc);

-- @table sys_number_rule | SYS | 채번 형식 — 번호 종류별 한 행 (REQ · WO · MLOT · PLOT · SHP · ERP · DQ). 형식은 코드가 아니라 이 행이다 (D-509)
create table sys_number_rule (
    seq_kind     text primary key,                                   -- 번호 종류: REQ | WO | MLOT | PLOT | SHP | ERP | DQ
    prefix       text not null default '',                           -- 접두 글자 (예시 — D-509)
    date_format  text not null default '',                           -- 날짜 부분 형식 (to_char 형식 · 빈 글자면 날짜 없음)
    seq_digits   integer not null,                                   -- 일련번호 자릿수
    note         text,                                               -- 비고 (가설 형식의 근거)
    updated_at   timestamptz,                                        -- 수정 일시
    updated_by   text,                                               -- 수정자 login_id
    constraint sys_number_rule_digits_chk check (seq_digits between 1 and 10)
);

-- @table sys_number_seq | SYS | 채번 카운터 — (번호 종류, 범위) 마다 마지막 일련번호
create table sys_number_seq (
    seq_kind    text not null,                                       -- 번호 종류
    seq_scope   text not null default '',                            -- 범위 (날짜 부분 값 · 날짜가 바뀌면 1부터)
    last_value  bigint not null,                                     -- 마지막으로 내준 일련번호
    constraint sys_number_seq_pk primary key (seq_kind, seq_scope)
);

-- @table sys_ai_call_log | SYS | AI 호출 로그 — 모든 AI 호출 한 행 (데이터 질의의 SQL 생성 등 · D-513)
create table sys_ai_call_log (
    id          bigserial primary key,                               -- 내부 키
    kind        text not null,                                       -- 호출 용도 (데이터 질의 등)
    model       text,                                                -- 모델 이름
    ok          boolean not null,                                    -- 성공 여부
    ms          integer,                                             -- 걸린 시간(밀리초)
    error       text,                                                -- 실패 사유 (키 없음 포함 — 키 값은 적지 않는다)
    user_id     bigint references sys_user (user_id),                -- 부른 사용자
    created_at  timestamptz not null default now()                   -- 호출 일시
);
create index sys_ai_call_log_at_idx on sys_ai_call_log (created_at desc);

-- ════════════════════════════════════════════════════════════════════
-- RPT 대시보드 — 데이터 질의 로그 (대시보드 자체는 테이블이 없다 · D-505)
-- ════════════════════════════════════════════════════════════════════

-- @table data_query_log | RPT | 데이터 질의 로그 — 거부를 포함한 모든 질의 한 행 (D-513)
create table data_query_log (
    id          bigserial primary key,                               -- 내부 키
    query_no    text not null,                                       -- 로그 번호 numbering.next("DQ") (형식 D-509)
    user_id     bigint references sys_user (user_id),                -- 질의한 사용자
    role_code   text,                                                -- 그때의 부서 (부서별 뷰 제한의 근거)
    question    text not null,                                       -- 질문 원문
    sql_text    text,                                                -- 생성된 SQL (AI 실패면 없다)
    ok          boolean not null,                                    -- 실행했는가 (검증 거부·실패는 false)
    row_count   integer,                                             -- 돌려준 행 수
    error       text,                                                -- 거부·실패 사유
    ms          integer,                                             -- 걸린 시간(밀리초)
    created_at  timestamptz not null default now(),                  -- 질의 일시
    constraint data_query_log_no_uq unique (query_no)
);

-- ════════════════════════════════════════════════════════════════════
-- DOC 문서관리 — 계정 매핑 · 일회용 SSO 토큰 (D-514)
-- ════════════════════════════════════════════════════════════════════

-- @table doc_account_map | DOC | MES 사용자 ↔ 문서관리 계정 ID (1:1). 매핑이 없으면 SSO 토큰을 발급하지 않는다
create table doc_account_map (
    id          bigserial primary key,                               -- 내부 키
    user_id     bigint not null references sys_user (user_id),       -- MES 사용자
    account_id  text not null,                                       -- 문서관리 계정 ID
    active      boolean not null default true,                       -- 사용 여부 (삭제 대신 false)
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint doc_account_map_user_uq unique (user_id),
    constraint doc_account_map_account_uq unique (account_id)
);

-- @table sso_token | DOC | 일회용 SSO 토큰 — jti · 만료(60초) · 사용 시각. 재사용을 막는다 (D-514)
create table sso_token (
    jti         uuid primary key,                                    -- 토큰 ID
    user_id     bigint not null references sys_user (user_id),       -- 발급받은 사용자
    account_id  text not null,                                       -- 넘긴 문서관리 계정 ID
    issued_at   timestamptz not null default now(),                  -- 발급 시각
    expires_at  timestamptz not null,                                -- 만료 시각 (발급 + 60초)
    used_at     timestamptz,                                         -- 사용 시각 (한 번만 — 있으면 재사용 거부)
    created_at  timestamptz not null default now(),                  -- 등록 일시
    constraint sso_token_expiry_chk check (expires_at > issued_at)
);

-- ════════════════════════════════════════════════════════════════════
-- HOME 내 업무 — 알림 (부서마다 1행 · D-522) · 개인 알림 설정. 할 일은 저장하지 않고 질의로 센다
-- ════════════════════════════════════════════════════════════════════

-- @table notification | HOME | 알림 — 수신 부서마다 1행. (dedupe_key, to_role) 유일. 한 사람이 처리하면 같은 부서에 처리됨 (D-511 · D-522)
create table notification (
    id          bigserial primary key,                               -- 내부 키
    event_key   text not null,                                       -- 이벤트 키 (notify.EVENTS — request_created · … 9종)
    to_role     text not null references sys_role (role_code),       -- 수신 부서
    link        text,                                                -- 눌렀을 때 여는 화면 경로
    dedupe_key  text not null,                                       -- 중복 방지 키 (같은 키 재발생은 무시)
    message     text not null,                                       -- 알림 문장
    handled_at  timestamptz,                                         -- 처리 일시 (부서 안 누구든 처리하면 채운다)
    handled_by  text,                                                -- 처리자 login_id
    created_at  timestamptz not null default now(),                  -- 발생 일시
    constraint notification_dedupe_uq unique (dedupe_key, to_role),
    constraint notification_handled_chk check ((handled_at is null) = (handled_by is null))
);
create index notification_inbox_idx on notification (to_role, handled_at);

-- @table notification_setting | HOME | 개인 추가 알림 설정 — 부서 기본 알림은 끌 수 없다. 메일·메신저는 미확정 (D-518)
create table notification_setting (
    id          bigserial primary key,                               -- 내부 키
    user_id     bigint not null references sys_user (user_id),       -- 사용자
    event_key   text not null,                                       -- 이벤트 키
    enabled     boolean not null default true,                       -- 켜짐 여부
    created_at  timestamptz not null default now(),                  -- 등록 일시
    created_by  text,                                                -- 등록자 login_id
    updated_at  timestamptz,                                         -- 수정 일시
    updated_by  text,                                                -- 수정자 login_id
    constraint notification_setting_uq unique (user_id, event_key)
);

-- ════════════════════════════════════════════════════════════════════
-- 트리거
-- ════════════════════════════════════════════════════════════════════

-- 세션 무효화: 계정의 상태나 비밀번호가 바뀌면 그 계정의 살아 있는 세션을 전부 끊는다. 역할·이름 변경은 올리지 않는다(요청마다 DB 에서 다시 읽는다).
create function sys_user_session_guard() returns trigger
language plpgsql as $$
begin
    if new.status is distinct from old.status or new.password_hash is distinct from old.password_hash then
        new.session_epoch := old.session_epoch + 1;
    end if;
    return new;
end;
$$;

create trigger sys_user_session_epoch_trg
    before update on sys_user
    for each row execute function sys_user_session_guard();

-- 불변 이력: 재고 조정(INV-030 「조정 이력은 수정·삭제하지 않는다」) · 반품·정정(SHP-020 · D-515) 행은 고치거나 지우지 않는다.
create function append_only_guard() returns trigger
language plpgsql as $$
begin
    raise exception '불변 이력입니다 — %.% 행은 % 할 수 없다', tg_table_schema, tg_table_name, tg_op;
end;
$$;

create trigger stock_adjust_append_only_trg
    before update or delete on stock_adjust
    for each row execute function append_only_guard();

create trigger shipment_adjust_append_only_trg
    before update or delete on shipment_adjust
    for each row execute function append_only_guard();

-- ════════════════════════════════════════════════════════════════════
-- 뷰 — 저장하지 않고 계산한다 (읽기 전용). v_dq_* 는 데이터 질의(RPT-130)의 허용 뷰 8 (D-513)
-- 수량 합은 취소 표시된 입고 행을 빼고, 출하는 확정된 출하만 센다.
-- ════════════════════════════════════════════════════════════════════

-- @view v_work_order_status | 지시별 공정 상태 (WO-040) — 지시 수량 · 일보 완료 합 · 제품 입고 합 · 출하 합 · 상태
create view v_work_order_status as
select w.id as work_order_id,
       w.work_order_no,
       r.id as request_id,
       r.request_no,
       w.item_id,
       w.qty as order_qty,
       coalesce(d.good_qty, 0) as daily_good_qty,
       coalesce(pr.receipt_qty, 0) as receipt_qty,
       coalesce(s.shipped_qty, 0) as shipped_qty,
       w.status
  from work_order w
  join production_request r on r.id = w.request_id
  left join (select work_order_id, sum(good_qty) as good_qty
               from production_daily group by work_order_id) d on d.work_order_id = w.id
  left join (select work_order_id, sum(qty) as receipt_qty
               from product_receipt where canceled_at is null group by work_order_id) pr on pr.work_order_id = w.id
  left join (select pl.work_order_id, sum(sl.qty) as shipped_qty
               from shipment_line sl
               join shipment_order so on so.id = sl.shipment_order_id and so.status = '확정'
               join product_lot pl on pl.id = sl.product_lot_id
              group by pl.work_order_id) s on s.work_order_id = w.id;

-- @view v_dq_orders | 데이터 질의 — 수주(=생산의뢰)
create view v_dq_orders as
select r.request_no,
       r.request_date,
       c.customer_code,
       c.customer_name,
       i.item_code,
       i.item_name,
       r.qty,
       r.due_date,
       r.status
  from production_request r
  join customer c on c.id = r.customer_id
  join item i on i.id = r.item_id;

-- @view v_dq_work_orders | 데이터 질의 — 생산지시와 진행 수량
create view v_dq_work_orders as
select v.work_order_no,
       v.request_no,
       i.item_code,
       i.item_name,
       w.equipment_code,
       w.planned_on,
       v.order_qty,
       v.daily_good_qty,
       v.receipt_qty,
       v.shipped_qty,
       v.status
  from v_work_order_status v
  join work_order w on w.id = v.work_order_id
  join item i on i.id = v.item_id;

-- @view v_dq_stock | 데이터 질의 — LOT × 위치 재고 (가용 = 현재고 − 할당)
create view v_dq_stock as
select s.lot_kind,
       coalesce(m.lot_no, p.lot_no) as lot_no,
       i.item_code,
       i.item_name,
       wh.warehouse_code,
       l.location_code,
       s.qty,
       s.allocated_qty,
       s.qty - s.allocated_qty as available_qty,
       s.status
  from lot_stock s
  left join material_lot m on s.lot_kind = '원자재' and m.id = s.lot_id
  left join product_lot p on s.lot_kind = '제품' and p.id = s.lot_id
  join item i on i.id = coalesce(m.item_id, p.item_id)
  join location l on l.id = s.location_id
  join warehouse wh on wh.id = l.warehouse_id;

-- @view v_dq_shipments | 데이터 질의 — 출하 지시 행 (LOT · 수량 · 납기 · 확정)
create view v_dq_shipments as
select so.shipment_no,
       r.request_no,
       c.customer_code,
       c.customer_name,
       so.due_date,
       so.status,
       so.confirmed_at,
       p.lot_no,
       i.item_code,
       i.item_name,
       sl.qty
  from shipment_order so
  join customer c on c.id = so.customer_id
  left join production_request r on r.id = so.request_id
  join shipment_line sl on sl.shipment_order_id = so.id
  join product_lot p on p.id = sl.product_lot_id
  join item i on i.id = p.item_id;

-- @view v_dq_quality | 데이터 질의 — 입고검사 · 제품검사 판정 (is_latest = 그 LOT 의 현재 판정)
create view v_dq_quality as
select '입고검사'::text as inspection_kind,
       m.lot_no,
       i.item_code,
       i.item_name,
       q.seq,
       q.result,
       q.inspected_at,
       q.seq = max(q.seq) over (partition by q.material_lot_id) as is_latest
  from incoming_inspection q
  join material_lot m on m.id = q.material_lot_id
  join item i on i.id = m.item_id
union all
select '제품검사'::text,
       p.lot_no,
       i.item_code,
       i.item_name,
       q.seq,
       q.result,
       q.inspected_at,
       q.seq = max(q.seq) over (partition by q.product_lot_id)
  from product_inspection q
  join product_lot p on p.id = q.product_lot_id
  join item i on i.id = p.item_id;

-- @view v_dq_production_daily | 데이터 질의 — 생산일보 (지시 × 일자 × 설비)
create view v_dq_production_daily as
select d.work_date,
       w.work_order_no,
       i.item_code,
       i.item_name,
       d.equipment_code,
       d.produced_qty,
       d.good_qty,
       d.loss_qty,
       d.run_minutes,
       d.stop_minutes
  from production_daily d
  join work_order w on w.id = d.work_order_id
  join item i on i.id = w.item_id;

-- @view v_dq_collections | 데이터 질의 — 수금 (반영 회차의 오류 없는 행만 · 영업부·회계부·관리자·경영진만 — D-513)
create view v_dq_collections as
select b.batch_no,
       b.period_from,
       b.period_to,
       u.parsed ->> 'customer_code' as erp_customer_code,
       c.customer_code,
       c.customer_name,
       (u.parsed ->> 'txn_date')::date as txn_date,
       (u.parsed ->> 'sales_amount')::numeric(16,2) as sales_amount,
       (u.parsed ->> 'collected_amount')::numeric(16,2) as collected_amount,
       (u.parsed ->> 'balance_amount')::numeric(16,2) as balance_amount,
       u.parsed ->> 'method' as method,
       (u.parsed ->> 'bill_due_date')::date as bill_due_date
  from erp_upload_row u
  join erp_upload_batch b on b.id = u.batch_id and b.status = '반영'
  left join erp_customer_map cm on cm.erp_code = u.parsed ->> 'customer_code'
  left join customer c on c.id = cm.customer_id
 where u.error is null and u.parsed is not null;

-- @view v_dq_receivables | 데이터 질의 — 거래처별 미수 (매출 합 − 수금 합 · 기준일 = 반영 회차의 마지막 기간 끝)
create view v_dq_receivables as
select erp_customer_code,
       customer_code,
       customer_name,
       sum(coalesce(sales_amount, 0)) as sales_amount,
       sum(coalesce(collected_amount, 0)) as collected_amount,
       sum(coalesce(sales_amount, 0)) - sum(coalesce(collected_amount, 0)) as receivable_amount,
       max(txn_date) as last_txn_date,
       max(period_to) as as_of
  from v_dq_collections
 group by erp_customer_code, customer_code, customer_name;
