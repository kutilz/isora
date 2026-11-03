# Model uang (mode scan bayar)

Model deteksi uang kertas untuk `modes/pay_mode.py`: **YOLO26n** (Ultralytics),
7 kelas (1K, 2K, 5K, 10K, 20K, 50K, 100K), dilatih dengan uang yang **dipegang
di tangan, sudut pandang orang pertama** — skenario kacamata. Sumber:
`Hasil Training.zip` → `1/runs/detect/train2/weights/best.pt` (di Downloads
pc-render). Model YOLOv5s di folder `2/` dicoba juga dan **tidak dipakai**: 0/40
pada test split dataset ini, bahkan di 640 float.

Hasil di device (MaixCAM, MaixPy 4.5.1 userspace `/root/t451`):

| | test split (40 gbr, uang dipegang) | waktu `detect()` 320×224 |
|---|---|---|
| float ONNX (PC) | 36/40 | – |
| INT8 penuh | 33/40 | 10,8 ms |
| **INT8 + head BF16** (dipakai) | **34/40** (conf ≥ 0,4), 32/40 (≥ 0,5) | **10,3 ms** |

Catatan jujur: test split diambil dari video yang sama dengan data latih, jadi
angkanya kemungkinan optimis. 7 foto uang tergeletak di meja dari atas (luar
distribusi latih) gagal semua, bahkan di float. Uji nyata dengan uang asli di
depan kamera tetap perlu.

## Kenapa bisa jalan di MaixPy 4.5.1 yang belum kenal YOLO26

YOLO26 punya `reg_max=1` (tanpa DFL). Kepala kotaknya langsung mengeluarkan
jarak ltrb per anchor dalam satuan grid — persis yang dikeluarkan conv DFL
YOLOv8. `export_y26.py` memotong graf di dua tensor itu (`boxes` `[1,1,4,N]`,
`scores` setelah sigmoid `[1,7,N]`), lalu `.mud` menyebut `model_type = yolov8`,
sehingga decoder `nn.YOLOv8` bawaan MaixPy yang membuat anchor, mengalikan
stride, dan NMS. Dipakai head one-to-many (yang memang dilatih untuk NMS).

## Membuat ulang

Semua kerja berat di **pc-render, di WSL** (`~/maixcam_uang/`):

1. Ekspor ONNX (env conda `rknn`: Python 3.10 + torch 2.4 — exporter lama
   dengan nama node yang stabil; CPU saja, torch 2.4 belum kenal RTX 50xx):

   ```bash
   CUDA_VISIBLE_DEVICES= YOLO_OFFLINE=1 YOLO_AUTOINSTALL=false \
     ~/miniconda3/envs/rknn/bin/python export_y26.py best.pt y26n_uang_320x224_one2many.onnx one2many
   ```

2. TPU-MLIR 1.12 (build 2024-11; cvimodel versi 1.4.0 yang dibaca runtime
   4.5.1) ada di venv `~/maixcam_uang/venv-tpu`. Dua tambalan di venv itu:
   - `tpu_mlir/lib/third_party/{libc.so.6,libm.so.6,libpthread.so.0}` dipindah ke
     `_bundled_glibc_2_35/` — glibc bawaan Ubuntu 22.04 itu bentrok dengan
     Ubuntu 24.04 (`GLIBC_2.36 not found`).
   - `site-packages/zz_borrow_rknn_torch.pth` meminjam torch dari env `rknn`
     (dibutuhkan `run_calibration`) tanpa mengunduh lagi.

   ```bash
   source ~/maixcam_uang/venv-tpu/bin/activate
   bash convert.sh y26n_uang_320x224_one2many.onnx calib/ test.jpg work/
   ```

   `calib/` = 126 gambar val (18 per kelas).

3. Kirim ke device: `uang_yolo26n_320x224_mix.cvimodel` + `uang_yolo26n.mud`
   → `/root/models/` (salinan di `models/` repo, di-gitignore). Uji di device
   dengan app dimatikan (NPU eksklusif) dan environment `t451`:

   ```sh
   /etc/init.d/S26isoraapp stop; sleep 8
   PYTHONPATH=/root/t451 LD_LIBRARY_PATH=/root/t451/lib \
     python devtest_money.py /root/models/uang_yolo26n.mud <dir_test_a> <dir_test_b>
   /etc/init.d/S26isoraapp start
   ```

Tanpa `/root/t451`, MaixPy ≥ 4.10.3 di MaixCAM Lite SIGSEGV saat memuat model
apa pun (lihat `tools/run.py`).
