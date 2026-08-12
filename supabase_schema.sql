-- Unified Fencing Group acquisition map — Supabase schema
-- Run this in your NEW (Grand Street) Supabase project: SQL Editor → paste → Run.
-- Safe to re-run (idempotent-ish: uses IF NOT EXISTS / CREATE OR REPLACE).

-- ---------------------------------------------------------------- companies
-- One row per target. Written by the local enrichment job (service_role key,
-- which bypasses RLS). Read by the logged-in team.
create table if not exists public.companies (
  id             text primary key,
  company        text not null,
  domain         text,
  tier           text,
  confidence     text,
  archetype      text,
  ownership      text,
  parent         text,
  description    text,
  founded        text,
  revenue        numeric,
  employees      numeric,
  rating         numeric,
  reviews        integer,
  contact_name   text,
  contact_title  text,
  phone          text,
  email          text,
  linkedin       text,
  hq             text,
  city           text,
  state          text,
  lat            double precision,
  lng            double precision,
  south_west     boolean,
  vinyl          boolean,
  composite      boolean,
  fit            integer,
  meets_buy_box  boolean,
  criteria       jsonb,
  source         text default 'tracker',   -- 'tracker' | 'discovered'
  address        text,                      -- street address (Places enrichment)
  place_id       text,
  place_rating   numeric,
  place_reviews  integer,
  review_qualified boolean,        -- discovered rows: rating>=4.5, rest unverified
  updated_at     timestamptz default now()
);

create index if not exists companies_fit_idx    on public.companies (fit desc);
create index if not exists companies_state_idx  on public.companies (state);
create index if not exists companies_source_idx on public.companies (source);

-- ---------------------------------------------------------------- outreach
-- Shared per-company outreach state so the team coordinates (one row per
-- company; whoever edits last is recorded). Handwritten-note / call workflow.
create table if not exists public.outreach (
  company_id  text primary key references public.companies (id) on delete cascade,
  status      text default 'Not started',  -- Not started|Note sent|Called|Meeting set|Interested|Pass
  notes       text,
  updated_by  uuid references auth.users (id),
  updated_at  timestamptz default now()
);

-- ---------------------------------------------------------------- RLS
alter table public.companies enable row level security;
alter table public.outreach  enable row level security;

-- Any logged-in teammate can read the target list.
drop policy if exists "team reads companies" on public.companies;
create policy "team reads companies" on public.companies
  for select to authenticated using (true);

-- Note: companies are written only by the enrichment job using the
-- service_role key, which bypasses RLS — so no insert/update policy is granted
-- to normal users (the browser cannot alter the target data).

-- Any logged-in teammate can read + upsert outreach status/notes.
drop policy if exists "team reads outreach" on public.outreach;
create policy "team reads outreach" on public.outreach
  for select to authenticated using (true);

drop policy if exists "team writes outreach" on public.outreach;
create policy "team writes outreach" on public.outreach
  for insert to authenticated with check (true);

drop policy if exists "team updates outreach" on public.outreach;
create policy "team updates outreach" on public.outreach
  for update to authenticated using (true) with check (true);

-- keep updated_at fresh on outreach writes
create or replace function public.touch_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;

drop trigger if exists outreach_touch on public.outreach;
create trigger outreach_touch before update on public.outreach
  for each row execute function public.touch_updated_at();
