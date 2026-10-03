-- VOLTA — Supabase schema. Safe to run more than once (also on top of the earlier draft).
-- ============================================================================

-- ---------- tables -----------------------------------------------------------
create table if not exists sources (
  id bigint generated always as identity primary key,
  name text not null,
  kind text not null,
  url text,
  region text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table sources drop constraint if exists sources_kind_check;
alter table sources add constraint sources_kind_check
  check (kind in ('ical','rss','ticketing','html','manual','aggregator'));
alter table sources drop constraint if exists sources_region_check;
alter table sources add constraint sources_region_check check (region in ('volos','pelion'));
alter table sources add column if not exists category text;

create table if not exists events (
  id bigint generated always as identity primary key,
  source_id bigint references sources(id),
  external_id text,
  title text not null,
  description text,
  starts_at timestamptz not null,
  ends_at timestamptz,
  venue text,
  region text,
  category text,
  url text,
  status text not null default 'published',
  overrides jsonb not null default '{}'::jsonb,
  collected_at timestamptz not null default now(),
  unique (source_id, external_id)
);
alter table events drop constraint if exists events_region_check;
alter table events add constraint events_region_check check (region in ('volos','pelion'));
alter table events drop constraint if exists events_status_check;
alter table events add constraint events_status_check check (status in ('published','hidden'));
-- what the static page needs besides the basics
alter table events add column if not exists sources jsonb not null default '[]'::jsonb;  -- [{source,url}]
alter table events add column if not exists all_day boolean not null default false;      -- no time known
alter table events add column if not exists price text;
alter table events add column if not exists hall text;                                    -- e.g. Αχίλλειον

create table if not exists submissions (
  id bigint generated always as identity primary key,
  kind text not null,
  payload jsonb not null,
  contact_email text,
  status text not null default 'pending',
  created_at timestamptz not null default now()
);
alter table submissions drop constraint if exists submissions_kind_check;
alter table submissions add constraint submissions_kind_check check (kind in ('event','ical','rss','website'));
alter table submissions drop constraint if exists submissions_status_check;
alter table submissions add constraint submissions_status_check check (status in ('pending','approved','rejected'));
-- the public form must not be able to fill the database with junk
alter table submissions drop constraint if exists submissions_size_check;
alter table submissions add constraint submissions_size_check
  check (pg_column_size(payload) < 6000 and coalesce(length(contact_email), 0) <= 200);
alter table submissions add column if not exists reason text;

-- ---------- who is an admin --------------------------------------------------
create table if not exists admins (user_id uuid primary key references auth.users(id) on delete cascade);
alter table admins enable row level security;

create or replace function is_admin() returns boolean
language sql stable security definer set search_path = public as
$$ select exists (select 1 from admins where user_id = auth.uid()) $$;
revoke execute on function is_admin() from public, anon;
grant execute on function is_admin() to authenticated;

-- ---------- row level security -----------------------------------------------
alter table sources enable row level security;
alter table events enable row level security;
alter table submissions enable row level security;

drop policy if exists "public reads published events" on events;
drop policy if exists "public can submit" on submissions;
drop policy if exists "admin all events" on events;
drop policy if exists "admin all submissions" on submissions;
drop policy if exists "admin all sources" on sources;

create policy "public reads published events" on events
  for select to anon using (status = 'published');
create policy "public can submit" on submissions
  for insert to anon with check (status = 'pending' and reason is null);
-- only people listed in "admins" — not every signed-in account
create policy "admin all events" on events
  for all to authenticated using (is_admin()) with check (is_admin());
create policy "admin all submissions" on submissions
  for all to authenticated using (is_admin()) with check (is_admin());
create policy "admin all sources" on sources
  for all to authenticated using (is_admin()) with check (is_admin());

-- ---------- what the public site reads (overrides win) -----------------------
drop view if exists public_events;
create view public_events with (security_invoker = true) as
select
  id, external_id,
  coalesce(overrides->>'title',       title)       as title,
  coalesce(overrides->>'description', description) as description,
  coalesce((overrides->>'starts_at')::timestamptz, starts_at) as starts_at,
  coalesce((overrides->>'ends_at')::timestamptz,   ends_at)   as ends_at,
  coalesce((overrides->>'all_day')::boolean, all_day) as all_day,
  coalesce(overrides->>'venue',    venue)    as venue,
  coalesce(overrides->>'region',   region)   as region,
  coalesce(overrides->>'category', category) as category,
  coalesce(overrides->>'url',      url)      as url,
  coalesce(overrides->>'price', price) as price,
  hall, sources
from events
where status = 'published';
grant select on public_events to anon, authenticated;

-- ---------- approve / reject (called from admin.html) ------------------------
create or replace function approve_submission(sub_id bigint)
returns void language plpgsql security invoker set search_path = public as $$
declare s submissions; p jsonb;
begin
  if not is_admin() then raise exception 'not allowed'; end if;
  select * into s from submissions where id = sub_id and status = 'pending';
  if not found then raise exception 'Submission % not pending', sub_id; end if;
  p := s.payload;
  if s.kind = 'event' then
    insert into events (source_id, external_id, title, description, starts_at, ends_at, all_day,
                        venue, region, category, url, price, sources)
    values (null, 'sub-' || s.id,
            p->>'title', p->>'description',
            (p->>'starts_at')::timestamptz, nullif(p->>'ends_at','')::timestamptz,
            coalesce((p->>'all_day')::boolean, false),
            p->>'venue', p->>'region', p->>'category', nullif(p->>'url',''), nullif(p->>'price',''),
            jsonb_build_array(jsonb_build_object(
              'source', 'Υποβολή: ' || coalesce(p->>'organizer', ''),
              'url', coalesce(nullif(p->>'url',''), '#'))));
  else
    insert into sources (name, kind, url, region, category)
    values (coalesce(nullif(p->>'name',''), p->>'url'),
            case s.kind when 'website' then 'html' else s.kind end,
            p->>'url', p->>'region', p->>'category');
  end if;
  update submissions set status = 'approved' where id = sub_id;
end $$;
revoke execute on function approve_submission(bigint) from public, anon;
grant execute on function approve_submission(bigint) to authenticated;

create index if not exists events_starts_idx on events (starts_at) where status = 'published';

-- ---------- error reports from visitors ("Αναφορά λάθους") -------------------
create table if not exists reports (
  id bigint generated always as identity primary key,
  event_id bigint references events(id) on delete set null,
  event_title text,
  event_date date,
  event_url text,
  issue text not null,
  message text,
  contact_email text,
  status text not null default 'open',
  created_at timestamptz not null default now()
);
alter table reports drop constraint if exists reports_issue_check;
alter table reports add constraint reports_issue_check
  check (issue in ('date','venue','cancelled','irrelevant','duplicate','other'));
alter table reports drop constraint if exists reports_status_check;
alter table reports add constraint reports_status_check check (status in ('open','resolved','dismissed'));
alter table reports drop constraint if exists reports_size_check;
alter table reports add constraint reports_size_check check (
  coalesce(length(message),0) <= 1000 and coalesce(length(contact_email),0) <= 200 and
  coalesce(length(event_title),0) <= 300 and coalesce(length(event_url),0) <= 500);
alter table reports enable row level security;
drop policy if exists "public can report" on reports;
drop policy if exists "admin all reports" on reports;
create policy "public can report" on reports for insert to anon with check (status = 'open');
create policy "admin all reports" on reports for all to authenticated using (is_admin()) with check (is_admin());
