-- 엘컴화인 MES — DB 스키마 (PostgreSQL 17 · DB lcomfine_db)
--
-- 이 파일이 테이블·컬럼의 **원본**이다 (decisions.md D-08). `contracts/db-schema.md` §4 는 이 파일의 렌더본이다(`make contracts`).
-- 고치는 사람은 아키텍트뿐이다. 개발자는 `progress-devN.md` §3 에 요청을 남긴다(D-22).
--
-- 작성 규칙 — `tools/gen_contracts.py` 가 이 형식을 읽는다:
--   · 테이블 앞 한 줄:  -- @table <이름> | <저장소 D1~D8 또는 SYS> | <설명>
--   · 컬럼 한 줄에 하나, 줄 끝에 `-- 설명`. 제약 줄은 constraint 로 시작한다.
--
-- 저장소 → 테이블 (설계도 §2 D1~D8)
--   D1 기준정보   item · customer · process · equipment · defect_code · plate_spec · anilox · ink_formula · ink_formula_component
--   D2 작업지시   job · job_lot
--   D3 원재료 LOT material_lot
--   D4 조색 기록  color_record · color_record_mix
--   D5 생산 실적  work_result · work_stop · work_scrap · material_input
--   D6 Roll·계보  roll · roll_genealogy
--   D7 품질 검사  inspection · inspection_defect
--   D8 출하       shipment
--   SYS 공통      sys_role · sys_user · sys_permission · sys_access_log · sys_number_rule · sys_number_seq · sys_migration_log

-- ════════════════════════════════════════════════════════════════════
-- D1 기준정보 — P1 이 쓴다 (입력: 품목, 고객, 공정, 설비, 불량코드, 판사양, 아니록스, 잉크조성)
-- ════════════════════════════════════════════════════════════════════

-- @table item | D1 | 품목 — 제품과 원재료를 한 테이블에 구분으로 담는다
create table item (
    item_id      bigint generated always as identity primary key,   -- 내부 키
    item_code    text not null unique,                              -- 품목 코드 (업무 키 · 이관 upsert 기준)
    item_name    text not null,                                     -- 품목명
    item_type    text not null,                                     -- 구분: 제품 | 원재료
    spec         text,                                              -- 규격 (글자 그대로 — 값은 받은 적 없음, D-18)
    unit         text,                                              -- 단위
    use_yn       text not null default 'Y',                         -- 사용 여부 Y | N
    created_at   timestamptz not null default now(),                -- 등록 일시
    created_by   text not null,                                     -- 등록자 login_id
    updated_at   timestamptz,                                       -- 수정 일시
    updated_by   text,                                              -- 수정자 login_id
    constraint item_type_chk check (item_type in ('제품', '원재료')),
    constraint item_use_chk check (use_yn in ('Y', 'N'))
);

-- @table customer | D1 | 고객
create table customer (
    customer_id    bigint generated always as identity primary key, -- 내부 키
    customer_code  text not null unique,                            -- 고객 코드
    customer_name  text not null,                                   -- 고객명
    note           text,                                            -- 비고
    use_yn         text not null default 'Y',                       -- 사용 여부 Y | N
    created_at     timestamptz not null default now(),              -- 등록 일시
    created_by     text not null,                                   -- 등록자 login_id
    updated_at     timestamptz,                                     -- 수정 일시
    updated_by     text,                                            -- 수정자 login_id
    constraint customer_use_chk check (use_yn in ('Y', 'N'))
);

-- @table process | D1 | 공정
create table process (
    process_id    bigint generated always as identity primary key,  -- 내부 키
    process_code  text not null unique,                             -- 공정 코드
    process_name  text not null,                                    -- 공정명
    process_type  text not null,                                    -- 공정 구분: 인쇄 | 후가공 | 슬리팅 | 기타
    sort_no       integer,                                          -- 표시 순서
    use_yn        text not null default 'Y',                        -- 사용 여부 Y | N
    created_at    timestamptz not null default now(),               -- 등록 일시
    created_by    text not null,                                    -- 등록자 login_id
    updated_at    timestamptz,                                      -- 수정 일시
    updated_by    text,                                             -- 수정자 login_id
    constraint process_type_chk check (process_type in ('인쇄', '후가공', '슬리팅', '기타')),
    constraint process_use_chk check (use_yn in ('Y', 'N'))
);

-- @table equipment | D1 | 설비 — 기준정보까지만. 설비 상태·수집값 컬럼은 두지 않는다 (G-12)
create table equipment (
    equipment_id    bigint generated always as identity primary key, -- 내부 키
    equipment_code  text not null unique,                            -- 설비 코드
    equipment_name  text not null,                                   -- 설비명
    process_id      bigint references process (process_id),          -- 이 설비가 속한 공정
    note            text,                                            -- 비고
    use_yn          text not null default 'Y',                       -- 사용 여부 Y | N
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text not null,                                   -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint equipment_use_chk check (use_yn in ('Y', 'N'))
);

-- @table defect_code | D1 | 불량코드 — P7 의 "불량 유형" 이 가리키는 곳
create table defect_code (
    defect_code_id  bigint generated always as identity primary key, -- 내부 키
    defect_code     text not null unique,                            -- 불량 코드
    defect_name     text not null,                                   -- 불량명 (불량 유형)
    defect_group    text,                                            -- 분류
    use_yn          text not null default 'Y',                       -- 사용 여부 Y | N
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text not null,                                   -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint defect_code_use_chk check (use_yn in ('Y', 'N'))
);

-- @table plate_spec | D1 | 판사양 (인쇄 기준)
create table plate_spec (
    plate_spec_id  bigint generated always as identity primary key,  -- 내부 키
    plate_code     text not null unique,                             -- 판 코드
    plate_name     text not null,                                    -- 판명
    item_id        bigint references item (item_id),                 -- 대상 품목(제품)
    color_count    integer,                                          -- 도수 (가설 컬럼 D-18)
    spec_note      text,                                             -- 사양 메모 (글자 그대로)
    use_yn         text not null default 'Y',                        -- 사용 여부 Y | N
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text not null,                                    -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint plate_spec_color_chk check (color_count is null or color_count > 0),
    constraint plate_spec_use_chk check (use_yn in ('Y', 'N'))
);

-- @table anilox | D1 | 아니록스 (인쇄 기준)
create table anilox (
    anilox_id    bigint generated always as identity primary key,    -- 내부 키
    anilox_code  text not null unique,                               -- 아니록스 코드
    anilox_name  text not null,                                      -- 명칭
    line_count   numeric(10,2),                                      -- 선수 (가설 컬럼 D-18)
    cell_volume  numeric(10,3),                                      -- 셀 용적 (가설 컬럼 D-18)
    note         text,                                               -- 비고
    use_yn       text not null default 'Y',                          -- 사용 여부 Y | N
    created_at   timestamptz not null default now(),                 -- 등록 일시
    created_by   text not null,                                      -- 등록자 login_id
    updated_at   timestamptz,                                        -- 수정 일시
    updated_by   text,                                               -- 수정자 login_id
    constraint anilox_use_chk check (use_yn in ('Y', 'N'))
);

-- @table ink_formula | D1 | 잉크조성 (인쇄 기준) — 조색의 기준이 되는 표준 조성
create table ink_formula (
    ink_formula_id  bigint generated always as identity primary key, -- 내부 키
    ink_code        text not null unique,                            -- 잉크 코드
    ink_name        text not null,                                   -- 잉크명
    color_name      text,                                            -- 색 이름
    target_l        numeric(7,2),                                    -- 기준 색상값 L (가설 컬럼 D-18)
    target_a        numeric(7,2),                                    -- 기준 색상값 a
    target_b        numeric(7,2),                                    -- 기준 색상값 b
    note            text,                                            -- 비고
    use_yn          text not null default 'Y',                       -- 사용 여부 Y | N
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text not null,                                   -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint ink_formula_use_chk check (use_yn in ('Y', 'N'))
);

-- @table ink_formula_component | D1 | 잉크조성의 조성 행 (성분·비율)
create table ink_formula_component (
    ink_formula_component_id  bigint generated always as identity primary key,               -- 내부 키
    ink_formula_id            bigint not null references ink_formula (ink_formula_id) on delete cascade, -- 잉크조성
    seq_no                    integer not null,                                              -- 행 순번
    component_name            text not null,                                                 -- 성분명
    ratio_pct                 numeric(6,3) not null,                                         -- 비율 (%)
    constraint ink_formula_component_uq unique (ink_formula_id, seq_no),
    constraint ink_formula_component_ratio_chk check (ratio_pct > 0 and ratio_pct <= 100)
);

-- ════════════════════════════════════════════════════════════════════
-- D2 작업지시 — P2 가 쓴다 (입력: Job 등록, Job-Lot-Roll 매핑 · 참조 D1)
-- ════════════════════════════════════════════════════════════════════

-- @table sales_order | EXT | 수주 — 설계도 밖 확장(D-418). 영업이 받은 수주 한 건. 작업지시가 이 행을 가리킨다(job.sales_order_id)
create table sales_order (
    sales_order_id  bigint generated always as identity primary key, -- 내부 키
    order_no        text not null unique,                            -- 수주 번호 (numbering.next('SALES_ORDER') · 형식 가설 D-418)
    customer_id     bigint not null references customer (customer_id), -- 고객
    item_id         bigint not null references item (item_id),       -- 품목(제품)
    order_qty       numeric(14,3) not null,                          -- 수주 수량
    qty_unit        text not null,                                   -- 수량 단위
    order_date      date not null default current_date,              -- 수주일
    due_date        date not null,                                   -- 납기 (고객 요청)
    customer_po     text,                                            -- 고객 발주 번호 (받은 글자 그대로)
    status          text not null default '등록',                    -- 등록 | 취소 (진행은 저장하지 않고 Job·실적·출하에서 읽는다)
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text not null,                                   -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint sales_order_qty_chk check (order_qty > 0),
    constraint sales_order_status_chk check (status in ('등록', '취소'))
);
create index sales_order_customer_idx on sales_order (customer_id);
create index sales_order_due_idx on sales_order (due_date);

-- @table job | D2 | 작업지시(Job) — Job-Lot-Roll 키의 맨 위
create table job (
    job_id          bigint generated always as identity primary key, -- 내부 키
    job_no          text not null unique,                            -- 작업지시 번호 (numbering.next('JOB') · 형식 D-05)
    item_id         bigint not null references item (item_id),       -- 품목(제품)
    customer_id     bigint not null references customer (customer_id), -- 고객
    plate_spec_id   bigint references plate_spec (plate_spec_id),    -- 판사양
    anilox_id       bigint references anilox (anilox_id),            -- 아니록스
    ink_formula_id  bigint references ink_formula (ink_formula_id),  -- 잉크조성
    equipment_id    bigint references equipment (equipment_id),      -- 계획 설비
    order_qty       numeric(14,3) not null,                          -- 지시 수량
    qty_unit        text not null,                                   -- 수량 단위
    due_date        date not null,                                   -- 납기 (실적 현황 납기 집계의 기준)
    status          text not null default '등록',                    -- 등록 | 완료 | 취소 (진행 여부는 저장하지 않고 D5 에서 읽는다)
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    created_by      text not null,                                   -- 등록자 login_id
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    sales_order_id  bigint references sales_order (sales_order_id),  -- 수주 (설계도 밖 확장 D-418 · 수주 없이 낸 지시는 NULL)
    constraint job_qty_chk check (order_qty > 0),
    constraint job_status_chk check (status in ('등록', '완료', '취소'))
);
create index job_due_idx on job (due_date);
create index job_sales_order_idx on job (sales_order_id);

-- @table job_lot | D2 | 생산 LOT — "Job-Lot-Roll 매핑" 의 Lot 단 (D-10). Job 1 : 생산 LOT N
create table job_lot (
    job_lot_id          bigint generated always as identity primary key, -- 내부 키
    job_id              bigint not null references job (job_id),         -- 작업지시
    lot_no              text not null unique,                            -- 생산 LOT 번호 (numbering.next('JOB_LOT'))
    planned_roll_count  integer,                                         -- 계획 롤 수
    planned_length_m    numeric(14,3),                                   -- 계획 길이 (m)
    note                text,                                            -- 비고
    created_at          timestamptz not null default now(),              -- 등록 일시
    created_by          text not null,                                   -- 등록자 login_id
    updated_at          timestamptz,                                     -- 수정 일시
    updated_by          text,                                            -- 수정자 login_id
    constraint job_lot_roll_chk check (planned_roll_count is null or planned_roll_count > 0),
    constraint job_lot_job_uq unique (job_lot_id, job_id)
);
create index job_lot_job_idx on job_lot (job_id);

-- ════════════════════════════════════════════════════════════════════
-- D3 원재료 LOT — P3 이 쓴다 (입력: 입고 등록, 입고검사 결과 · 참조 D1)
-- ════════════════════════════════════════════════════════════════════

-- @table material_lot | D3 | 원재료 LOT — 입고 1건 = LOT 1개. 계보의 맨 앞 (설계도 §3 그림의 이름 그대로)
create table material_lot (
    material_lot_id  bigint generated always as identity primary key, -- 내부 키
    lot_no           text not null unique,                            -- 원재료 LOT 번호 (numbering.next('MAT_LOT') · 라벨 바코드)
    item_id          bigint not null references item (item_id),       -- 원재료 품목
    supplier_name    text,                                            -- 공급처 (마스터 없음 — 글자, D-18)
    supplier_lot_no  text,                                            -- 공급사 LOT 번호
    received_qty     numeric(14,3) not null,                          -- 입고 수량
    qty_unit         text not null,                                   -- 수량 단위
    received_at      timestamptz not null default now(),              -- 입고 일시
    received_by      text not null,                                   -- 입고 등록자 login_id
    insp_status      text not null default '대기',                    -- 입고검사 결과: 대기 | 합격 | 불합격 (합격만 투입 가능)
    insp_at          timestamptz,                                     -- 입고검사 일시
    insp_by          text,                                            -- 입고검사자 login_id
    insp_note        text,                                            -- 입고검사 비고
    note             text,                                            -- 비고
    created_at       timestamptz not null default now(),              -- 등록 일시
    updated_at       timestamptz,                                     -- 수정 일시
    updated_by       text,                                            -- 수정자 login_id
    constraint material_lot_qty_chk check (received_qty > 0),
    constraint material_lot_insp_chk check (insp_status in ('대기', '합격', '불합격')),
    constraint material_lot_insp_at_chk check ((insp_status = '대기') = (insp_at is null))
);
create index material_lot_item_idx on material_lot (item_id);

-- ════════════════════════════════════════════════════════════════════
-- D4 조색 기록 — P4 가 쓴다 (입력: 색상값, 배합비 · 참조 D2)
-- ════════════════════════════════════════════════════════════════════

-- @table color_record | D4 | 조색 기록 — Job 의 색별·차수별 색상값
create table color_record (
    color_record_id  bigint generated always as identity primary key, -- 내부 키
    job_id           bigint not null references job (job_id),         -- 작업지시 (Job 키)
    ink_formula_id   bigint references ink_formula (ink_formula_id),  -- 기준 잉크조성
    color_name       text not null,                                   -- 색 이름
    seq_no           integer not null default 1,                      -- 차수 (재조색마다 +1)
    color_l          numeric(7,2),                                    -- 색상값 L (가설: Lab, D-18)
    color_a          numeric(7,2),                                    -- 색상값 a
    color_b          numeric(7,2),                                    -- 색상값 b
    note             text,                                            -- 비고
    recorded_at      timestamptz not null default now(),              -- 기록 일시
    recorded_by      text not null,                                   -- 기록자 login_id
    updated_at       timestamptz,                                     -- 수정 일시
    updated_by       text,                                            -- 수정자 login_id
    constraint color_record_uq unique (job_id, color_name, seq_no),
    constraint color_record_seq_chk check (seq_no > 0)
);

-- @table color_record_mix | D4 | 조색 기록의 배합비 행 (성분·비율)
create table color_record_mix (
    color_record_mix_id  bigint generated always as identity primary key,                 -- 내부 키
    color_record_id      bigint not null references color_record (color_record_id) on delete cascade, -- 조색 기록
    seq_no               integer not null,                                                -- 행 순번
    component_name       text not null,                                                   -- 성분명
    ratio_pct            numeric(6,3) not null,                                           -- 배합비 (%)
    constraint color_record_mix_uq unique (color_record_id, seq_no),
    constraint color_record_mix_ratio_chk check (ratio_pct > 0 and ratio_pct <= 100)
);

-- ════════════════════════════════════════════════════════════════════
-- D5 생산 실적 — P5 가 쓴다 (입력: 작업 시작·종료, 정지, 폐기, 자재 투입 스캔 · 참조 D2·D3)
-- ════════════════════════════════════════════════════════════════════

-- @table work_result | D5 | 작업 실적(인쇄) — 시작·종료. 실적 1건 = 인쇄 롤 1개 (D-13)
create table work_result (
    work_result_id  bigint generated always as identity primary key, -- 내부 키 (경로의 work_id)
    job_id          bigint not null references job (job_id),         -- 작업지시 (Job 키)
    job_lot_id      bigint,                                          -- 생산 LOT
    process_id      bigint references process (process_id),          -- 공정
    equipment_id    bigint references equipment (equipment_id),      -- 설비
    status          text not null default '진행',                    -- 진행 | 정지 | 완료
    started_at      timestamptz not null default now(),              -- 작업 시작
    ended_at        timestamptz,                                     -- 작업 종료
    output_qty      numeric(14,3),                                   -- 실적 수량 (종료 때 입력 · 생산 집계의 값)
    qty_unit        text,                                            -- 수량 단위
    worker          text not null,                                   -- 작업자 login_id
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint work_result_job_lot_fk foreign key (job_lot_id, job_id) references job_lot (job_lot_id, job_id),
    constraint work_result_status_chk check (status in ('진행', '정지', '완료')),
    constraint work_result_end_chk check ((status = '완료') = (ended_at is not null)),
    constraint work_result_qty_chk check (output_qty is null or output_qty >= 0)
);
create index work_result_job_idx on work_result (job_id);

-- @table work_stop | D5 | 정지 기록 — 정지 시작과 재개
create table work_stop (
    work_stop_id    bigint generated always as identity primary key, -- 내부 키 (경로의 stop_id)
    work_result_id  bigint not null references work_result (work_result_id), -- 작업 실적
    stop_reason     text not null,                                   -- 정지 사유 (마스터 없음 — 글자, D-18)
    stopped_at      timestamptz not null default now(),              -- 정지 시각
    resumed_at      timestamptz,                                     -- 재개 시각 (비어 있으면 정지 중)
    created_by      text not null,                                   -- 등록자 login_id
    constraint work_stop_time_chk check (resumed_at is null or resumed_at >= stopped_at)
);
create unique index work_stop_open_uq on work_stop (work_result_id) where resumed_at is null;

-- @table work_scrap | D5 | 폐기 기록
create table work_scrap (
    work_scrap_id   bigint generated always as identity primary key, -- 내부 키
    work_result_id  bigint not null references work_result (work_result_id), -- 작업 실적
    scrap_qty       numeric(14,3) not null,                          -- 폐기 수량
    qty_unit        text,                                            -- 수량 단위
    defect_code_id  bigint references defect_code (defect_code_id),  -- 폐기 사유(불량코드)
    reason          text,                                            -- 사유 메모
    scrapped_at     timestamptz not null default now(),              -- 폐기 시각
    created_by      text not null,                                   -- 등록자 login_id
    constraint work_scrap_qty_chk check (scrap_qty > 0)
);
create index work_scrap_work_idx on work_scrap (work_result_id);

-- @table material_input | D5 | 자재 투입 스캔 — 작업 종료 때 인쇄 롤의 계보 `투입` 행이 된다 (D-13)
create table material_input (
    material_input_id  bigint generated always as identity primary key, -- 내부 키
    work_result_id     bigint not null references work_result (work_result_id), -- 작업 실적
    material_lot_id    bigint not null references material_lot (material_lot_id), -- 원재료 LOT (합격만)
    input_qty          numeric(14,3),                                -- 투입량
    qty_unit           text,                                         -- 수량 단위
    scanned_at         timestamptz not null default now(),           -- 스캔 시각
    scanned_by         text not null,                                -- 스캔한 사람 login_id
    constraint material_input_uq unique (work_result_id, material_lot_id),
    constraint material_input_qty_chk check (input_qty is null or input_qty > 0)
);
create index material_input_lot_idx on material_input (material_lot_id);

-- ════════════════════════════════════════════════════════════════════
-- D6 Roll·계보 — P5(인쇄 롤) · P6(후가공·슬리팅) 이 쓴다. `출하` 화살표만 P8 이 lineage 를 거쳐 쓴다 (D-12)
-- ════════════════════════════════════════════════════════════════════

-- @table roll | D6 | 롤 — 인쇄·후가공·슬리팅 롤을 한 테이블에 공정 구분으로. 상태 컬럼은 없다 (v_roll_state)
create table roll (
    roll_id         bigint generated always as identity primary key, -- 내부 키
    roll_no         text not null unique,                            -- 롤 번호 (numbering.next('ROLL') · 라벨 바코드)
    process_type    text not null,                                   -- 공정 구분: 인쇄 | 후가공 | 슬리팅
    job_id          bigint not null references job (job_id),         -- 작업지시 (Job 키)
    job_lot_id      bigint,                                          -- 생산 LOT (Lot 키)
    work_result_id  bigint references work_result (work_result_id),  -- 인쇄 롤을 만든 작업 실적 (D5 키 · 인쇄 롤만)
    equipment_id    bigint references equipment (equipment_id),      -- 가공 실적: 설비
    length_m        numeric(14,3),                                   -- 가공 실적: 길이 m (가설 컬럼 D-18)
    width_mm        numeric(10,2),                                   -- 가공 실적: 폭 mm (슬리팅 분할 폭)
    slit_seq        integer,                                         -- 슬리팅 분할 순번 (1..N)
    produced_at     timestamptz not null default now(),              -- 생산(가공) 일시
    produced_by     text not null,                                   -- 작업자 login_id
    note            text,                                            -- 비고
    created_at      timestamptz not null default now(),              -- 등록 일시
    constraint roll_job_lot_fk foreign key (job_lot_id, job_id) references job_lot (job_lot_id, job_id),
    constraint roll_process_chk check (process_type in ('인쇄', '후가공', '슬리팅')),
    constraint roll_work_chk check (work_result_id is null or process_type = '인쇄'),
    constraint roll_slit_chk check (slit_seq is null or (process_type = '슬리팅' and slit_seq > 0)),
    constraint roll_size_chk check ((length_m is null or length_m >= 0) and (width_mm is null or width_mm > 0)),
    constraint roll_job_uq unique (roll_id, job_id)
);
create unique index roll_work_result_uq on roll (work_result_id) where work_result_id is not null;
create index roll_job_idx on roll (job_id);

-- ════════════════════════════════════════════════════════════════════
-- D8 출하 — P8 이 쓴다 (입력: 출하 등록, 출하 승인, 롤 스캔 · 참조 D6·D7). 계보가 가리키므로 계보보다 먼저 만든다
-- ════════════════════════════════════════════════════════════════════

-- @table shipment | D8 | 출하 LOT — 계보의 맨 끝. 담긴 롤은 roll_genealogy 의 `출하` 행이다 (별도 목록 테이블 없음)
create table shipment (
    shipment_id     bigint generated always as identity primary key, -- 내부 키
    shipment_no     text not null unique,                            -- 출하 LOT 번호 (numbering.next('SHIPMENT'))
    job_id          bigint not null references job (job_id),         -- 작업지시 (Job 키 — 출하 LOT 1 = Job 1, D-16)
    customer_id     bigint not null references customer (customer_id), -- 고객
    ship_date       date not null,                                   -- 출하일 (납기 집계에서 납기와 비교)
    status          text not null default '등록',                    -- 등록 | 승인 | 취소
    registered_at   timestamptz not null default now(),              -- 출하 등록 일시
    registered_by   text not null,                                   -- 출하 등록자 login_id
    approved_at     timestamptz,                                     -- 출하 승인 일시
    approved_by     text,                                            -- 출하 승인자 login_id (관리자)
    coa_no          text unique,                                     -- COA 번호 (승인 때 numbering.next('COA'), D-17)
    coa_issued_at   timestamptz,                                     -- COA 발행 일시
    note            text,                                            -- 비고
    updated_at      timestamptz,                                     -- 수정 일시
    updated_by      text,                                            -- 수정자 login_id
    constraint shipment_status_chk check (status in ('등록', '승인', '취소')),
    constraint shipment_approve_chk check ((status = '승인') = (approved_at is not null)),
    constraint shipment_coa_chk check (coa_no is null or status = '승인')
);
create index shipment_job_idx on shipment (job_id);

-- @table roll_genealogy | D6 | 계보 — 한 행 = 설계도 §3 그림의 화살표 하나 (부모 → 자식). 추적은 이 표를 따라가는 조회다
create table roll_genealogy (
    genealogy_id            bigint generated always as identity primary key,       -- 내부 키
    parent_material_lot_id  bigint references material_lot (material_lot_id),      -- 부모: 원재료 LOT (parent_roll_id 와 둘 중 하나)
    parent_roll_id          bigint references roll (roll_id),                      -- 부모: 롤
    child_roll_id           bigint references roll (roll_id),                      -- 자식: 롤 (child_shipment_id 와 둘 중 하나)
    child_shipment_id       bigint references shipment (shipment_id),              -- 자식: 출하 LOT
    relation                text not null,                                         -- 관계: 투입 | 후가공 | splice | 슬리팅 | 출하
    qty                     numeric(14,3),                                         -- 그 화살표로 넘어간 양 (투입량 등 · 없으면 비움)
    created_at              timestamptz not null default now(),                    -- 기록 일시
    created_by              text not null,                                         -- 기록자 login_id
    constraint roll_genealogy_parent_chk check (num_nonnulls(parent_material_lot_id, parent_roll_id) = 1),
    constraint roll_genealogy_child_chk check (num_nonnulls(child_roll_id, child_shipment_id) = 1),
    constraint roll_genealogy_self_chk check (parent_roll_id is null or child_roll_id is null or parent_roll_id <> child_roll_id),
    constraint roll_genealogy_relation_chk check (relation in ('투입', '후가공', 'splice', '슬리팅', '출하')),
    constraint roll_genealogy_shape_chk check (
        (relation = '투입') = (parent_material_lot_id is not null)
        and (relation = '출하') = (child_shipment_id is not null)
        and (parent_material_lot_id is null or child_roll_id is not null)
    )
);
create unique index roll_genealogy_lot_roll_uq on roll_genealogy (parent_material_lot_id, child_roll_id) where parent_material_lot_id is not null;
create unique index roll_genealogy_roll_roll_uq on roll_genealogy (parent_roll_id, child_roll_id) where parent_roll_id is not null and child_roll_id is not null;
create unique index roll_genealogy_ship_once_uq on roll_genealogy (parent_roll_id) where child_shipment_id is not null;
create index roll_genealogy_child_roll_idx on roll_genealogy (child_roll_id);
create index roll_genealogy_child_ship_idx on roll_genealogy (child_shipment_id);
create index roll_genealogy_parent_roll_idx on roll_genealogy (parent_roll_id);

-- 계보 지킴이 — CHECK 로 못 막는 것 넷을 막는다 (D-11). 위반은 SQLSTATE 23514(check_violation) → 앱은 422.
--   ① 순환: 자식에서 내려가 부모에 닿으면 거부    ② 출하된 롤을 다음 공정의 부모로 쓰기 / 소진된 롤 출하하기
--   ③ 관계와 자식 롤의 공정 구분이 어긋남          ④ 출하: 등록 상태가 아닌 출하에 담기 · 다른 Job 의 롤 담기
-- 계보 행은 고치지 않는다(지우고 다시 넣는다). qty 만 고칠 수 있다.
create function roll_genealogy_guard() returns trigger
language plpgsql as $$
declare
    v_hit       bigint;
    v_child_pt  text;
    v_roll_job  bigint;
    v_ship      record;
begin
    if tg_op = 'UPDATE' then
        if (new.parent_material_lot_id, new.parent_roll_id, new.child_roll_id, new.child_shipment_id, new.relation)
           is distinct from
           (old.parent_material_lot_id, old.parent_roll_id, old.child_roll_id, old.child_shipment_id, old.relation) then
            raise exception '계보 행의 부모·자식·관계는 고칠 수 없다 (genealogy_id=%)', old.genealogy_id
                using errcode = 'check_violation';
        end if;
        return new;
    end if;

    if new.parent_roll_id is not null and new.parent_roll_id = new.child_roll_id then
        raise exception '자기 자신을 부모로 하는 계보는 만들 수 없다 (roll_id=%)', new.parent_roll_id
            using errcode = 'check_violation';
    end if;

    -- 동시에 A→B 와 B→A 가 들어와 서로를 못 보는 경우를 막는다
    perform pg_advisory_xact_lock(hashtext('roll_genealogy'));

    if new.child_roll_id is not null then
        select process_type into v_child_pt from roll where roll_id = new.child_roll_id;
        if (new.relation = '투입' and v_child_pt <> '인쇄')
           or (new.relation in ('후가공', 'splice') and v_child_pt <> '후가공')
           or (new.relation = '슬리팅' and v_child_pt <> '슬리팅') then
            raise exception '관계 % 와 자식 롤의 공정 구분 % 이 맞지 않는다 (roll_id=%)', new.relation, v_child_pt, new.child_roll_id
                using errcode = 'check_violation';
        end if;
    end if;

    if new.parent_roll_id is not null and new.child_roll_id is not null then
        if exists (select 1 from roll_genealogy
                    where parent_roll_id = new.parent_roll_id and child_shipment_id is not null) then
            raise exception '이미 출하된 롤은 다음 공정에 쓸 수 없다 (roll_id=%)', new.parent_roll_id
                using errcode = 'check_violation';
        end if;
        with recursive down (roll_id) as (
            select new.child_roll_id
            union
            select g.child_roll_id
              from roll_genealogy g
              join down d on g.parent_roll_id = d.roll_id
             where g.child_roll_id is not null
        )
        select roll_id into v_hit from down where roll_id = new.parent_roll_id limit 1;
        if v_hit is not null then
            raise exception '계보 순환: 롤 % 은 롤 % 의 자손이다', new.parent_roll_id, new.child_roll_id
                using errcode = 'check_violation';
        end if;
    end if;

    if new.child_shipment_id is not null then
        if exists (select 1 from roll_genealogy
                    where parent_roll_id = new.parent_roll_id and child_roll_id is not null) then
            raise exception '다음 공정에 쓰인(소진) 롤은 출하할 수 없다 (roll_id=%)', new.parent_roll_id
                using errcode = 'check_violation';
        end if;
        select shipment_id, job_id, status into v_ship from shipment where shipment_id = new.child_shipment_id;
        if v_ship.status <> '등록' then
            raise exception '% 상태의 출하에는 롤을 담을 수 없다 (shipment_id=%)', v_ship.status, new.child_shipment_id
                using errcode = 'check_violation';
        end if;
        select job_id into v_roll_job from roll where roll_id = new.parent_roll_id;
        if v_roll_job <> v_ship.job_id then
            raise exception '출하 LOT 과 Job 이 다른 롤이다 (roll_id=%, shipment_id=%)', new.parent_roll_id, new.child_shipment_id
                using errcode = 'check_violation';
        end if;
    end if;
    return new;
end;
$$;

create trigger roll_genealogy_guard_trg
    before insert or update on roll_genealogy
    for each row execute function roll_genealogy_guard();

-- ════════════════════════════════════════════════════════════════════
-- D7 품질 검사 — P7 이 쓴다 (입력: ΔE, 불량 유형·위치, 불량 롤 번호 · 참조 D6)
-- ════════════════════════════════════════════════════════════════════

-- @table inspection | D7 | 검사 결과 — 롤 1개에 여러 번. 최신 검사가 그 롤의 판정이다
create table inspection (
    inspection_id  bigint generated always as identity primary key,  -- 내부 키
    roll_id        bigint not null,                                  -- 검사한 롤 ("불량 롤 번호" 가 가리키는 롤)
    job_id         bigint not null references job (job_id),          -- 작업지시 (롤에서 복사한 Job 키, D-16)
    delta_e        numeric(7,2),                                     -- ΔE (색차)
    result         text not null,                                    -- 판정: 합격 | 불합격
    inspected_at   timestamptz not null default now(),               -- 검사 일시
    inspected_by   text not null,                                    -- 검사자 login_id
    note           text,                                             -- 비고
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    constraint inspection_roll_fk foreign key (roll_id, job_id) references roll (roll_id, job_id),
    constraint inspection_result_chk check (result in ('합격', '불합격')),
    constraint inspection_delta_chk check (delta_e is null or delta_e >= 0)
);
create index inspection_roll_idx on inspection (roll_id, inspected_at desc);
create index inspection_job_idx on inspection (job_id);

-- @table inspection_defect | D7 | 검사의 불량 행 (불량 유형·위치) — 불량 유형별 집계의 원천
create table inspection_defect (
    inspection_defect_id  bigint generated always as identity primary key,             -- 내부 키
    inspection_id         bigint not null references inspection (inspection_id) on delete cascade, -- 검사 결과
    defect_code_id        bigint not null references defect_code (defect_code_id),     -- 불량 유형 (불량코드)
    position              text,                                                        -- 불량 위치 (형식 미정 — 글자, D-18)
    note                  text                                                         -- 비고
);
create index inspection_defect_insp_idx on inspection_defect (inspection_id);
create index inspection_defect_code_idx on inspection_defect (defect_code_id);

-- ════════════════════════════════════════════════════════════════════
-- SYS 공통 — 로그인 · 역할별 권한 · 접근 로그 · 채번 · 이관 기록 (설계도 §4 "공통", D-15). G-05 쓰기 경계 밖
-- ════════════════════════════════════════════════════════════════════

-- @table sys_role | SYS | 역할 — 설계도 §6 의 4역할. 역할을 늘리려면 행을 넣는다 (D-06)
create table sys_role (
    role_code  text primary key,                                     -- 역할 코드 (ADMIN · PROD · QC · FIELD)
    role_name  text not null unique,                                 -- 역할명 (관리자 · 생산 · 품질 · 현장)
    sort_no    integer not null default 0,                           -- 표시 순서 (권한 표의 열 순서)
    use_yn     text not null default 'Y',                            -- 사용 여부 Y | N
    constraint sys_role_use_chk check (use_yn in ('Y', 'N'))
);

-- @table sys_user | SYS | 사용자 계정
create table sys_user (
    user_id        bigint generated always as identity primary key,  -- 내부 키
    login_id       text not null unique,                             -- 로그인 ID
    user_name      text not null,                                    -- 이름
    password_hash  text not null,                                    -- 비밀번호 해시 (PBKDF2 · 화면에 내보내지 않는다)
    role_code      text not null references sys_role (role_code),    -- 역할
    status         text not null default '정상',                     -- 정상 | 잠금 | 중지
    fail_count     integer not null default 0,                       -- 연속 로그인 실패 횟수
    last_login_at  timestamptz,                                      -- 마지막 로그인
    created_at     timestamptz not null default now(),               -- 등록 일시
    created_by     text not null,                                    -- 등록자 login_id
    updated_at     timestamptz,                                      -- 수정 일시
    updated_by     text,                                             -- 수정자 login_id
    session_epoch  integer not null default 0,                       -- 세션 판 번호 — 상태·비밀번호가 바뀌면 트리거가 +1. 로그인 때의 값과 다른 세션은 무효 (D-26)
    revoked_sessions jsonb not null default '{}'::jsonb,             -- 로그아웃한 세션 ID → 로그아웃 시각(epoch 초). 쿠키 수명이 지난 것은 다음 로그아웃 때 지운다 (D-26)
    constraint sys_user_status_chk check (status in ('정상', '잠금', '중지'))
);

-- 세션 무효화 (D-26): 계정의 상태나 비밀번호가 바뀌면 그 계정의 살아 있는 세션을 전부 끊는다.
-- 누가 어디서 고치든(사용자 화면 · 시드 · SQL) 같은 규칙이 적용되도록 DB 가 판 번호를 올린다. 역할·이름 변경은 올리지 않는다(요청마다 DB 에서 다시 읽는다).
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

-- @table sys_permission | SYS | 권한 표 — 역할 × 대메뉴 한 칸이 한 행 (4 × 12 = 48). 코드가 아니라 데이터다 (G-17 · D-14)
create table sys_permission (
    role_code    text not null references sys_role (role_code) on delete cascade, -- 역할
    menu_code    text not null,                                      -- 대메뉴 코드 (nav.py 의 BAS · PRT · … · SYS)
    level        text not null,                                      -- 입력 | 조회 | 없음
    write_scope  text not null default '',                           -- 입력의 범위: 일반 | 입고검사 | 승인 (쉼표로 여럿). 입력이 아니면 빈 글자
    updated_at   timestamptz,                                        -- 수정 일시
    updated_by   text,                                               -- 수정자 login_id
    constraint sys_permission_pk primary key (role_code, menu_code),
    constraint sys_permission_level_chk check (level in ('입력', '조회', '없음')),
    constraint sys_permission_scope_chk check ((level = '입력') = (write_scope <> ''))
);

-- @table sys_access_log | SYS | 접근 로그 — 로그인 성공·실패, 화면 조회, 데이터 변경, 오류 (G-18)
create table sys_access_log (
    log_id       bigint generated always as identity primary key,    -- 내부 키
    logged_at    timestamptz not null default now(),                 -- 일시 (언제)
    log_type     text not null,                                      -- 구분: 로그인 | 조회 | 변경 | 오류
    login_id     text,                                               -- 누가 (실패한 로그인은 입력한 ID)
    role_code    text,                                               -- 그때의 역할
    method       text,                                               -- HTTP 메서드
    path         text,                                               -- 경로
    screen_id    text,                                               -- 화면 ID (nav.py)
    function_id  text,                                               -- 기능 ID (function-list.md)
    target       text,                                               -- 무엇을 (테이블·업무 번호)
    result       text not null,                                      -- 성공 | 실패
    detail       text,                                               -- 내용
    client_ip    text,                                               -- 접속 IP
    constraint sys_access_log_type_chk check (log_type in ('로그인', '조회', '변경', '오류')),
    constraint sys_access_log_result_chk check (result in ('성공', '실패'))
);
create index sys_access_log_at_idx on sys_access_log (logged_at desc);

-- @table sys_number_rule | SYS | 채번 형식 — 번호 종류별 한 행. 형식은 코드가 아니라 이 행이다 (D-05). 행은 개발1 시드가 넣는다
create table sys_number_rule (
    seq_kind     text primary key,                                   -- 번호 종류: JOB | JOB_LOT | MAT_LOT | ROLL | SHIPMENT | COA
    prefix       text not null default '',                           -- 접두 글자
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

-- @table sys_migration_log | SYS | 이관 배치 실행 기록 — 실행마다 한 행 (G-15 · D-23)
create table sys_migration_log (
    migration_log_id  bigint generated always as identity primary key, -- 내부 키
    command           text not null,                                 -- 명령 (load-master 등)
    target            text,                                          -- 대상 테이블
    source_file       text,                                          -- Import 파일명
    read_count        integer not null default 0,                    -- 읽은 행 수
    loaded_count      integer not null default 0,                    -- 적재한 행 수
    error_count       integer not null default 0,                    -- 오류 행 수
    error_detail      text,                                          -- 오류 내용
    started_at        timestamptz not null default now(),            -- 시작
    finished_at       timestamptz,                                   -- 끝
    run_by            text                                           -- 실행한 사람
);

-- ════════════════════════════════════════════════════════════════════
-- 뷰 — 저장하지 않고 계산하는 값 (읽기 전용 · D-11)
-- ════════════════════════════════════════════════════════════════════

-- 롤 상태: 출하(출하 행이 있다) > 소진(자식 롤이 있다) > 재고(아무 자식도 없다). 취소된 출하의 계보 행은 지워지므로 여기 남지 않는다.
create view v_roll_state as
select r.roll_id,
       r.roll_no,
       r.process_type,
       r.job_id,
       case
           when s.genealogy_id is not null then '출하'
           when exists (select 1 from roll_genealogy c where c.parent_roll_id = r.roll_id and c.child_roll_id is not null) then '소진'
           else '재고'
       end as state,
       s.child_shipment_id as shipment_id
  from roll r
  left join roll_genealogy s on s.parent_roll_id = r.roll_id and s.child_shipment_id is not null;

-- 원재료 LOT 잔량 = 입고 수량 − 투입량 합. P5 는 D3 에 쓰지 못하므로 잔량을 material_lot 에 저장하지 않는다 (D-13).
create view v_material_lot_stock as
select m.material_lot_id,
       m.lot_no,
       m.item_id,
       m.insp_status,
       m.received_qty,
       coalesce(sum(i.input_qty), 0) as input_qty,
       m.received_qty - coalesce(sum(i.input_qty), 0) as remaining_qty,
       count(i.material_input_id) as input_count
  from material_lot m
  left join material_input i on i.material_lot_id = m.material_lot_id
 group by m.material_lot_id;
