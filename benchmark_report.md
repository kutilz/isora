# AuralAI  Long-Term Stress Test Report

> 

## 1. Ringkasan Eksekutif

| Item           | Nilai                                              |
| -------------- | -------------------------------------------------- |
| Perangkat      | Sipeed MaixCAM (varian reguler)                    |
| Pipeline diuji | Camera -> YOLO11n -> Annotate -> JPEG encode       |
| Jadwal         | 3-6 jam/hari (peak 8 jam) × 5 hari = ~25 jam total |
| Verdict akhir  | ✅ STABIL                                           |

---

## 2. Tujuan & Metode

**Tujuan:** memverifikasi stabilitas termal dan ketahanan FPS pipeline AuralAI
saat dijalankan terus-menerus minimal 5 jam/hari selama 5 hari berturut-turut, untuk
memastikan tidak ada thermal throttling, kebocoran memori, atau crash pada
penggunaan jangka panjang.

**Metode:**

- Script: `stress-test/long_term_stress.py` (resume otomatis via
  `long_term_state.json`).
- Beban per frame: `camera.read()` → `detector.detect()` → `draw_rect()` →
  `to_format(JPEG)`.
- Checkpoint & logging tiap **15 menit** ke `logs/day_NN_YYYY-MM-DD.csv`.

---

## 3. Lingkungan Uji

| Parameter       | Nilai                                |
| --------------- | ------------------------------------ |
| Model           | YOLO11n (`/root/models/yolo11n.mud`) |
| Input model     | 320×224, FMT_RGB888                  |
| OS / Kernel     | Linux [ 5.10.4-tag- ]                |
| Arsitektur      | riscv64                              |
| Python / MaixPy | 3.11                                 |
| RAM total       | 256 MB                               |
| NPU freq        | 1000 MHz                             |
| Pendinginan     | Heatsink                             |
| Suhu ruangan    | 27 °C                                |

---

## 4. Hasil Harian

### Day 1 - 8 Mei 2026

| Metrik                    | Nilai         |
| ------------------------- | ------------- |
| Durasi                    | 3 jam         |
| Total frame               | belum dicatat |
| Avg FPS                   | 51.3          |
| FPS drift (awal -> akhir) | 51.6 -> 51.0  |
| Throttle events           | 0             |
| RAM free (min)            | 159 MB        |
| Peak temp                 | 85.1          |
| Crash / error             | -             |

### Day 2 - 9 Mei 2026

| Metrik                    | Nilai         |
| ------------------------- | ------------- |
| Durasi                    | 5 jam         |
| Total frame               | belum dicatat |
| Avg FPS                   | 51.1          |
| FPS drift (awal -> akhir) | 51.6 -> 50.9  |
| Throttle events           | -             |
| RAM free (min)            | 155 MB        |
| Crash / error             | -             |

### Day 3 - 10 Mei 2026

| Metrik                    | Nilai        |
| ------------------------- | ------------ |
| Durasi                    | 8 jam        |
| Total frame               | 1,476,289    |
| Avg FPS                   | 51           |
| FPS drift (awal -> akhir) | 51.6 -> 50.8 |
| Throttle events           | -            |
| RAM free (min)            | 155 MB       |
| Crash / error             | -            |

### Day 4 - 11 Mei 2026

| Metrik                    | Nilai        |
| ------------------------- | ------------ |
| Durasi                    | 5 jam        |
| Total frame               | 921,293      |
| Avg FPS                   | 51.2         |
| FPS drift (awal -> akhir) | 51.6 -> 50.8 |
| Throttle events           | -            |
| RAM free (min)            | 159 MB       |
| Crash / error             | -            |

### Day 5 - 12 Mei 2026

| Metrik                    | Nilai        |
| ------------------------- | ------------ |
| Durasi                    | 5 jam        |
| Total frame               | 921,323      |
| Avg FPS                   | 51.2         |
| FPS drift (awal -> akhir) | 51.5 -> 50.8 |
| Throttle events           | -            |
| RAM free (min)            | 159 MB       |
| Crash / error             | -            |

---

## 5. Rekap Peak Temperature

Peak temperature per hari:

- Day 1: 85.1
- Day 2: 85
- Day 3: 85.1
- Day 4: 85.1
- Day 5: 85.1

---

## 6. Lampiran

- Log CSV harian: `stress-test/logs/day_01..05_*.csv` (repository github)
  State file: `stress-test/long_term_state.json`
- Script: `stress-test/long_term_stress.py`
