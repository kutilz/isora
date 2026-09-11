# Boot-Time Optimization

> **Date:** 2025-06-23
> **Goal:** Reduce time from power-on to hearing "AuralAI menyala"
> **Result:** ~28-30s → **~2.0s** (measured on device; was ~16s before the
> early-init chime — see "Early-init chime" below)

## TL;DR — where the time went (measured via dmesg, monotonic from power-on)

Boot-to-chime was dominated entirely by **when the chime got a chance to play**,
not by app code:

| Chime location | Plays at | Why |
|----------------|---------:|-----|
| rc.local / S99local (original) | ~16.4s | runs dead-last, behind WiFi association (~13s) |
| S15 (after udev) | ~9.2s | `udevadm settle` in S10udev is a ~6s blocker |
| S05z (after S0x hw scripts) | ~6.1s | still behind S00kmod's ~25 `insmod`s + i2c/touch probe |
| **S00a (first init script)** | **~2.0s** | before module load + WiFi; DAC ready at kernel probe (~0.78s) |

The Python import optimization below does **not** affect time-to-chime — the
chime plays via ALSA long before Python matters. It only speeds full readiness.

## Early-init chime (S00a) — the big win

The boot chime no longer lives in `rc.local`. It is a standalone init script
installed at **`/etc/init.d/S00aauralchime`** — the *first* script `rcS` runs,
before `S00kmod` loads the ~25 soph camera/NPU modules and long before WiFi.

Why this is safe (the design goal was: **never stall boot just to make a sound**):
- The cv182xa **DAC is kernel-probed at ~0.78s** and its node `/dev/snd/pcmC1D0p`
  is created by devtmpfs right then — it exists before any init.d script. The
  chime uses the **i2s** DAC, independent of the **i2c** bus that `S00pmu`/the
  camera sensor use, so it does not contend with module loading.
- `aplay` runs in a **detached background subshell** → the script returns
  instantly; boot proceeds even if audio is slow/absent.
- It plays + sets `/tmp/.boot_chime_played` **only if** `/dev/snd/pcmC1D0p` and
  the PCM both exist. If audio isn't ready that early, it does nothing and sets
  no flag → `main.py`'s `_boot_cue_fast` plays it later (the ~16s path).
  **Self-adaptive**: worst case is the old behavior, never a broken boot.
- Always `exit 0`.

Installed/removed automatically by `tools/run.py --autostart` /
`--autostart-off` (see `CHIME_INIT_SCRIPT` / `CHIME_INIT_PATH`). Verified
on-device: modules + camera still come up clean, single chime at ~2.0s.

## What Changed

1. **`tools/run.py`** — `RC_BLOCK` autostart block:
   - `sleep 5` → `sleep 1`
   - Boot chime moved OUT of `rc.local` into the `S00aauralchime` init script
     (above); `rc.local` now only launches the app
   - Original block preserved as `RC_BLOCK_LEGACY` for one-line rollback

2. **`device/main.py`** — Import ordering:
   - Heavy imports (`config`, `orchestrator`, `cloud`, etc.) moved from top-level into `main()`
   - New `_boot_cue_fast()` function plays PCM directly via `maix.audio.Player`
   - Boot cue thread starts *before* imports, so sound plays ~4-6s earlier
   - "Menghubungkan ke wifi" plays after imports via the full `play_wav_blocking` path

## How to Revert

### Option A: Git revert
```bash
git checkout device/main.py tools/run.py
python tools/run.py --autostart
```

### Option B: rc.local only
In `tools/run.py`, change `RC_BLOCK` to `RC_BLOCK_LEGACY`, then:
```bash
python tools/run.py --autostart
```

### Option C: SSH direct
```bash
ssh root@<device-ip>  # password: root
cat > /etc/rc.local << 'REVERT'
#!/bin/sh
# >>> AuralAI autostart >>>
sleep 5
cd /root/aural-ai
nohup python3 /root/aural-ai/main.py >> /tmp/aural_main.log 2>&1 &
echo $! > /tmp/aural_main.pid
# <<< AuralAI autostart <<<
REVERT
chmod +x /etc/rc.local && sync && reboot
```

## Technical Details

### Why `sleep 5` was unnecessary
- `rc.local` is called by `/etc/init.d/S99local` — the **last** init script
- By this point all drivers are loaded (WiFi at ~14s, DAC at ~33s in dmesg)
- The `sleep 5` was a conservative safety margin, but `sleep 1` is sufficient

### Why `aplay` works
- ALSA device: `hw:1,0` (card 1: cv182xa_dac)
- PCM format: `S16_LE`, 48000 Hz, mono — matches `audio_manager._ensure_pcm`
- File: `/root/audio/auralai_menyala.pcm` (165888 bytes, ~1.7s audio)
- `2>/dev/null &` — runs in background, errors suppressed

### Import timing (measured on device)
| Module | Time |
|--------|------|
| `config` | 2.032s |
| `core.cloud` | 2.558s |
| `core.audio_manager` | 1.324s |
| `server.web_server` | 0.774s |
| `core.onboarding` | 0.521s |
| `utils.logger` | 0.380s |
| Others | ~0.4s |
| **Total** | **~6.7s** |

### Double-play protection + fallback
Both `aplay` (rc.local) and `_boot_cue_fast` (main.py) can play the boot chime.
A flag file `/tmp/.boot_chime_played` coordinates them:

- rc.local sets the flag **only if** `auralai_menyala.pcm` exists (so the flag
  reliably means "aplay had something to play"). `_boot_cue_fast` sees the flag
  and skips → no double-play.
- If the PCM is **missing** (fresh flash, deleted cache, or a re-recorded WAV),
  rc.local does NOT set the flag and `aplay` plays nothing. `_boot_cue_fast`
  then takes the **fallback** path: it calls `play_wav_blocking("auralai_menyala.wav")`,
  which regenerates the PCM via ffmpeg (cached next to the WAV) and plays it.
  This is the *only* path that recreates the PCM — without it the cue would be
  silent forever once the cache is gone.
- `/tmp` is tmpfs, so the flag clears on every reboot. A manual relaunch is not
  a reboot, so `tools/run.py` clears the flag itself when relaunching `main.py`,
  ensuring the cue replays on an app restart instead of being skipped on a stale
  flag.
