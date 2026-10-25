-- D-531 전사 경영 Cockpit 무손실 이관. 기존 업무 테이블은 변경하지 않는다.
begin;

create table if not exists management_metric (
 metric_key text primary key, metric_name text not null unique, unit text not null default '', direction text not null,
 source_key text not null, use_yn text not null default 'Y', created_at timestamptz not null default now(), created_by text,
 updated_at timestamptz, updated_by text,
 constraint management_metric_direction_chk check (direction in ('높을수록 좋음','낮을수록 좋음','범위 내 정상')),
 constraint management_metric_use_chk check (use_yn in ('Y','N'))
);
do $$ begin
 if exists (select 1 from pg_constraint where conname='management_metric_metric_name_key') then
  alter table management_metric rename constraint management_metric_metric_name_key to management_metric_name_uq;
 end if;
end $$;
create table if not exists management_target (
 id bigserial primary key, metric_key text not null references management_metric(metric_key), period_kind text not null,
 period_from date not null, period_to date not null, scope_kind text not null default 'company', scope_key text,
 status text not null default '사용', created_at timestamptz not null default now(), created_by text, updated_at timestamptz, updated_by text,
 constraint management_target_period_chk check (period_kind in ('연간','월간','주간')),
 constraint management_target_dates_chk check (period_from <= period_to),
 constraint management_target_scope_chk check ((scope_kind='company' and scope_key is null) or (scope_kind in ('department','customer','item','equipment','warehouse') and scope_key is not null)),
 constraint management_target_status_chk check (status in ('사용','중지'))
);
create unique index if not exists management_target_active_uq on management_target
 (metric_key,period_kind,period_from,period_to,scope_kind,coalesce(scope_key,'')) where status='사용';
create table if not exists management_target_version (
 id bigserial primary key, target_id bigint not null references management_target(id), version_no integer not null,
 target_value numeric(18,4) not null, range_min numeric(18,4), range_max numeric(18,4), change_reason text not null,
 created_at timestamptz not null default now(), created_by text,
 constraint management_target_version_uq unique(target_id,version_no),
 constraint management_target_version_range_chk check ((range_min is null and range_max is null) or (range_min is not null and range_max is not null and range_min <= range_max))
);
create table if not exists management_threshold (
 id bigserial primary key, metric_key text not null references management_metric(metric_key), level text not null,
 compare_op text not null, value_min numeric(18,4), value_max numeric(18,4), period_from date not null, period_to date not null,
 scope_kind text not null default 'company', scope_key text, status text not null default '사용',
 created_at timestamptz not null default now(), created_by text, updated_at timestamptz, updated_by text,
 constraint management_threshold_level_chk check (level in ('주의','위험')),
 constraint management_threshold_op_chk check (compare_op in ('gt','gte','lt','lte','outside')),
 constraint management_threshold_value_chk check (value_min is not null and (compare_op <> 'outside' or value_max is not null)),
 constraint management_threshold_dates_chk check (period_from <= period_to),
 constraint management_threshold_scope_chk check ((scope_kind='company' and scope_key is null) or (scope_kind in ('department','customer','item','equipment','warehouse') and scope_key is not null)),
 constraint management_threshold_status_chk check (status in ('사용','중지'))
);
create index if not exists management_threshold_lookup_idx on management_threshold
 (metric_key,period_from,period_to,scope_kind,scope_key) where status='사용';
create table if not exists management_issue (
 id bigserial primary key, issue_key text not null unique, metric_key text references management_metric(metric_key), severity text not null,
 title text not null, observed_value numeric(18,4), evidence jsonb not null default '{}'::jsonb, source_screen text not null,
 source_query text not null default '', owner_role text references sys_role(role_code), status text not null default '신규',
 first_seen_at timestamptz not null default now(), last_seen_at timestamptz not null default now(), resolved_at timestamptz,
 close_reason text, created_at timestamptz not null default now(), created_by text, updated_at timestamptz, updated_by text,
 constraint management_issue_severity_chk check (severity in ('주의','위험')),
 constraint management_issue_status_chk check (status in ('신규','진행','해결')),
 constraint management_issue_resolved_chk check ((status='해결') = (resolved_at is not null))
);
do $$ begin
 if exists (select 1 from pg_constraint where conname='management_issue_issue_key_key') then
  alter table management_issue rename constraint management_issue_issue_key_key to management_issue_key_uq;
 end if;
end $$;
create index if not exists management_issue_open_idx on management_issue(severity,last_seen_at desc) where status <> '해결';
create table if not exists management_action (
 id bigserial primary key, issue_id bigint not null references management_issue(id), owner_role text not null references sys_role(role_code),
 owner_user_id bigint references sys_user(user_id), due_date date not null, action_text text not null, status text not null default '대기',
 completed_at timestamptz, completed_by bigint references sys_user(user_id), created_at timestamptz not null default now(),
 created_by text, updated_at timestamptz, updated_by text,
 constraint management_action_status_chk check (status in ('대기','진행','완료','취소')),
 constraint management_action_completed_chk check ((status='완료') = (completed_at is not null))
);
create index if not exists management_action_owner_idx on management_action(owner_role,status,due_date);
create table if not exists financial_import_batch (
 id bigserial primary key, period_from date not null, period_to date not null, round_no integer not null,
 status text not null default '검증', source_name text not null, fields jsonb not null default '[]'::jsonb,
 row_count integer not null default 0, error_count integer not null default 0,
 replaced_by bigint references financial_import_batch(id), applied_at timestamptz,
 created_at timestamptz not null default now(), created_by text, updated_at timestamptz, updated_by text,
 constraint financial_import_batch_period_uq unique(period_from,period_to,round_no),
 constraint financial_import_batch_dates_chk check (period_from <= period_to),
 constraint financial_import_batch_status_chk check (status in ('검증','반영','교체','오류')),
 constraint financial_import_batch_counts_chk check (row_count >= 0 and error_count >= 0 and error_count <= row_count)
);
create unique index if not exists financial_import_batch_active_uq on financial_import_batch(period_from,period_to) where status='반영';
create table if not exists financial_fact (
 id bigserial primary key, batch_id bigint not null references financial_import_batch(id), row_no integer not null,
 period_month date not null, customer_id bigint not null references customer(id), item_id bigint not null references item(id),
 order_amount numeric(16,2), shipment_amount numeric(16,2), standard_cost numeric(16,2), actual_cost numeric(16,2),
 raw jsonb not null default '{}'::jsonb, error text, created_at timestamptz not null default now(), created_by text,
 constraint financial_fact_row_uq unique(batch_id,row_no),
 constraint financial_fact_month_chk check (period_month=date_trunc('month',period_month)::date),
 constraint financial_fact_amount_chk check (order_amount is not null or shipment_amount is not null or standard_cost is not null or actual_cost is not null)
);
create index if not exists financial_fact_lookup_idx on financial_fact(period_month,customer_id,item_id) where error is null;

drop trigger if exists management_target_version_append_only_trg on management_target_version;
create trigger management_target_version_append_only_trg before update or delete on management_target_version
 for each row execute function append_only_guard();
drop trigger if exists management_target_version_no_truncate_trg on management_target_version;
create trigger management_target_version_no_truncate_trg before truncate on management_target_version
 for each statement execute function append_only_guard();
drop trigger if exists financial_fact_append_only_trg on financial_fact;
create trigger financial_fact_append_only_trg before update or delete on financial_fact
 for each row execute function append_only_guard();
drop trigger if exists financial_fact_no_truncate_trg on financial_fact;
create trigger financial_fact_no_truncate_trg before truncate on financial_fact
 for each statement execute function append_only_guard();

commit;
