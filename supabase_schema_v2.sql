-- supabase_schema_v2.sql
-- Run this once in Supabase SQL Editor.
-- JSON-backed schema: prevents future column mismatch errors.

create extension if not exists pgcrypto;

create table if not exists public.projects (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    description text,
    owner text,
    data jsonb,
    created_at timestamp with time zone default now(),
    updated_at timestamp with time zone default now()
);

create table if not exists public.allocation_rows (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references public.projects(id) on delete cascade,
    row_order integer,
    row_data jsonb,
    updated_by text,
    updated_at timestamp with time zone default now()
);

create table if not exists public.allocation_versions (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references public.projects(id) on delete cascade,
    version_no integer,
    saved_by text,
    save_note text,
    snapshot jsonb,
    created_at timestamp with time zone default now()
);

create table if not exists public.save_events (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references public.projects(id) on delete cascade,
    event_type text,
    event_by text,
    event_note text,
    created_at timestamp with time zone default now()
);

alter table public.projects
add column if not exists description text,
add column if not exists owner text,
add column if not exists data jsonb,
add column if not exists created_at timestamp with time zone default now(),
add column if not exists updated_at timestamp with time zone default now();

alter table public.allocation_rows
add column if not exists row_order integer,
add column if not exists row_data jsonb,
add column if not exists updated_by text,
add column if not exists updated_at timestamp with time zone default now();

alter table public.allocation_versions
add column if not exists version_no integer,
add column if not exists saved_by text,
add column if not exists save_note text,
add column if not exists snapshot jsonb,
add column if not exists created_at timestamp with time zone default now();

alter table public.save_events
add column if not exists event_type text,
add column if not exists event_by text,
add column if not exists event_note text,
add column if not exists created_at timestamp with time zone default now();

create index if not exists idx_allocation_rows_project on public.allocation_rows(project_id);
create index if not exists idx_allocation_versions_project on public.allocation_versions(project_id);
create index if not exists idx_save_events_project on public.save_events(project_id);

create table if not exists shared_workbooks (
  project_id text primary key,
  workbook jsonb not null,
  updated_by text,
  updated_at timestamptz default now()
);

alter table shared_workbooks enable row level security;

drop policy if exists "authenticated users can read shared workbooks" on shared_workbooks;
create policy "authenticated users can read shared workbooks"
on shared_workbooks for select
to authenticated
using (true);

drop policy if exists "authenticated users can insert shared workbooks" on shared_workbooks;
create policy "authenticated users can insert shared workbooks"
on shared_workbooks for insert
to authenticated
with check (true);

drop policy if exists "authenticated users can update shared workbooks" on shared_workbooks;
create policy "authenticated users can update shared workbooks"
on shared_workbooks for update
to authenticated
using (true)
with check (true);

