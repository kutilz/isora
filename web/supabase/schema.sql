-- I-Sora cloud relay — Supabase schema
-- Run in the Supabase SQL editor (or `supabase db push`).
--
-- Trust model:
--   * Browser (anon/authenticated key) is constrained by RLS: a user only ever
--     sees devices they own. It NEVER touches pairing_codes or other devices.
--   * Device & privileged route handlers use the service-role key (server-only),
--     which bypasses RLS. Device identity is proven by X-Device-Secret (hashed).
--
-- There is no sign-up. A browser that opens /app is handed an ANONYMOUS Supabase
-- user (lib/supabase/session.ts), so `owner_user_id` and every policy below keep
-- working unchanged — only the way an identity is obtained changed. Attaching an
-- email later upgrades that same row, so ownership survives.
--   → REQUIRES "Allow anonymous sign-ins" in Authentication → Sign In / Providers.
--
-- This does not widen the security boundary: an email account never proved
-- anything about owning a device. What proves it is still one of the pairing
-- paths — a press of the device's own ACTION button, a scanned QR token, a live
-- single-use code, or being the only unclaimed device on the caller's network —
-- and all of them are enforced server-side below and in app/api/pair/*.
-- Bulk-minting anonymous users is bounded by Supabase's own per-IP sign-in rate
-- limit.

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

-- Keyed hash (never the raw IP) of the public network the device last phoned
-- home from. Equality against the browser's own network hash answers "is my
-- phone on the same WiFi as this device?" — see web/lib/net.ts.
alter table public.devices add column if not exists net_hash text;

create index if not exists devices_owner_idx on public.devices(owner_user_id);
-- Serves the "unclaimed devices on my network" lookup in /api/pair/nearby.
create index if not exists devices_unclaimed_net_idx
  on public.devices(net_hash, last_seen) where owner_user_id is null;

-- ─── pairing_codes ──────────────────────────────────────────────────────────
create table if not exists public.pairing_codes (
  code        text primary key,                   -- short, TTS-friendly, single-use
  device_id   text not null references public.devices(id) on delete cascade,
  expires_at  timestamptz not null,
  used        boolean not null default false,
  created_at  timestamptz not null default now()
);

create index if not exists pairing_codes_device_idx on public.pairing_codes(device_id);

-- ─── pairing_sessions ───────────────────────────────────────────────────────
-- The button path: the phone opens a session and waits, the person presses the
-- device's ACTION button, the device confirms. Pressing a button you are holding
-- is stronger proof of ownership than sharing a public IP — and it costs the
-- user no typing, no reading and no sighted help, which the spoken code did.
create table if not exists public.pairing_sessions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  net_hash    text,                               -- the phone's network, see lib/net.ts
  device_id   text references public.devices(id) on delete set null,  -- set on confirm
  expires_at  timestamptz not null,
  created_at  timestamptz not null default now()
);

-- Drives the "which session is this button press for?" lookup on confirm.
create index if not exists pairing_sessions_waiting_idx
  on public.pairing_sessions(expires_at) where device_id is null;

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
alter table public.devices          enable row level security;
alter table public.pairing_codes    enable row level security;
alter table public.pairing_sessions enable row level security;
alter table public.commands         enable row level security;

-- Owners can read & update their own devices (the service role bypasses RLS).
-- Note the UPDATE policy below re-checks `owner_user_id = auth.uid()` on the NEW
-- row as well, so a browser can never hand a device to another account (nor
-- release one — /api/devices/:id DELETE does that with the service role).
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

-- pairing_codes / pairing_sessions: no browser policies → anon/authenticated
-- cannot read or write either table. Only the service role (server) touches
-- them, and app/api/pair/* scopes every read to the calling user.

-- Column-level grants are the real guard on what a signed-in browser may write.
-- RLS says WHICH rows; this says WHICH columns — without it an owner could
-- overwrite their device's secret_hash or pubkey and impersonate the hardware.
revoke update on public.devices from anon, authenticated;
grant  update (name) on public.devices to authenticated;

-- ─── housekeeping: drop expired/used pairing codes & sessions ───────────────
create or replace function public.purge_expired_pairing_codes()
returns void language sql as $$
  delete from public.pairing_codes
  where used = true or expires_at < now() - interval '1 hour';
  delete from public.pairing_sessions
  where expires_at < now() - interval '1 hour';
$$;
