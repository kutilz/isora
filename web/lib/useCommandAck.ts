"use client";

import { useEffect, useState } from "react";

export type AckState = "idle" | "waiting" | "applied" | "slow";

const POLL_MS = 2_000;
/** Two long-poll windows plus slack — the device re-polls every ~25 s. */
const GIVE_UP_MS = 45_000;

/**
 * Watch a queued config command until the device actually applies it.
 *
 * Without this the app can only say "terkirim", which reads as *nothing
 * happened*: the device might be asleep, off the WiFi, or two seconds from
 * picking the command up, and the person staring at the screen cannot tell
 * which. `slow` is not a failure — the relay holds the command until the
 * device comes back — it just means we should say so instead of pretending.
 *
 * The ACK deletes the row (so E2E ciphertext never lingers in the relay), so
 * "row is gone" is the success signal; see app/api/ack/route.ts.
 */
export function useCommandAck(deviceId: string, commandId: string | null): AckState {
  const [state, setState] = useState<AckState>("idle");

  useEffect(() => {
    if (!commandId) {
      setState("idle");
      return;
    }
    setState("waiting");

    let done = false;
    const started = Date.now();

    const tick = async () => {
      if (done) return;
      try {
        const res = await fetch(
          `/api/devices/${deviceId}/config?command_id=${encodeURIComponent(commandId)}`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.status === "applied") {
            done = true;
            clearInterval(timer);
            setState("applied");
            return;
          }
        }
      } catch {
        /* transient — the interval retries */
      }
      if (!done && Date.now() - started > GIVE_UP_MS) {
        done = true;
        clearInterval(timer);
        setState("slow");
      }
    };

    const timer = setInterval(tick, POLL_MS);
    tick();
    return () => {
      done = true;
      clearInterval(timer);
    };
  }, [deviceId, commandId]);

  return state;
}
