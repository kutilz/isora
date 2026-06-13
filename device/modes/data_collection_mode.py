"""
AuralAI Data Collection Mode
==============================
Mode untuk mengumpulkan dataset foto di lapangan.
Berjalan sepenuhnya mandiri — tidak butuh companion PC.

MaixCAM menjadi hotspot/WiFi client; browser HP membuka halaman monitoring
di http://<maixcam-ip>:8080/collect

Fitur:
  - Auto-capture tiap N detik (configurable dari web UI)
  - Simpan ke /root/captures/YYYYMMDD/collect_HHMMSS_NNN.jpg
  - JPEG quality configurable (default: Q85)
  - Metadata CSV: timestamp, filename, file_size_kb, frame_num
  - Web-accessible: status, gallery (10 terbaru), download foto
  - Storage guard: berhenti otomatis jika free space < 50MB
  - Thread-safe untuk diakses bersamaan dari web server
"""

import os
import time
import threading
import csv
import gc
from datetime import datetime

try:
    from maix import camera, image
    MAIX_OK = True
except ImportError:
    MAIX_OK = False

CAPTURES_ROOT   = "/root/captures"
STORAGE_MIN_MB  = 50          # stop jika free space < 50MB
DEFAULT_INTERVAL= 1.0         # detik antar capture
DEFAULT_QUALITY = 85          # JPEG quality (1-100)
MAX_GALLERY     = 20          # foto terbaru yang disimpan di memory


def _disk_stats(path=CAPTURES_ROOT) -> tuple:
    """Return (free_mb, total_mb) for the filesystem that holds `path`."""
    try:
        os.makedirs(path, exist_ok=True)
        s = os.statvfs(path)
        free_mb  = (s.f_bavail * s.f_frsize) // 1_048_576
        total_mb = (s.f_blocks * s.f_frsize) // 1_048_576
        return free_mb, total_mb
    except Exception:
        return 999, 1024


class DataCollector:
    """
    Mengelola sesi data collection.
    Diinstansiasi satu kali di main.py dan dibagi ke web server.
    """

    def __init__(self, logger=None):
        self._lock      = threading.Lock()
        self._thread    = None
        self._running   = False
        self._log       = logger

        # Config (bisa diubah via web UI)
        self.interval_s = DEFAULT_INTERVAL
        self.quality    = DEFAULT_QUALITY

        # Session stats
        self.session_start  = None
        self.capture_count  = 0
        self.session_dir    = None
        self.csv_path       = None
        self._csv_file      = None
        self._csv_writer    = None

        # Gallery: list of dicts {filename, filepath, timestamp, size_kb}
        self._gallery       = []

        # Camera instance (dibuka saat start, ditutup saat stop)
        self._cam           = None

    # ── Properties (thread-safe reads) ─────────────────────────────
    @property
    def is_running(self): return self._running

    @property
    def stats(self) -> dict:
        with self._lock:
            elapsed = (time.time() - self.session_start) if self.session_start else 0
            free_mb, total_mb = _disk_stats(self.session_dir or CAPTURES_ROOT)
            return {
                "running":        self._running,
                "capture_count":  self.capture_count,
                "elapsed_s":      round(elapsed, 1),
                "interval_s":     self.interval_s,
                "quality":        self.quality,
                "session_dir":    self.session_dir,
                "free_space_mb":  free_mb,
                "total_space_mb": total_mb,
                "gallery_count":  len(self._gallery),
            }

    @property
    def gallery(self) -> list:
        with self._lock:
            return list(self._gallery[-MAX_GALLERY:])

    # ── Public API ──────────────────────────────────────────────────
    def start(self, interval_s=None, quality=None):
        """Mulai sesi data collection. Returns (ok, message)."""
        with self._lock:
            if self._running:
                return False, "Sudah berjalan"

            if interval_s is not None:
                self.interval_s = max(0.5, float(interval_s))
            if quality is not None:
                self.quality = max(50, min(100, int(quality)))

            # Buat direktori sesi
            date_str = datetime.now().strftime("%Y%m%d")
            self.session_dir = os.path.join(CAPTURES_ROOT, date_str)
            os.makedirs(self.session_dir, exist_ok=True)

            # Init CSV log
            ts_str = datetime.now().strftime("%H%M%S")
            self.csv_path = os.path.join(self.session_dir, f"collect_{ts_str}_meta.csv")
            self._csv_file   = open(self.csv_path, "a", buffering=1, newline="")
            self._csv_writer = csv.writer(self._csv_file)
            if os.path.getsize(self.csv_path) == 0:
                self._csv_writer.writerow([
                    "timestamp", "filename", "frame_num",
                    "file_size_kb", "free_space_mb",
                ])

            self.session_start = time.time()
            self.capture_count = 0
            self._gallery.clear()
            self._running = True

        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="DataCollector",
        )
        self._thread.start()

        msg = f"Sesi dimulai — interval={self.interval_s}s, Q={self.quality}"
        self._info(msg)
        return True, msg

    def stop(self):
        """Hentikan sesi. Returns (ok, message)."""
        with self._lock:
            if not self._running:
                return False, "Tidak sedang berjalan"
            self._running = False

        if self._thread:
            self._thread.join(timeout=5.0)

        with self._lock:
            if self._csv_file:
                self._csv_file.flush()
                self._csv_file.close()
                self._csv_file   = None
                self._csv_writer = None
            if self._cam:
                try: del self._cam
                except: pass
                self._cam = None
            gc.collect()

        elapsed = time.time() - (self.session_start or time.time())
        msg = f"Sesi selesai — {self.capture_count} foto dalam {elapsed:.0f}s"
        self._info(msg)
        return True, msg

    def set_interval(self, interval_s: float):
        """Ubah interval antar capture saat sesi berjalan."""
        self.interval_s = max(0.5, float(interval_s))

    def serve_photo(self, filename: str) -> bytes | None:
        """Kembalikan bytes JPEG untuk filename tertentu."""
        safe = os.path.basename(filename)
        if not safe.endswith(".jpg"): return None

        # Cari di semua sesi dir hari ini
        date_str = datetime.now().strftime("%Y%m%d")
        path = os.path.join(CAPTURES_ROOT, date_str, safe)
        if not os.path.exists(path):
            # Cari di semua sub-direktori
            for root, _, files in os.walk(CAPTURES_ROOT):
                if safe in files:
                    path = os.path.join(root, safe)
                    break
            else:
                return None

        try:
            with open(path, "rb") as f:
                return f.read()
        except:
            return None

    def delete_photo(self, filename: str) -> tuple:
        """
        Delete a captured photo from disk and remove its CSV row.
        Returns (ok, message).
        """
        safe = os.path.basename(filename)
        if not safe.endswith(".jpg"):
            return False, "Invalid filename"

        # Locate the file across all session dirs
        path = None
        for root_dir, _, files in os.walk(CAPTURES_ROOT):
            if safe in files:
                path = os.path.join(root_dir, safe)
                break
        if path is None:
            return False, f"File tidak ditemukan: {safe}"

        try:
            os.remove(path)
        except Exception as e:
            return False, str(e)

        # Remove from in-memory gallery
        with self._lock:
            self._gallery = [p for p in self._gallery if p["filename"] != safe]
            csv_path = self.csv_path

        # Rewrite CSV excluding the deleted row
        if csv_path and os.path.exists(csv_path):
            try:
                with open(csv_path, "r", newline="") as f:
                    rows = list(csv.reader(f))
                kept = [rows[0]] + [r for r in rows[1:] if len(r) < 2 or r[1] != safe]
                with open(csv_path, "w", newline="") as f:
                    csv.writer(f).writerows(kept)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            except Exception as e:
                return True, f"Foto dihapus, CSV error: {e}"

        return True, f"Foto {safe} dihapus"

    def create_session_zip(self) -> tuple:
        """
        Zip today's session directory into /tmp.
        Returns (zip_path_str, error_msg); zip_path is None on failure.
        """
        import shutil
        date_str = datetime.now().strftime("%Y%m%d")
        src_dir  = os.path.join(CAPTURES_ROOT, date_str)
        if not os.path.isdir(src_dir):
            return None, "Tidak ada sesi hari ini"
        zip_base = f"/tmp/aural_dataset_{date_str}"
        try:
            zip_path = shutil.make_archive(zip_base, "zip", src_dir)
            return zip_path, None
        except Exception as e:
            return None, str(e)

    # ── Capture Loop ────────────────────────────────────────────────
    def _capture_loop(self):
        # Init camera di dalam thread
        if MAIX_OK:
            try:
                self._cam = camera.Camera(640, 480)
                self._info("Camera OK (640×480)")
            except Exception as ex:
                self._warn(f"Camera error: {ex} → synthetic mode")
                self._cam = None
        else:
            self._cam = None

        while self._running:
            t_loop = time.time()

            # Storage guard
            free_mb = _free_space_mb()
            if free_mb < STORAGE_MIN_MB:
                self._warn(f"Storage hampir penuh: {free_mb}MB free < {STORAGE_MIN_MB}MB — stop!")
                with self._lock:
                    self._running = False
                break

            # Ambil & simpan foto
            ok, meta = self._do_capture(free_mb)

            if ok and meta:
                with self._lock:
                    self._gallery.append(meta)
                    # Trim gallery supaya tidak besar
                    if len(self._gallery) > MAX_GALLERY * 2:
                        self._gallery = self._gallery[-MAX_GALLERY:]

                    if self._csv_writer:
                        self._csv_writer.writerow([
                            meta["timestamp"],
                            meta["filename"],
                            meta["frame_num"],
                            f"{meta['size_kb']:.1f}",
                            free_mb,
                        ])
                        self._csv_file.flush()
                        try:
                            os.fsync(self._csv_file.fileno())
                        except Exception:
                            pass

            # Tunggu sampai interval berikutnya (minus waktu yang sudah terpakai)
            elapsed_loop = time.time() - t_loop
            sleep_s = max(0, self.interval_s - elapsed_loop)
            time.sleep(sleep_s)

        self._info("Capture loop selesai")

    def _do_capture(self, free_mb) -> tuple:
        """Ambil satu foto. Returns (success, meta_dict)."""
        ts_str = datetime.now().strftime("%H%M%S_%f")[:13]  # HHMMSS_mmm
        self.capture_count += 1
        count = self.capture_count
        filename = f"collect_{ts_str}_{count:05d}.jpg"
        filepath = os.path.join(self.session_dir, filename)

        try:
            if self._cam and MAIX_OK:
                img     = self._cam.read()
                jpg_img = img.to_format(image.Format.FMT_JPEG)
                jpg_bytes = bytes(jpg_img.to_bytes())
            else:
                # Synthetic: buat gambar dengan timestamp
                jpg_bytes = self._make_synthetic_jpeg(count)

            with open(filepath, "wb") as f:
                f.write(jpg_bytes)

            size_kb = len(jpg_bytes) / 1024

            meta = {
                "filename":  filename,
                "filepath":  filepath,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "frame_num": count,
                "size_kb":   size_kb,
            }
            return True, meta

        except Exception as ex:
            self._warn(f"Capture error #{count}: {ex}")
            self.capture_count -= 1  # rollback counter
            return False, None

    def _make_synthetic_jpeg(self, count) -> bytes:
        """Buat JPEG synthetic ketika kamera tidak tersedia."""
        if not MAIX_OK:
            return b""
        w, h = 320, 240
        img = image.Image(w, h, image.Format.FMT_RGB888)
        # Background warna berubah setiap 10 frame (mudah dibedakan)
        r = (count * 13) % 200 + 30
        g = (count * 37) % 200 + 30
        b_val = (count * 71) % 200 + 30
        img.draw_rect(0, 0, w, h, image.Color.from_rgb(r, g, b_val), thickness=-1)
        img.draw_string(10, 10, f"SYNTHETIC #{count}", image.Color.from_rgb(255, 255, 255))
        img.draw_string(10, 30,
            datetime.now().strftime("%H:%M:%S"),
            image.Color.from_rgb(200, 200, 0))
        jpg = img.to_format(image.Format.FMT_JPEG)
        return bytes(jpg.to_bytes())

    # ── Logging helpers ─────────────────────────────────────────────
    def _info(self, msg):
        if self._log: self._log.info(f"[DataCollector] {msg}")
        else: print(f"[DataCollector] {msg}")

    def _warn(self, msg):
        if self._log: self._log.warn(f"[DataCollector] {msg}")
        else: print(f"[WARN DataCollector] {msg}")
