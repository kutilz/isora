/**
 * Whether the cloud relay (Supabase behind /api/devices, /api/pair, /api/poll…)
 * is switched off.
 *
 * Off since 1 Nov 2026: the Supabase project was deleted, and bringing up a new
 * one would make every online unit re-register as *unpaired* and speak the
 * "press the button to connect" prompt every 60 s (core/cloud.py,
 * ANNOUNCE_EVERY_S) until re-paired — not something to risk during PIMNAS.
 * The glasses do everything that matters offline; the app is an optional extra.
 *
 * While true:
 *   - every app screen that needs the relay says so and offers a way onward
 *     (components/app/RelayPaused.tsx) instead of hanging on "Memuat…";
 *   - middleware answers the relay API with 503 at once, so the units' retry
 *     loop costs no function time waiting on a hostname that no longer exists;
 *   - nothing calls Supabase from the browser.
 *
 * To bring the app back: provision a new project (web/supabase/schema.sql,
 * anonymous sign-ins on), set the Vercel env vars, flip this to false, deploy,
 * then pair each unit straight away.
 */
export const RELAY_PAUSED = true;
