-- The kit's operational store in Azure Database for PostgreSQL.
-- Row-level security by country: the API sets `kit.countries` (comma-separated, or '*') per request
-- from the caller's Entra groups, so a query can only return rows of the caller's countries.
-- Usage events are append-only: adoption and impact are measured from them.

create table if not exists proposals (
  proposal_id text primary key, case_id text not null, use_case text not null, country text not null,
  created_ts bigint not null, prepared_by text not null, decision text not null, needs_review boolean not null,
  payload jsonb not null);
create table if not exists actions (
  action_id text primary key, proposal_id text not null references proposals, case_id text not null,
  kind text not null, amount numeric(12, 2), payload jsonb not null, payload_hash text not null, role text,
  status text not null default 'proposed', created_ts bigint not null);
create table if not exists approvals (
  approval_id text primary key, action_id text not null references actions, approver text not null,
  decided_ts bigint not null, decision text not null, token_id text unique, consumed_ts bigint);
create table if not exists usage_events (
  event_id bigserial primary key, ts bigint not null, use_case text not null, case_id text not null,
  country text not null, user_oid text not null, event text not null, value double precision, detail jsonb);

create or replace function kit_refuse_change() returns trigger language plpgsql as $$
begin raise exception 'usage_events is append-only'; end $$;
drop trigger if exists usage_events_append_only on usage_events;
create trigger usage_events_append_only before update or delete on usage_events
  for each row execute function kit_refuse_change();

create or replace function kit_sees(country text) returns boolean language sql stable as $$
  select coalesce(current_setting('kit.countries', true), '') = '*'
      or country = any(string_to_array(coalesce(current_setting('kit.countries', true), ''), ','))
$$;

alter table proposals enable row level security;
alter table usage_events enable row level security;
drop policy if exists proposals_by_country on proposals;
create policy proposals_by_country on proposals using (kit_sees(country)) with check (kit_sees(country));
drop policy if exists usage_by_country on usage_events;
create policy usage_by_country on usage_events using (kit_sees(country)) with check (kit_sees(country));

do $$ begin
  if not exists (select from pg_roles where rolname = 'kit_app') then create role kit_app nologin; end if;
end $$;
grant select, insert, update on proposals, actions, approvals to kit_app;
grant select, insert on usage_events to kit_app;
grant usage on sequence usage_events_event_id_seq to kit_app;
