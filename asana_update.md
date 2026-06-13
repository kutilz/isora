# AuralAI SDK — Resource Update Asana

Bahan siap-tempel untuk mengisi progress ke Asana. Disusun dari `git log` +
`CHANGELOG.md` + `README.md`.

- **Project:** AuralAI SDK — on-device visual assistant di Sipeed MaixCAM untuk
  membantu tunanetra mengenali lingkungan lewat audio.
- **Cara pakai:** tiap heading `##` = Section/kolom di Asana. Tiap `###` = nama
  task. Teks di bawahnya = deskripsi task (paste ke field Description).
- Semua task dibiarkan terbuka (belum dicentang) — tandai selesai sendiri sesuai
  kondisi sebenarnya.

---

## Phase 0 · Foundation

### Web Dashboard mockup
Dashboard dev awal: camera preview, log stream, dan simulasi physics-based
dengan deteksi yang sinkron ke objek di canvas. Jalan penuh di mode simulasi
tanpa hardware (`device/server/static/index.html`).

### Device Python stack + PC-side tools
Fondasi stack Python untuk MaixCAM + script PC-side (deploy, generate audio,
model converter) di folder `tools/`.

### Companion PC MVP
Jalur Companion: MaixCAM (UI + YOLO lokal) ⇄ PC Flask (OpenAI Vision, MJPEG,
browser TTS). File: `device/aural_maix.py` + `companion/webserver.py`,
`companion/run_desktop.py` (simulasi pakai webcam), `companion/minimal_server.py`
(tes koneksi tanpa OpenAI).

---

## Phase 1 · Core Rewrite (integrasi hardware nyata)

### Event-driven state machine + Config singleton
Rewrite total `orchestrator.py` jadi state machine berbasis event (ganti polling
loop). `config.py` jadi `Config` singleton thread-safe yang di-backing
`/root/config.json` — semua key bisa di-update runtime, dengan alias module-level
backward-compat.

### YOLO11 object detection + Explorer Mode
Inference NPU via `maix.nn.YOLO11`. `release_model()`/`reload_model()` untuk
manajemen memori saat ganti mode. Explorer Mode = deteksi objek offline
(`modes/explorer_mode.py`).

### Priority audio queue
`audio_manager.py`: `threading.PriorityQueue` non-blocking dengan level
CRITICAL/HIGH/NORMAL/LOW, event interrupt untuk preempt prioritas lebih tinggi,
cooldown per-label, konversi WAV→PCM s16le 48 kHz via ffmpeg (cached).

### Watchdog + HealthMonitor + GPIO button
`watchdog.py` (restart berbasis heartbeat), `HealthMonitor` daemon (polling 5s,
callback thermal throttle/recover), dan listener tombol fisik GPIO (falling-edge,
debounce 0.3s). Structured JSON logging di `logger.py`.

### Autostart + camera auto-recover
Autostart data-collection saat boot via `tools/run.py`; recovery otomatis dari
camera read timeout transien (single auto-recover saat `RuntimeError`).

---

## Phase 2 · Detection QA, Benchmark & QRIS

### Benchmark suite 4-test + Safety & Reliability Index
`device/benchmark/`: T1 latency (p95 < 300ms), T2 accuracy (recall/precision),
T3 audio priority (interrupt < 150ms), T4 stability (FPS ≥ 15, zero crash).
`report.py` = Safety & Reliability Index berbobot (T1 35% / T2 30% / T3 20% /
T4 15%), grade A–F + rekomendasi. CLI `run_all.py` + endpoint `/suite/*`.

### Overnight stress test + benchmark streaming UI
Stress test endurance semalaman + UI streaming progress benchmark real-time
(health bar live).

### Scene Description (AI Vision / Context Mode)
Context Mode online: kirim frame ke AI vision untuk deskripsi suasana
(`modes/context_mode.py`).

### QRIS verifier
Decoder QRIS lokal + dispatcher 3-mode (online / offline / hybrid).

### Token auth + presets + encrypted API keys
Auth berbasis token, sistem preset, dan penyimpanan API key terenkripsi via
dashboard UI (autosave).

---

## Phase 3 · Multi-provider AI & Audio

### AI adapters (OpenAI / Gemini / Claude)
Package `device/adapters/` dengan base class `AIAdapter` + 3 implementasi
(OpenAI `gpt-4o-mini`, Gemini `gemini-1.5-flash`, Claude `claude-haiku-4-5`).
Interface seragam: `describe_scene()`, `scan_qris()`, `test_connection()`.
Factory `get_adapter(provider, cfg)`. `ai_engine.py` dialihkan dari call OpenAI
hardcoded ke factory.

### AI Settings UI
`GET/POST /ai-settings` + `POST /ai-settings/test`: pilih provider/model, input
key ter-mask (4 char terakhir saja), prompt editable, test konektivitas. Key
tidak pernah dikembalikan utuh; field key kosong diabaikan (anti hapus key tak
sengaja).

### Hybrid TTS
TTS hybrid: cache WAV lokal + fallback sintesis gTTS (CG-1).

### Log rotation + stack-trace logging
Rotasi log + logging stack trace (CG-3/CG-5).

### Audio progress saat AI call
Cue audio "masih_memproses" tiap 3 detik selama panggilan AI berlangsung (W-3).

### I2C battery HAT probe fix
Probe `/dev/i2c-1`/`/dev/i2c-2` (addr 0x36/0x40); kalau HAT tidak ada,
`battery_info()` balik dict kosong diam-diam — tidak ada `OSError` saat startup,
warning baterai auto-disable. Probe manual via `/i2c-probe` (W-2).

---

## Phase 4 · Companion UI Redesign (WCAG 2.1 AA)

### Vite + Preact + TypeScript scaffold
Source UI di `device/server/src/`. Build output di-commit ke
`device/server/static/app/` (device tanpa Node.js). ~10 KB gz shared chunk +
0.5–9 KB gz per halaman.

### Halaman /guide (publik)
Scroll-page panduan tanpa auth: Hero + Storyboard + Hardware + Audio + pemilih
preferensi audio (C4).

### Wizard /setup (4 langkah)
Wizard first-time: power → wifi → AI key → checklist serah-terima. Redirect dari
`/` saat `setup_completed` masih false (C5).

### Dashboard / (companion)
Dashboard untuk pendamping (guru SLB, keluarga): live view, status, activity
feed (`/history`) (C6).

### Dashboard /admin
Dashboard operator/dev: companion view + AdminRibbon + Debug Overlay + DevSidebar
(log tail + quick actions). Auth `device_token` / `admin_role_token`. Dashboard
lama tetap di `/admin/legacy` (C7).

### Design tokens + a11y bar + keyboard shortcuts
`tokens.css` single-source (served di `/tokens.css`). A11y bar tiap halaman:
high-contrast / large-type / reduced-motion (persist localStorage). Skip-link,
`aria-live`, `role=radiogroup`, hit-target ≥ 48px, shortcut 1/2/3 mode, +/-
volume, ? help.

### i18n + dukungan English
`i18n/{id,en}.json`, dukungan terjemahan English + language switcher aktif.
Status field baru di `/status`: battery, wifi_signal, wifi_ssid, temperature,
last_caption, audio_mode, setup_completed. Config key baru: `audio_mode`
(chime/speech/both), `admin_role_token`, `setup_completed`, `assets_dir`.

---

## Phase 5 · Device Hardening & Onboarding

### Per-device identity + mDNS + spoken-URL onboarding
Identitas per-device, mDNS, onboarding URL yang diucapkan (spoken-URL), + tombol
onboarding. Boleh `device_name` kosong.

### Crash-proof camera failure
Kegagalan kamera tidak lagi bikin crash; device tetap hidup dan informatif.

### Instant offline chimes + boot/ack cues
Object alert memutar chime offline instan; tambahan cue audio boot + ack di
generator audio.

### Autostart rc.local + graceful camera release
Metode autostart via `rc.local` + pelepasan kamera yang graceful saat SIGTERM.

### Companion info: SSID WiFi & status kamera
Tampilkan SSID WiFi & status kamera yang informatif di companion. A11y: target
fokus skip-link, halaman 404 HTML, tooling deploy.

---

## Catatan
- Phase 0–5 di atas mengikuti urutan riwayat repo (Mar–Jun 2026).
- Belum ada section "Next / Backlog" — tambahkan sendiri kalau mau melacak
  kerjaan ke depan (mis. uji deploy di hardware nyata, rekam chime, isi photo
  assets, finalisasi operator runbook).
- Referensi detail per perubahan: lihat `CHANGELOG.md` dan `git log`.
