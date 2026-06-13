-- I-Sora cloud relay — Supabase schema
-- Run in the Supabase SQL editor (or `supabase db push`).
--
-- Trust model:
--   * Browser (anon/authenticated key) is constrained by RLS: a user only ever
--     sees devices they own. It NEVER touches pairing_codes or other devices.
--   * Device & privileged route handlers use the service-role key (server-only),
--     which bypasses RLS. Device identity is proven by X-Device-Secret (hashed).

-- ─── devices ────────────────────────────────────────────────────────────────
create table if not exists public.devices (
  id            text primary key,                 -- cloud_device_id (random hex, from device)
  secret_hash   text not null,                    -- sha256(device_secret) — never store plaintext
  pubkey        text,                             -- device E2E public key (P-256 raw, base64)
  owner_user_id uuid references auth.users(id) on delete set null,
  name          text,
  fw_version    text,
  status        jsonb not null default '{}'::jsonb,  -- last heartbeat (mode, wifi, battery…)
  last_seen     timestamptz,
  created_at    timestamptz not null default now()
);

create index if not exists devices_owner_idx on public.devices(owner_user_id);

-- ─── pairing_codes ──────────────────────────────────────────────────────────
create table if not exists public.pairing_codes (
  code        text primary key,                   -- short, TTS-friendly, single-use
  device_id   text not null references public.devices(id) on delete cascade,
  expires_at  timestamptz not null,
  used        boolean not null default false,
  created_at  timestamptz not null default now()
);

create index if not exists pairing_codes_device_idx on public.pairing_codes(device_id);

-- ─── commands ───────────────────────────────────────────────────────────────
-- Desired-config / actions pushed web → device. Device long-polls, applies, ACKs.
create table if not exists public.commands (
  id          uuid primary key default gen_random_uuid(),
  device_id   text not null references public.devices(id) on delete cascade,
  type        text not null,                      -- 'config' | 'action'
  payload     jsonb not null default '{}'::jsonb, -- secrets here are E2E ciphertext
  status      text not null default 'pending',    -- 'pending' | 'acked'
  created_at  timestamptz not null default now(),
  acked_at    timestamptz
);

create index if not exists commands_device_pending_idx
  on public.commands(device_id) where status = 'pending';

-- ─── Row Level Security ─────────────────────────────────────────────────────
alter table public.devices       enable row level security;
alter table public.pairing_codes enable row level security;
alter table public.commands      enable row level security;

-- Owners can read & update their own devices (the service role bypasses RLS).
drop policy if exists devices_owner_select on public.devices;
create policy devices_owner_select on public.devices
  for select using (owner_user_id = auth.uid());

drop policy if exists devices_owner_update on public.devices;
create policy devices_owner_update on public.devices
  for update using (owner_user_id = auth.uid());

-- Owners can read commands for devices they own (writes happen via service role).
drop policy if exists commands_owner_select on public.commands;
create policy commands_owner_select on public.commands
  for select using (
    exists (
      select 1 from public.devices d
      where d.id = commands.device_id and d.owner_user_id = auth.uid()
    )
  );

-- pairing_codes: no browser policies → anon/authenticated cannot read or write.
-- Only the service role (server) touches this table.

-- ─── housekeeping: drop expired/used pairing codes ──────────────────────────
create or replace function public.purge_expired_pairing_codes()
returns void language sql as $$
  delete from public.pairing_codes
  where used = true or expires_at < now() - interval '1 hour';
$$;
