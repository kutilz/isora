# I-Sora — Rencana Benchmark In-Situ (Mode Penjelajah & Mode Konteks)

Benchmark **akurasi + reliability** (bukan cuma performa) untuk dua mode inti,
dijalankan di ruangan lab ~5×5 m dengan operator di lapangan.

- **Software/SSH:** dipegang Claude (verifikasi config, jalankan tooling, hitung metrik).
- **Hardware/eksekusi:** dipegang operator (tandai lantai, susun scene, gerakkan objek, tekan tombol-sim, isi rubrik).
- **Device:** MaixCAM @ `10.144.124.103` (SSH `root`/`root`) atau USB CDC-NCM. Web API di `:8080`.
- QRIS **ditunda** sesi ini (fokus explorer + konteks dulu).

> Toolkit instrumentasi sudah dibuat di `device/benchmark/field/` dan sudah
> diverifikasi end-to-end dengan data sintetis. Lihat §4–§7 untuk perintahnya.

---

## 1. Model mental dua mode (dari kode)

|            | Mode Penjelajah (`explorer`)                                                     | Mode Konteks (`context`)                           |
| ---------- | -------------------------------------------------------------------------------- | -------------------------------------------------- |
| Sifat      | **Offline**, jalan tiap tick (real-time)                                         | **Standby**, aktif saat command `describe`         |
| Inti       | YOLO11n @ 320×224, 12 objek nav                                                  | Cloud vision (OpenAI/Gemini/Claude) → deskripsi ID |
| Output     | Alert nav ("orang di kanan dekat")                                               | Kalimat deskripsi + TTS (per-word cache)           |
| Knob kunci | `conf_threshold=0.6`, de-flicker (`min_streak=3`), tier near/far, AnnouncePolicy | verbosity `sedang/detail`, word-cache, timeout 15s |

---

## 2. Metrik & target (master)

Di-ground ke `device/config.py`. Semua dicek otomatis oleh `analyze.py`.

### Blok A — Explorer: Akurasi & Keselamatan

| Metrik                                                  | Target    | Sumber                 |
| ------------------------------------------------------- | --------- | ---------------------- |
| Recall objek kritis (orang/mobil/motor/bus/truk/sepeda) | ≥ 95%     | stream deteksi vs mark |
| Recall objek umum (kursi/anjing)                        | ≥ 90%     | idem                   |
| Recall objek kecil (botol/tas/ransel/kucing)            | ≥ 70%     | idem                   |
| Time-to-announce (deteksi → suara) **median**           | ≤ 800 ms  | caption-change         |
| Time-to-announce **p95**                                | ≤ 1500 ms | caption-change         |
| Akurasi posisi (kiri/tengah/kanan)                      | ≥ 90%     | stream deteksi vs mark |
| Akurasi tier (near/far)                                 | ≥ 85%     | stream deteksi vs mark |

### Blok B — Explorer: Anti-spam & Recovery

| Metrik                             | Target                                 |
| ---------------------------------- | -------------------------------------- |
| Phantom saat scene kosong          | ≤ 1 / 5 menit                          |
| Deteksi saat **lensa tertutup**    | 0                                      |
| Announce saat lensa tertutup       | 0                                      |
| Re-announce objek bahaya diam      | ~tiap 3 s (`announce_danger_remind_s`) |
| Flapping tier near↔far objek batas | 0 flip (histeresis)                    |

### Blok C — Explorer: Performa & Endurance (suite lama)

Pakai `T1` (latency) + `T4` (endurance) yang sudah ada. Target: T1 p95 < 300 ms; T4 min FPS ≥ 15, **zero crash**, suhu < 80 °C.

### Blok D — Konteks: Akurasi & Kegunaan Deskripsi (rubrik manual)

| Metrik                          | Target |
| ------------------------------- | ------ |
| Recall objek kunci yang disebut | ≥ 80%  |
| Posisi benar                    | ≥ 80%  |
| **Hallucination rate**          | ≤ 10%  |
| Kegunaan navigasi (1–5)         | ≥ 4.0  |

### Blok E — Konteks: Latency & Cache (otomatis dari driver)

| Metrik                                 | Target    |
| -------------------------------------- | --------- |
| Warm (cache hit) → audio mulai, median | ≤ 1500 ms |
| Cold (synth) total (gemini+audio) p95  | ≤ 9000 ms |
| Cache hit-rate setelah warm-up         | ≥ 70%     |

### Blok G — Reliability Lintas-Mode

| Metrik                                          | Target         |
| ----------------------------------------------- | -------------- |
| Mode-switch sukses (50× cycle)                  | 100%           |
| `status_fail` (proxy crash)                     | 0              |
| Barge-in: deskripsi kedengar saat explorer spam | ya             |
| Cue offline benar saat WiFi mati                | ya             |
| Suhu max / FPS min sepanjang sesi               | < 80 °C / ≥ 15 |

---

## 3. Logistik ruangan 5×5 m

- **Lakban lantai**: garis jarak @ **1 / 2 / 3 / 4 m** dari device, + garis kolom **kiri / tengah / kanan** (FoV).
- **Pencahayaan**: minimal 2 kondisi — terang normal & redup (ulang Blok A di kedua kondisi).
- **Kit objek**: helper (orang), kursi, botol, tas, ransel; opsional sepeda.
- **Network**: WiFi + API key aktif (Blok D–E). Siapkan cara matiin WiFi cepat (Blok G).
- **Catat** suhu ambient ruangan (interpretasi thermal).

---

## 4. Toolkit instrumentasi (`device/benchmark/field/`)

| File                           | Fungsi                                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| `recorder.py`                  | Poll `GET /status` → `events.jsonl` (deteksi, latency, caption, scene_metrics, suhu) |
| `mark.py`                      | Tandai ground-truth ke `marks.jsonl` (operator ketik saat kejadian)                  |
| `driver.py`                    | Otomasi trigger: `describe` (D/E), `modeswitch`/`describe1` (G), `config`            |
| `analyze.py`                   | Hitung semua metrik Blok A/B/D/E/G → `report.json` + ringkasan konsol                |
| `templates/context_rubric.csv` | Lembar penilaian Blok D (diisi operator)                                             |

**Prinsip akurasi:** `get_status()` melakukan subprocess (wifi) tiap panggil →
polling cepat membebani device 1-core dan mengganggu ukuran latency. Jadi:

- **Konten** (recall/posisi/tier/phantom): `--hz 2..3` (aman).
- **Latency window** (Blok A): boleh `--hz 8` tapi durasi pendek; atau pakai
  *in-process tracer* (lihat §8) untuk presisi penuh tanpa beban subprocess.

Hasil per sesi tersimpan di `/root/logs/field/<sesi>/`.

---

## 5. Pra-tes checklist (Claude, via SSH, saat device nyala)

1. SSH masuk, pastikan app jalan & web API hidup: `curl -s localhost:8080/status | head`.
2. Verifikasi config relevan: `conf_threshold`, `detection_min_streak`, `distance_near_area`, `ai_provider` + API key (via `/ai-settings` test).
3. Cek `scene_metrics` & word-cache aktif (`word_cache_enabled`).
4. Pastikan jam device konsisten (semua tooling pakai jam ini).
5. Mulai recorder untuk sesi pertama (lihat §6).

---

## 6. Protokol per blok (perintah persis)

> Jalankan **semua** di device via SSH (satu jam). Ganti `<APP>` dgn folder app
> di device (mis. `/root/isora`). Sesi = folder hasil.

### Blok A — Explorer akurasi (sesi `explorerA`)

```bash
# 1) Recorder (window latency, hz lebih tinggi). Biarkan jalan.
python3 <APP>/device/benchmark/field/recorder.py --session explorerA --hz 8 &

# 2) Operator jalankan skenario; tandai SAAT kejadian:
#    orang masuk dari kanan ~3m, mendekat ke 1m, lalu keluar:
python3 <APP>/device/benchmark/field/mark.py explorerA enter person kanan 3 far
python3 <APP>/device/benchmark/field/mark.py explorerA move  person kanan 1 near
python3 <APP>/device/benchmark/field/mark.py explorerA exit  person
#    kursi diam di tengah 2m:
python3 <APP>/device/benchmark/field/mark.py explorerA enter chair tengah 2 far
python3 <APP>/device/benchmark/field/mark.py explorerA exit  chair
#    ulang utk botol/tas (kiri/kanan, dekat), dan ULANG semua di cahaya redup:
python3 <APP>/device/benchmark/field/mark.py explorerA phase "cahaya redup"
# 3) Stop recorder: touch /tmp/isora_field_stop   (atau kill %1)
```

Tips ground-truth tier: isi `near` kalau objek dalam jarak reaksi (≤ ~1.5 m), `far` kalau lebih jauh. Tanpa tier, segmen itu dilewati untuk cek tier (recall/posisi tetap dihitung).

### Blok B — Explorer anti-spam (lanjut di sesi sama / `explorerB`)

```bash
python3 <APP>/device/benchmark/field/recorder.py --session explorerB --hz 3 &
# scene kosong diam 5 menit:
python3 .../mark.py explorerB empty_start ;  # (tunggu 5 menit)  ; python3 .../mark.py explorerB empty_end
# lensa ditutup 2 menit:
python3 .../mark.py explorerB cover ;        # (tutup lensa 2 menit) ; python3 .../mark.py explorerB uncover
# objek bahaya diam (uji re-announce + flapping), 1 menit:
python3 .../mark.py explorerB static person tengah 1 near
python3 .../mark.py explorerB exit person
# stop: touch /tmp/isora_field_stop
```

### Blok C — Performa & endurance (suite lama, paralel/terpisah)

```bash
python3 <APP>/device/benchmark/run_all.py --tests T1            # latency
python3 <APP>/device/benchmark/run_all.py --tests T4 --t4-duration 10800   # endurance 3 jam
```

### Blok D & E — Konteks (sesi `context1`)

```bash
python3 <APP>/device/benchmark/field/recorder.py --session context1 --hz 2 &
python3 <APP>/device/benchmark/field/driver.py  context1 setmode context
# Untuk tiap scene: operator susun objek + catat isi sebenarnya, lalu:
python3 <APP>/device/benchmark/field/mark.py    context1 phase "scene meja-1: botol kiri, laptop depan"
# Trigger describe 5x (scene SAMA berturut → uji cache hit-rate naik):
python3 <APP>/device/benchmark/field/driver.py  context1 describe --n 5 --gap 10
# Ulang utk 8–10 scene berbeda (verbosity sedang & detail). transcript auto ke marks.jsonl.
# stop: touch /tmp/isora_field_stop
```

Lalu isi rubrik Blok D (lihat §7).

### Blok G — Reliability (sesi `reli1`)

```bash
python3 <APP>/device/benchmark/field/recorder.py --session reli1 --hz 3 &
# mode-switch stress 50x:
python3 <APP>/device/benchmark/field/driver.py reli1 modeswitch --n 50 --gap 1.5
# barge-in: pastikan ada orang di depan (explorer spam), lalu:
python3 .../driver.py reli1 setmode explorer
python3 .../driver.py reli1 describe1 --label barge
# network-drop: matikan WiFi device, lalu:
python3 .../mark.py   reli1 net_down
python3 .../driver.py reli1 describe1 --label netdown
python3 .../mark.py   reli1 net_up      # nyalakan WiFi lagi
# recovery lensa:
python3 .../mark.py reli1 cover ; # (tutup) ; python3 .../mark.py reli1 uncover
# stop: touch /tmp/isora_field_stop
```

---

## 7. Penilaian & laporan

Setelah tiap sesi:

```bash
python3 <APP>/device/benchmark/field/analyze.py --session explorerA
python3 <APP>/device/benchmark/field/analyze.py --session context1
# dst — menghasilkan ringkasan PASS/FAIL + /root/logs/field/<sesi>/report.json
```

**Rubrik Blok D:** salin `templates/context_rubric.csv` ke
`/root/logs/field/context1/context_rubric.csv`, isi per scene (objek benar,
berapa disebut, halusinasi, posisi benar, kegunaan 1–5). `analyze.py`
membacanya otomatis. Transcript deskripsi ada di `marks.jsonl` (aksi `describe`).

---

## 8. (Opsional) Upgrade akurasi latency — in-process tracer

Untuk time-to-announce presisi tanpa beban polling, kita bisa tambahkan trace
ringan langsung di proses app (tanpa subprocess, timestamp monotonic), di-gate
flag `field_trace`. Hook ±2 baris di 3 titik (`explorer_mode` set deteksi,
`audio_manager._queue_nav` announce, `orchestrator.switch_mode`). **Diterapkan
& diverifikasi live di device** saat hari-H (belum dipasang sekarang supaya core
tidak diubah tanpa uji on-device). Fallback tanpa tracer: recorder `--hz 8`.

---

## 9. Pembagian kerja ringkas

| Claude (SSH/software)                                                            | Operator (hardware)                                                                                            |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Verifikasi config/API key, jalankan recorder/driver, hitung metrik, interpretasi | Tandai lantai, susun scene, gerakkan objek/helper, ketik `mark.py`, isi rubrik, tutup/buka lensa, matikan WiFi |
