# I-Sora SDK — Changelog

---

## [Device — uji pemakaian nyata: yang diucapkan alat keluar semua] — 2026-10-29

Uji end-to-end di aural-78a7 (modul bermic + kamera; kini unit I-Sora, config
AuralAI dicadangkan di `/root/config.auralai-backup-20261029.json`): app penuh,
tombol ditekan lewat `POST /button` (handler yang sama dengan tombol fisik),
mic direkam terus, tiap langkah dicocokkan dengan trace audio baru. Run pertama
menemukan masalah di bawah; run kedua setelah perbaikan: 66/66 klip yang
diputar terdengar di mic.

- **"Isora siap digunakan" tidak pernah diucapkan** saat cloud aktif (default)
  kecuali perangkat belum di-pair DAN belum di-setup: onboarding menyerahkan
  ke `cloud.py`, yang diam untuk unit yang sudah di-pair atau yang cloud-nya
  tidak terjangkau. Juga menunggu IP, jadi tanpa WiFi tidak pernah keluar.
  Sekarang salam siap hanya menunggu app (web + audio); hanya prompt setup
  yang menunggu jaringan.
- **Membuka kamera menelan audio yang sedang diputar** (multimedia init
  MaixPy): chime mode saat idle → penjelajah hilang. Buka/tutup kamera kini
  memegang slot audio (`_codec`): klip yang berjalan selesai dulu, klip
  berikutnya menunggu kamera siap. Termasuk Mode Ambil Data.
- **`.pcm` kosong (0 byte) dipercaya selamanya** kalau stempel mtime-nya
  cocok: "mode idle" di aural-78a7 tidak pernah bersuara. Cache kosong kini
  selalu dibuat ulang (juga cek salam boot di `main.py` dan `S00`).
- **ACTION direbut pairing di semua mode** selama belum di-pair, walau API key
  sudah ada: deskripsi dan navigasi daring hanya menjawab "Gagal
  menghubungkan". Sekarang ACTION = pairing hanya di idle, atau di mode mana
  pun kalau belum ada API key.
- **Navigasi daring diam kalau tidak ada yang perlu disebut.** Jawaban penanda
  "Belum ada yang perlu disebut." tidak lagi dibacakan tiap ~8 detik.
- **Replay klip yang terpotong dibatasi umur (30 s)**, bukan 2 kali: orang di
  depan kamera memicu "orang di depan dekat" tiap ~1,5 s dan balasan pairing di
  bawahnya hilang setelah 3 detik.
- **Trace audio** `GET /audio/trace?since=<seq>`: tiap klip yang diminta dan
  nasibnya (played / cut lalu diulang / dropped + alasan: flushed, cooldown,
  stale, play-failed…). Untuk menjawab "kenapa tadi tidak bunyi" di lapangan.

---

## [Device — audio: tidak ada klip yang hilang tanpa sengaja] — 2026-10-29

Hasil QA audio: setiap klip yang bisa diminta program dipetakan (258 klip:
11 chime, 25 cue sistem, 6 kalimat, 216 peringatan navigasi) lalu dicek
statis dan diputar di unit.

- **Klip yang terpotong peringatan diputar ulang.** Nama mode, nominal uang,
  atau satu kalimat deskripsi yang ditimpa peringatan rintangan dulu hilang
  begitu saja; sekarang dimasukkan lagi ke antrean (maks. 2 kali, posisinya
  tetap di depan klip yang lebih baru). Klip yang dibatalkan tombol/ganti mode
  tetap dibuang, termasuk yang sudah terlanjur diambil play loop.
- **Interrupt tidak lagi tertelan.** Peringatan mendesak yang masuk tepat saat
  klip lain mulai dulu menunggu klip itu selesai, lalu dibuang oleh batas basi
  nav 3 s.
- **Mode "speech" tanpa internet** memakai rekaman WAV kalau TTS gagal (dulu
  diam). **Error driver** saat membuka Player dicoba sekali lagi.
- **Cache PCM**: `deploy.py` mempertahankan mtime file, jadi `.pcm` tetap valid
  setelah deploy (dulu hanya 13 dari 427 WAV yang punya `.pcm`, sisanya kena
  ffmpeg 0,2-0,4 s (lebih untuk kalimat panjang) saat pertama diputar, termasuk
  "orang di depan", dan bisa gagal saat RAM sempit). App
  meng-convert semua WAV yang belum punya `.pcm` di background 20 s setelah
  boot (`nice`, satu per satu, hanya saat hening); konversi ditulis ke tmp lalu
  di-rename.
- **Dua klip baru** (dulu hanya lewat cloud TTS, diam saat offline):
  "Perangkat sudah terhubung." (pairing berhasil) dan "Kamera belum aktif.
  Tekan tombol mode dulu."
- **`import maix` pertama kini pasti di main thread** (`main.py`). maix
  memasang signal handler saat di-import; kalau import pertama terjadi di
  thread AudioMgr, SETIAP klip gagal ("signal only works in main thread") dan
  alat diam total. Selama ini hanya kebetulan tercegah oleh import comm
  listener, yang dilewati kalau `maix_comm_listener` aktif. Error import selain
  ImportError sekarang di-log, tidak ditelan.
- Test `test_audio_no_skip.py`: setiap `queue_system`/`queue_cue`/kalimat di
  kode wajib punya sumber di `generate_audio.py`/wordlist.

Diuji di isora-88dd (29 Okt, app dihentikan, AudioManager + Player asli):
258/258 klip diputar lewat API yang sama dengan program, 0 butuh cloud TTS,
0 error driver, 0 terpotong, tidak ada PCM yang hening/terpotong (0,16–4,18 s),
tiap klip menahan slot selama durasinya. Skenario: nama mode ditimpa "orang di
depan dekat" → peringatan diputar lalu nama mode diulang utuh; tombol ditekan
saat kalimat diputar → kalimat dibatalkan, chime tombol terdengar.

Uji akustik di modul bermic (aural-78a7; kode + audio I-Sora dari folder uji
terpisah, firmware AuralAI-nya tidak diubah): mic direkam terus dengan
`arecord` selama 258 klip + 2 skenario. Setiap putaran (263) terdengar di
jendela waktunya sendiri dengan SNR ≥ 20 dB (median 28,7 dB) di atas noise
floor, dan 259/259 jeda antar klip kembali ke noise, jadi suara tiap klip
benar-benar milik klip itu. `maix.audio.Recorder` tidak bisa dipakai untuk ini
(tidak merekam selama Player aktif); jam capture ADC lebih cepat 0,8% dari
`time.monotonic`, jadi analisis memakai pemetaan waktu yang dikoreksi drift.

---

## [Device — supervisor app + pengerasan server lokal] — 2026-10-29

Alat tidak boleh diam di tengah presentasi, dan pengguna tunanetra tidak bisa
melihat kenapa alat diam. Sebelumnya `main.py` dijalankan sekali dengan nohup:
crash (SIGSEGV saat load model, OOM) atau macet di driver kamera = diam sampai
daya dicabut.

- **Supervisor** `device/system/supervise.sh` → `/etc/isora/supervise.sh`,
  dijalankan oleh `S26isoraapp`. App crash → hidup lagi (backoff 2/5/30 s).
  App macet (loop AI berhenti berdetak > 45 s, `utils/liveness.py` →
  `/tmp/isora_alive`, + 30 s) → SIGKILL lalu start ulang. Tiga kali gagal
  beruntun, atau proses tak bisa di-kill → **satu kali reboot**, tidak lagi
  sampai ada run sehat 5 menit. Exit 0/130/143 (stop yang disengaja) tidak
  di-restart, jadi `kill`, `S26isoraapp stop`, `run.py --stop` tetap berlaku.
  Rilis trial yang crash terus di-rollback lewat hitungan start `release.py`.
  Log `/tmp/isora_main.log` dipangkas di 2 MB (RAM); riwayat supervisor di
  `/root/isora_supervisor.log` (bertahan setelah reboot).
- **Server web**: timeout socket 20 s (klien yang tidak mengirim body tidak
  lagi menahan thread selamanya); body POST > 256 KB atau Content-Length
  negatif/rusak ditolak sebelum dibaca.
- **CORS** default `[]` (unit lama dimigrasi dari `["*"]`): halaman web lain
  di WiFi yang sama tidak bisa membaca `/snapshot`. Origin yang tidak terdaftar
  tidak lagi dibalas `Access-Control-Allow-Origin: null` (iframe sandbox
  mengirim `Origin: null`, jadi itu sama saja membuka). `POST /config` tidak bisa
  lagi mengganti `cloud_base_url`, `cloud_device_id`, `device_pubkey`,
  `cors_allowed_origins`.
- **E2E**: titik ECDH di luar kurva P-256 ditolak (invalid-curve attack).
- **QRIS hybrid**: kalau QR gagal di-decode lokal, teks AI tidak lagi dibacakan
  dengan chime sukses — chime error + "Perkiraan AI, belum pasti … mohon
  pastikan nominal ke kasir". `qris_log.json` dibatasi 200 entri, ditulis atomik.

Butuh `python tools/run.py --autostart` sekali per unit supaya supervisor
terpasang di `/etc`; tanpa itu init script tetap jalan cara lama.

Diuji langsung di isora-88dd (USB, 29 Okt): `kill -9` → hidup lagi dalam 3 s;
`kill -STOP` (simulasi macet) → terdeteksi setelah 35 s tanpa detak, di-kill,
hidup lagi 3 s kemudian, tanpa reboot; reboot → supervisor jalan dari boot,
detak pertama di uptime 20 s; `S26isoraapp stop` → tidak di-respawn; start dua
kali → tetap satu app. RAM tidak berubah (±67 MB terpakai).

---

## [Device — Mode PIMNAS: profil acara + tombol suara] — 2026-10-28

Halaman operator `http://<ip-alat>:8080/pimnas` untuk orang kedua yang memegang
ponsel (sekaligus hotspot alat) saat presentasi. Jalan di LAN, tanpa internet.

- Saklar **Mode PIMNAS** (`event_mode`): auto-update tidak mengunduh dan tidak
  me-restart; deskripsi menyerah setelah `event_ai_timeout_s` (10 s, bukan 15);
  kalau gagal, alat membacakan hasil YOLO dari frame saat itu ("orang di
  depan") — mode konteks ikut memuat model nav untuk itu. Ambil data,
  benchmark, dan stress test ditolak (423).
- **Tombol suara**: ketik kalimat → dirender sekali (butuh internet) → jadi
  tombol yang diputar tanpa internet. Disimpan di
  `/root/audio/pimnas_presets/`, terpisah dari cache TTS yang dipangkas.
  Maks 40 tombol, 300 huruf; bisa diurutkan dan dihapus (mode Atur).
- Status (mode, baterai, suhu, WiFi, kalimat terakhir), siapa yang terakhir
  menekan tombol (alat / ponsel), pindah mode langsung, ACTION, Deskripsikan,
  Hentikan suara, volume (min 20%), cek sebelum tampil, kamera opsional.

---

## [Device — mode scan bayar: uang kertas + QRIS bergantian] — 2026-10-27

Mode scan bayar (`qris`) sekarang terus memindai, tidak lagi diam menunggu
ACTION. Tiap tick membaca satu frame dan memakainya untuk SATU dari dua hal,
bergantian: model uang di NPU, atau pencari QR bawaan MaixPy.

- Uang kertas diucapkan sekali saat muncul ("lima puluh ribu rupiah", WAV
  luring); dipegang terus tidak diulang, ditaruh lalu ditunjukkan lagi diucapkan
  lagi (`utils/money.PresenceTracker`). Dua lembar sekaligus: terbesar dulu.
- QRIS didekode di device dan dibacakan merchant + nominal (formatter yang sama
  dengan scan ACTION); QR lain → "bukan kode pembayaran". Tidak ada yang
  diucapkan di atas audio lain.
- ACTION tetap menjalankan scan QRIS lengkap dengan cek silang AI.
- Model: YOLO26n uang (dari `Hasil Training.zip`), dikonversi ke cvimodel
  cv181x INT8 + head BF16, dibaca decoder `nn.YOLOv8` MaixPy 4.5.1. 10,3 ms per
  frame, 34/40 di test split. Cara membuat ulang: `tools/money_model/README.md`.
  File model TIDAK ikut `tools/deploy.py` — salin manual ke `/root/models/`.
- `AIEngine`: model per mode (`Orchestrator._MODE_MODELS`, menggantikan
  `_YOLO_MODES`); engine dibuka langsung dengan model mode saat itu (sebelumnya
  selalu memuat model nav lalu dibuang lagi di mode konteks); model yang gagal
  dimuat dicoba lagi paling cepat tiap 30 s, bukan tiap tick.
- `read_qr()` mengecilkan frame > 320×240 sebelum `find_qrcodes()` — di gambar
  besar fungsi MaixPy itu SIGSEGV (terukur di device).
- Audio baru: `system_{seribu..seratus_ribu}_rupiah.wav`,
  `system_bukan_kode_pembayaran.wav`.
- Diuji di isora-88dd: pergantian model explorer ↔ scan bayar di app, dan
  `run_pay_tick` asli dengan frame suntikan (kamera unit ini belum terdeteksi).
  Belum diuji dengan kamera dan uang asli.

---

## [Device — navigasi daring di mode penjelajah] — 2026-10-26

ACTION (tekan pendek) di mode penjelajah sekarang menyalakan/mematikan
**navigasi daring**: YOLO tetap berjalan untuk peringatan bahaya, dan tiap
`scan_interval_s` (default 8 s) sebuah foto dikirim ke AI dengan prompt pendek
khusus orang berjalan (`scene_prompt.SCENE_PROMPT_SCAN`: bahaya → jalur →
tulisan papan, maks. 15 kata). Long-press ACTION tetap mengulang hasil
terakhir. Deskripsi sekali tekan tetap ada di mode konteks.

- `modes/scan_narrator.py`: maksimal satu panggilan berjalan; foto berikutnya
  menunggu interval DAN sampai kalimat sebelumnya selesai diputar; jawaban yang
  tiba > `scan_stale_s` (6 s) setelah fotonya dibuang; gagal diucapkan sekali per
  gangguan lalu dicoba lagi tiap `scan_retry_s` (15 s); mati sendiri saat mode
  diganti. Panggilan cloud dan pengucapan berjalan di worker thread — AI loop
  hanya meng-encode JPEG (terukur di isora-88dd: `step()` terburuk 2,7 ms;
  sebelumnya 716 ms karena concat word-cache berjalan di thread pemanggil).
- Selama narasi diputar, penjelajah hanya mengucapkan bahaya (narasi LOW
  priority akan terpotong oleh setiap peringatan HIGH).
- `AudioManager.is_quiet()`; `speak_scene(still_wanted=...)` supaya kalimat yang
  sedang dirender tidak terucap setelah "navigasi daring mati". Loop audio kini
  mengosongkan `_current_text` juga saat `_play_task` melempar exception —
  sebelumnya status "sedang bicara" bisa macet selamanya.
- Interval bisa diatur dari `/buttons` (slider 3–60 s) dan dari app cloud
  `/app/[id]` (`scan_interval_s` masuk `ALLOWED_CONFIG_KEYS`, di-clamp di read
  site). Heartbeat melaporkan `scan_active` + `scan_interval_s`.
- Audio baru: `system_navigasi_daring_aktif.wav`, `system_navigasi_daring_mati.wav`
  (`python tools/generate_audio.py`, lalu salin ke `/root/audio/`).
- Tanpa API key: ACTION mengucapkan "API tidak tersedia" dan tetap luring.
- Catatan: selama device belum di-pair dan cloud aktif, ACTION di mode apa pun
  tetap dipakai untuk pairing (perilaku lama).

---

## [Web — PWA, Settings app, and camera simulator] — 2026-09-11

Reshapes `web/` around two jobs: an installable app for people who own a
device, and a phone-camera simulator for people who don't yet.

### Installable app (PWA)

- `app/manifest.ts`, `public/sw.js`, `lib/pwa.ts`, `components/InstallCard.tsx`,
  `public/icons/*` (regenerate: `node scripts/gen-icons.mjs`).
- Service worker: network-first navigation with an `/offline` fallback,
  cache-first for build output and media, and a separate long-lived bucket for
  the ~6 MB TFJS model so a deploy doesn't force a re-download.
- `start_url` is `/app` — the installed app opens on your devices, not on
  marketing copy.

### `/app` — a phone-Settings-style shell

- New route groups: `app/(marketing)` keeps `Nav`/`Footer`; `app/(shell)`
  carries its own `AppBar` per screen.
- `/app` device list → `/app/[id]` device settings → `/app/tambah` pairing.
- `/pair` and `/dashboard` are now redirects (the `?code=` deep link still
  lands on the spoken-code tab).
- `DELETE /api/devices/:id` releases a device from the account.

### Pairing: automatic first

- `GET|POST /api/pair/nearby` — devices and phones that reach the relay from
  the same public IP are on the same WiFi, so unclaimed devices "here" can be
  listed and claimed with one tap. Offered **only** when exactly one candidate
  is visible, because CGNAT can share an IPv4 between households; anything
  ambiguous falls back to QR or the spoken code.
- `devices.net_hash` stores a **keyed hash**, never a raw IP (`lib/net.ts`).
  The same signal drives `same_network`, which decides whether the app offers a
  device's LAN control link.
- `device/core/cloud.py` heartbeat now also reports `local_ip_url`; the app
  prefers it over `<name>.local`, which Chrome on Android cannot resolve.

### `/simulasi` — the device, run on a phone camera

- `lib/sim/` ports the real decision code: `vision.ts` ←
  `utils/logger.position_from_bbox` + `utils/distance.band`; `announce.ts` ←
  `utils/announce_policy.decide`; `constants.ts` ← `config.NAV_OBJECTS`, the
  thresholds, and `audio_manager`'s phrase maps.
- COCO-SSD (TensorFlow.js) stands in for YOLO11n; WebAudio panned chimes and
  Web Speech (`id-ID`) stand in for the pre-rendered WAVs.
- One big tap-target emulates the device's single button (short = re-read,
  long = describe). QRIS mode reads EMVCo tag 59. Debug panel shows boxes,
  tier, `area_ratio`, and inference time.
- "Jelaskan sekitar" uses the user's own OpenAI/Gemini key, kept in
  `localStorage` and sent straight to the provider — never through I-Sora.

### Schema

Re-run `web/supabase/schema.sql` (idempotent): adds `devices.net_hash`, a
partial index for the nearby lookup, and column-level `UPDATE` grants so a
signed-in browser can no longer overwrite `secret_hash` or `pubkey`.

---

## [Phase 4 — Companion Redesign] — 2026-05-21

Implements the `design_handoff_isora_redesign/` package: split the operator
dashboard into three audience-specific interfaces plus a first-time setup
wizard, all WCAG 2.1 AA compliant.

### New routes

- `GET /`                       — Companion dashboard for pendamping (guru SLB,
                                  keluarga). Redirects to `/setup` when
                                  `setup_completed` is false.
- `GET /admin`                  — Operator/dev dashboard. Wraps the companion
                                  view + adds AdminRibbon, Debug Overlay,
                                  DevSidebar with log tail + quick actions.
- `GET /guide`                  — Public scroll-page panduan (no auth). Hero
                                  + Storyboard + Hardware + Audio + Audio
                                  preference picker.
- `GET /setup`                  — 4-step first-time wizard (power → wifi →
                                  AI key → handover checklist).
- `GET /admin/legacy`           — Original operator dashboard
                                  (`static/index.html`), kept reachable.
- `GET /tokens.css`             — Design tokens (single source of truth).
- `GET /audio/chimes/manifest.json`
                                — Lists pre-recorded chime WAVs; frontend
                                  hides the "Putar" column when empty.
- `GET /assets/manifest.json`   — Lists available photo assets; frontend
                                  swaps SVG mockups for photos when files
                                  exist in `/root/assets/`.
- `GET /assets/<name>`          — Static asset serving with mime guess +
                                  immutable cache headers.
- `GET /history?date=today`     — Activity feed (parsed from log buffer).
- `GET /app/<...>`              — Hashed JS/CSS chunks from the Vite build.

### New config keys

- `audio_mode`: `"chime"` | `"speech"` | `"both"` (default `"both"`).
  AudioManager `_play_task` now honors this: chime mode drops TTS fallback,
  speech mode bypasses pre-recorded chimes.
- `admin_role_token`: optional separate token for admin role. Empty =
  device_token grants admin too.
- `setup_completed`: bool gate for first-time wizard redirect.
- `assets_dir`: filesystem path for `/assets/<name>` serving (default
  `/root/assets`).

### New status fields

`GET /status` now returns:

- `battery` (int 0..100 or `null` when no calibrated HAT)
- `wifi_signal` (0..4 bars from `/proc/net/wireless`)
- `wifi_ssid` (`iwgetid -r`)
- `temperature` (CPU °C)
- `last_caption` (`{text, time_iso, priority}`)
- `audio_mode`
- `setup_completed`

### UI build pipeline

- **New** `device/server/src/` — Vite + Preact + TypeScript source for the
  four new pages. Builds into `device/server/static/app/` which is committed
  (device has no Node.js). Total runtime ~10 KB gz shared chunk + 0.5-9 KB
  gz per page. Dev: `cd device/server/src && npm install && npm run build`.
- **New** `device/server/static/tokens.css` — design tokens, served at
  `/tokens.css` and linked from every entry HTML. Edit-and-reload, no
  rebuild needed.
- **New** `device/server/src/i18n/{id,en}.json` — id.json populated; en.json
  is a stub. See `device/server/src/README.md` for the 3-step EN swap-in.

### Audio manager

- `current_text` companion property `last_caption` now exposes the most
  recent caption with timestamp + priority, persists after playback ends.
- `_play_task` checks `cfg.AUDIO_MODE` per task — change the preference via
  `POST /config { "audio_mode": "..." }` and the next task respects it.

### Accessibility (WCAG 2.1 AA)

- A11y bar on every new page: high-contrast / large-type / reduced-motion,
  persisted to localStorage.
- Skip-link "Lewati ke konten utama" first focusable element.
- `aria-live="polite"` on StatusBanner + LiveView last-caption.
- `role="radiogroup"` + `role="radio"` for mode + audio-mode pickers.
- Hit-targets ≥ 48 px via `--hit` token.
- Keyboard shortcuts 1/2/3 mode, +/- volume, ? help. Skipped when an input
  has focus.
- `<html lang="id">` set at runtime via lib/i18n.

### Files

- `device/config.py` — `_DEFAULTS` + typed properties
- `device/server/web_server.py` — new routes
- `device/core/orchestrator.py` — `get_status()` + telemetry helpers
- `device/core/audio_manager.py` — `last_caption` + audio_mode gating
- `device/server/static/tokens.css` (new)
- `device/server/static/app/` (new — built artifact)
- `device/server/src/` (new — Preact source)
- `design_handoff_isora_redesign/` (vendored handoff package)

---

## [Phase 3] — 2026-05-14

### AI Vision API Adapters

- **New: `device/adapters/` package** with unified `AIAdapter` base class and three provider implementations:
  - `OpenAIAdapter` — Chat Completions with `image_url` (base64 inline); `gpt-4o-mini` default
  - `GeminiAdapter` — `generateContent` REST v1beta with `inlineData`; `gemini-1.5-flash` default
  - `ClaudeAdapter` — Anthropic Messages API with `image` content blocks; `claude-haiku-4-5` default
  - All adapters share `describe_scene()`, `scan_qris()`, and `test_connection()` interface
  - Factory function `get_adapter(provider, cfg)` selects adapter based on active provider
- **Updated `device/core/ai_engine.py`** — replaced hardcoded OpenAI calls in `trigger_scene_description()` and `trigger_qris_scan()` with `get_adapter(cfg.AI_PROVIDER, cfg)`; no structural changes to the inference pipeline

### Config Changes

- **Updated `device/config.py`**:
  - New keys: `ai_provider` ("openai"/"gemini"/"claude"), `ai_timeout_s`, `gemini_api_key`, `gemini_model`, `claude_api_key`, `claude_model`
  - `prompt_scene` and `prompt_qris` moved from class-level string constants → runtime-editable config keys (backed by `/root/config.json`)
  - New typed properties: `AI_PROVIDER`, `AI_TIMEOUT_S`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `CLAUDE_API_KEY`, `CLAUDE_MODEL`, `PROMPT_SCENE`, `PROMPT_QRIS`

### Web UI — AI Settings

- **New `GET /ai-settings`** — returns active provider, model names, key presence hints (last 4 chars), and prompts; API keys are never returned in full
- **New `POST /ai-settings`** — saves provider/model/key/prompt changes; empty key fields are ignored (no accidental key erasure)
- **New `POST /ai-settings/test`** — tests live connectivity to the configured adapter using a minimal text-only call
- **Updated `device/server/static/index.html`** — "AI Settings" button in controls bar; full settings modal with provider selector tabs, model dropdowns, masked API key inputs, editable prompts, test button, and save/cancel
- **Updated `device/server/static/style.css`** — styles for AI settings modal, provider tab buttons, key hint, test result badge

### Bug Fixes

- **`device/utils/health.py` — I2C battery HAT probing**: probes `/dev/i2c-1`/`/dev/i2c-2` at addresses 0x36/0x40 on import; `battery_hat_present()` and `battery_info()` return empty dict silently if no HAT is found — no more `OSError` at startup and battery audio warnings are disabled automatically
- **`device/core/audio_manager.py` — `player.stop()` AttributeError**: `_play_pcm()` now catches `AttributeError` separately from other exceptions; when `stop()` is missing the method returns immediately so the higher-priority task starts without waiting for the full PCM deadline
- **`device/core/audio_manager.py` — `_current_text` tracking**: new `current_text` property (thread-safe) exposes the text currently being played; set on `_play_task` entry, cleared on exit
- **`device/core/orchestrator.py` — `audio_text` in status**: `get_status()` now includes `"audio_text"` from `audio_manager.current_text` so the `/status` endpoint delivers the playing text without the removed `pop_audio()` deque
- **`device/server/web_server.py` — simplified `_serve_status()`**: removed the now-redundant `pop_audio()` call; `audio_text` arrives directly from `get_status()`
- **`device/server/static/dashboard.js` — removed Web Speech API**: `showAudioText()` is now a pure visual log update; `window.speechSynthesis` calls removed entirely; device speaker is the only audio output

---

## [Phase 2] — 2026-05-13

### Standardized Benchmark Suite

- **`device/benchmark/t1_latency.py`** — End-to-End Latency: measures cam/infer/post/queue stages; p95 < 300 ms to pass; score 0–100
- **`device/benchmark/t2_accuracy.py`** — Detection Accuracy: recall/precision on `/root/test_images/`; critical recall ≥ 95%; skips gracefully if no dataset
- **`device/benchmark/t3_audio.py`** — Audio Priority: simulates CRITICAL→LOW interrupt (must succeed within 150 ms); PriorityQueue ordering; cooldown isolation
- **`device/benchmark/t4_stability.py`** — Hardware Stability: full pipeline endurance for configurable duration; FPS ≥ 15 and zero crashes to pass; per-minute snapshots
- **`device/benchmark/report.py`** — Safety & Reliability Index: weighted sum T1×35% + T2×30% + T3×20% + T4×15%; grades A/B/C/D/F; Indonesian recommendations
- **`device/benchmark/run_all.py`** — CLI entry point; `--tests`, `--t1-frames`, `--t4-duration`, `--report-only`; live progress to `/tmp/bench_suite_progress.json`
- **`device/server/web_server.py`** — added `BenchmarkSuiteRunner` class and `/suite/start`, `/suite/stop`, `/suite/progress`, `/suite/report` endpoints

---

## [Phase 1] — 2026-05-12

### Core Rewrite — Real Hardware Integration

#### `device/config.py`

- Full rewrite as thread-safe `Config` singleton backed by `/root/config.json`
- `cfg.update(mapping)` persists to disk; all config keys runtime-updatable
- Backward-compat module-level aliases (`from config import X` still works)

#### `device/core/orchestrator.py`

- Event-driven state machine replacing polling loop
- `switch_mode()` releases/reloads NPU model based on `_YOLO_MODES`
- GPIO hardware button listener (falling-edge, 0.3 s debounce) via `cfg.button_pin_mode`
- Thermal throttle callbacks (`_on_thermal_throttle`, `_on_thermal_recover`)
- `_mode_event` (threading.Event) for zero-latency mode-change wakeup in AI loop

#### `device/core/ai_engine.py`

- NPU inference via `maix.nn.YOLO11`
- `release_model()` / `reload_model()` for mode-switch memory management
- `release()` / `reload()` as watchdog restart functions
- Single auto-recover on camera `RuntimeError`
- Watchdog heartbeat on every successful pipeline tick

#### `device/core/audio_manager.py`

- Non-blocking `threading.PriorityQueue` with levels CRITICAL(0)/HIGH(1)/NORMAL(2)/LOW(3)
- `_interrupt` event for immediate higher-priority preemption
- Cooldown map per label; per-priority stable ordering via sequence counter
- WAV → PCM s16le 48 kHz conversion via ffmpeg (cached)

#### `device/utils/health.py`

- Added `HealthMonitor` daemon: polls every 5 s; fires `on_throttle`/`on_recover` callbacks

#### `device/utils/logger.py`

- Structured JSON logging: `{"ts":…, "level":…, "module":…, "msg":…}`

#### `device/core/watchdog.py` (new)

- Heartbeat-based watchdog; `max_misses × check_interval_s` before `restart_fn()` is called

#### `device/main.py`

- Wires Watchdog, HealthMonitor, Orchestrator, WebServer together

#### `device/server/web_server.py`

- `_handle_config()` now calls `cfg.update(data)` (was a no-op)
- `pop_audio()` stub on Orchestrator for backward-compat (returns None)
