# AuralAI — Operator Runbook (Draft Outline)

> This document is a **rough outline** for the operator guide that you will fully develop later.
> Each section contains bullet points that need to be expanded into complete procedures.

---

## 1. What is AuralAI?

- An on-device visual assistant for visually impaired users.
- Hardware: Sipeed MaixCAM with built-in speaker.
- Three main modes: Explorer (object detection), Scene (AI description), QRIS (payment scanning).
- Operator = caregiver/companion assisting the user; User = visually impaired individual.
- Web dashboard (`http://<device-ip>:8080`) is for the operator's use — not for the user.

---

## 2. Pre-use Preparation

### 2.1 Checklist Before Handing Over to the User

- [ ] Device is connected to the user's WiFi network.
- [ ] API key has been set via the dashboard.
- [ ] Audio test: Device plays "AuralAI ready" upon boot.
- [ ] Explorer mode check: Objects are detected → audio alerts play.
- [ ] Speaker volume is sufficiently loud for the user's environment.
- [ ] Battery / power supply is securely attached.
- [ ] config.json has been backed up.

### 2.2 API Key Setup

1. Open the dashboard → go to the AI Settings menu.
2. Select the provider (OpenAI / Gemini / Claude).
3. Enter the API key → click Save.
4. Click "Test Connection" — a successful AI response must return.
5. Record the dashboard authentication token in the operator's notes (do not share with the user).

---

## 3. How to Boot the Device

- Connect power → the device boots automatically (~30 seconds).
- Ready indicator: Audio cue "AuralAI siap digunakan" (AuralAI is ready for use) plays from the speaker.
- If no audio is heard within 60 seconds → refer to the Troubleshooting section.

### Audio Status Indicators

| Heard Sound                       | Meaning                            |
| --------------------------------- | ---------------------------------- |
| "AuralAI siap digunakan"          | Boot successful, ready for use     |
| "Mode penjelajah aktif"           | Entered Explorer Mode              |
| "Mode konteks aktif"              | Entered Scene Mode                 |
| "Mode scan bayar aktif"           | Entered QRIS Mode                  |
| "Sedang menganalisis"             | AI Vision is processing            |
| "Masih memproses"                 | AI is still working, please wait   |
| "Koneksi gagal"                   | Internet connection is unavailable |
| "Gagal menganalisis"              | AI failed to process request       |
| "Baterai lemah"                   | Low battery, charge immediately    |
| "Perangkat terlalu panas"         | Device is overheating              |

---

## 4. Operating Modes

### 4.1 Explorer Mode (Default)

- Active upon boot.
- Camera detects objects in real-time (YOLO).
- Hazardous objects (near range) → play CRITICAL priority audio (interrupts other audio).
- General objects → play HIGH priority audio.

### 4.2 Scene Mode

- Triggered via physical button or dashboard command → switches to Scene Mode.
- User presses button → AI Vision describes the scene in Indonesian.
- Requires active internet connection.
- Response time ~3-8 seconds (audio progress plays every 3 seconds while waiting).

### 4.3 QRIS Mode

- Active when the user wishes to scan payment codes.
- Default hybrid mode: Local decoder + AI cross-check.
- Output: "MERCHANT: [name], NOMINAL: [amount]".
- If nominal amount > 1 million IDR → prompts for confirmation (safety cap).

### 4.4 Switching Modes

- Via physical button (configure pins in Dashboard → Hardware Settings).
- Via web dashboard → mode switch button.
- Mode cycle: Explorer → Scene → QRIS → Explorer.

---

## 5. Web Dashboard

- URL: `http://<maixcam-ip>:8080`
- Check IP address via MaixCAM screen or router dashboard.
- Log in with the access token (see `/root/config.json` key `device_token` for initial token).
- **Dashboard is ONLY for operators/devs** — audio output still routes through the device speaker.

### Dashboard Features

- **Camera preview** — live camera feed.
- **Status bar** — active mode, FPS, CPU temperature, RAM usage.
- **Log stream** — real-time logs from the device.
- **AI Settings** — change provider, API key, custom prompt.
- **Presets** — quick switch between preset configurations (Explorer/Scene/QRIS preset).
- **Health** — hardware metrics (temperature, disk, RAM).
- **I2C Probe** — checks battery HAT status (POST `/i2c-probe`).

---

## 6. WiFi Troubleshooting

| Symptom                   | Steps |
| ------------------------- | ----- |
| No "ready" audio          | Check power source, wait 60 seconds, reboot. |
| Dashboard won't open      | Check device IP address, ensure you are on the same WiFi network. |
| "Connection failed"       | Check WiFi password, check signal strength, reboot router. |
| IP changes on every boot  | Set static IP in router settings (DHCP MAC reservation). |
| Needs 4G backup           | Set up phone mobile hotspot, connect device to hotspot SSID. |

---

## 7. Troubleshooting No Sound Output

1. Check volume level in the dashboard (AI Settings → Audio Volume, default 80).
2. Check if a mode is active (logs should register object detections).
3. Check logs for "Audio fallback" errors → indicates missing WAV files.
4. Regenerate audio files: `python tools/generate_audio.py --from-wordlist`.
5. Re-deploy audio files: `python tools/deploy.py --audio-only`.
6. Verify physical speaker (test with another audio file directly on the device).

---

## 8. Reading System Logs

- From the dashboard: Logs menu → real-time log stream.
- On the device: `/root/logs/aural_*.log` (auto-rotated: 7 days or 100MB limit).
- Log Format: `[TIMESTAMP] [LEVEL] [MODULE] message`
- TTS Cache: `/root/audio/tts_cache/` — stores WAV files from runtime synthesis.

### Log Levels

| Level | Meaning                                     |
| ----- | ------------------------------------------- |
| OK    | Operation successful                        |
| INFO  | General system information                  |
| WARN  | Warning (system remains functional)         |
| ERROR | Failed operation, attention required        |
| FATAL | Critical crash — device recovery or reboot |

---

## 9. Resetting the Device

### Soft Reset (Restart Application Service)

- Dashboard → click Restart Service.
- Or via SSH: `systemctl restart aural-ai`

### Hard Reset (Reboot Hardware)

- Power cycle the device (unplug and replug; watchdog handles recovery).
- Or via SSH: `reboot`

### Factory Reset Config

```bash
# On device via SSH:
rm /root/config.json
reboot
# Config file will regenerate with defaults
```

### Backup Configuration

```bash
# On PC:
scp root@<maixcam-ip>:/root/config.json ./backup_config_$(date +%Y%m%d).json
```

---

## 10. Routine Maintenance

| Frequency | Task |
| ----------- | ------------------------------------------------------------- |
| Daily | Brief check of dashboard logs to verify no FATAL errors occur. |
| Weekly | Monitor disk usage (`/root/logs/` and `/root/audio/tts_cache/`). |
| Per sprint | Back up config.json from all deployed devices. |
| Per event | Ensure WiFi stability before handing over, test QRIS mode. |

> Log rotation runs automatically (7 days / 100MB). TTS cache does not auto-delete — prune manually if disk becomes full.

---

## 11. Field Logbook

Require each operator to document logs in a notebook or digital form:

- Date & time of event.
- User ID (anonymous: U1, U2, etc.).
- Active operating mode.
- System behavior (audio cues heard vs expected).
- Action taken by operator.
- Whether the issue was resolved.

This logbook data is collected for post-pilot IEEE research reports.

---

## 12. Contacts & Escalation

| Situation | Action |
| --------------------------- | --------------------------------------------------- |
| Minor bug | Record in logbook, proceed with operation. |
| Device unusable | Soft reset → hard reset → contact development team. |
| User data leak (photo/log)  | Power off device immediately, contact dev team. |
| User reports incorrect info | Note details, switch to offline mode, contact dev. |

> **Dev contact:** [Fill in developer name/contact info]  
> **Repository:** `github.com/<username>/AuralAI-SDK`
