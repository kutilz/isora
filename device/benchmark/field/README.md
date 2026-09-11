# Field benchmark toolkit (in-situ, human-in-the-loop)

Tooling untuk benchmark **akurasi + reliability** mode `explorer` & `context` di
lab nyata. Rencana lengkap + protokol: lihat `benchmark_plan.md` di root repo.

Murni stdlib (urllib/json) — tanpa `maix`. Jalankan di device via SSH (satu jam
dengan recorder/mark/driver) atau dari PC (untuk `analyze.py`).

| File | Fungsi |
|---|---|
| `recorder.py` | Poll `GET /status` → `events.jsonl` |
| `mark.py` | Tandai ground-truth → `marks.jsonl` |
| `driver.py` | Otomasi `describe` / `modeswitch` / `config` |
| `analyze.py` | Hitung metrik A/B/D/E/G → `report.json` + ringkasan |

Hasil per sesi: `/root/logs/field/<sesi>/`.

```bash
# rekam
python3 recorder.py --session explorerA --hz 8 &
# tandai (saat kejadian)
python3 mark.py explorerA enter person kanan 3 far
python3 mark.py explorerA exit person
# konteks
python3 driver.py context1 describe --n 5 --gap 10
# nilai
python3 analyze.py --session explorerA
```

Catatan: `get_status()` shell-out wifi tiap panggil → pakai `--hz 2..3` untuk
sesi panjang; `--hz 8` hanya untuk window latency pendek (lihat §8 plan untuk
in-process tracer presisi).
