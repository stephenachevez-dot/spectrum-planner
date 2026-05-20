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

create extension if not exists pgcrypto;

create table if not exists public.user_roles (
  user_id uuid primary key,
  email text unique,
  role text not null default 'viewer',
  full_name text,
  updated_by text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now(),
  constraint user_roles_role_check check (role in ('admin', 'editor', 'viewer', 'disabled'))
);

create index if not exists user_roles_email_idx
on public.user_roles(email);

-- Existing app tables, included here so this SQL is safe to run on a fresh project too.
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

create table if not exists public.project_files (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references public.projects(id) on delete cascade,
  file_name text not null,
  storage_path text not null,
  uploaded_by text,
  uploaded_at timestamp with time zone default now()
);

create index if not exists idx_allocation_rows_project on public.allocation_rows(project_id);
create index if not exists idx_allocation_versions_project on public.allocation_versions(project_id);
create index if not exists idx_save_events_project on public.save_events(project_id);
create index if not exists project_files_project_id_idx on public.project_files(project_id);

insert into storage.buckets (id, name, public)
values ('spectrum-files', 'spectrum-files', false)
on conflict (id) do nothing;

drop policy if exists "spectrum_files_select" on storage.objects;
drop policy if exists "spectrum_files_insert" on storage.objects;
drop policy if exists "spectrum_files_update" on storage.objects;
drop policy if exists "spectrum_files_delete" on storage.objects;

create policy "spectrum_files_select"
on storage.objects for select
using (bucket_id = 'spectrum-files');

create policy "spectrum_files_insert"
on storage.objects for insert
with check (bucket_id = 'spectrum-files');

create policy "spectrum_files_update"
on storage.objects for update
using (bucket_id = 'spectrum-files')
with check (bucket_id = 'spectrum-files');

create policy "spectrum_files_delete"
on storage.objects for delete
using (bucket_id = 'spectrum-files');
