"""
MaixCAM Battery Endurance Stress Test
====================================
Tujuan:
  - Menjalankan beban stabil (kamera + operasi gambar + CPU burn) sambil
    mencatat telemetry secara KONSTAN agar kamu bisa pantau penurunan baterai.
  - Skrip ini sengaja dibuat tahan mati listrik: log di-flush setiap baris.

Catatan penting soal keamanan LiPo:
  - Idealnya JANGAN dipaksa sampai "kosong banget". Untuk 1S LiPo, batas aman
    umumnya ~3.3V (di bawah beban) untuk berhenti, dan jangan sampai <3.0V.
  - Jika perangkat punya proteksi undervoltage, ia akan mati sendiri lebih aman.
  - Kalau tidak ada API pembacaan baterai, pantau pakai multimeter.

Cara pakai (di MaixCAM):
  python stress-test/maixcam_battery_stress.py

Opsional env:
  LOG_INTERVAL_S   (default 5)   : interval log
  LOAD_PROFILE     (default "balanced") : "light" | "balanced" | "heavy"
  STOP_VOLTAGE_V   (default 3.30): jika bisa baca voltage, stop di bawah ini
  STOP_CAPACITY_PCT(default 5)   : jika bisa baca capacity, stop di bawah ini
  MANUAL_V_PROMPT_S(default 0)   : jika >0, minta input tegangan manual tiap N detik
                                  (berguna kalau power_supply tidak ada / supply via VBUS)
  MANUAL_V_FILE    (default "")  : alternatif kalau input() tidak interaktif.
                                  Set path file (mis. /tmp/maix_manual_v.txt).
                                  Isi file cukup angka voltage (contoh: 3.87 atau 3.87V).
"""

import os
import time
import math
from datetime import datetime

try:
    from maix import camera, image, display, app
    MAIX_OK = True
except Exception:
    MAIX_OK = False


DIVIDER = "=" * 60


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


def _read_text(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return ""


def discover_power_supplies(base: str = "/sys/class/power_supply"):
    out = []
    if not os.path.exists(base):
        return out
    try:
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if os.path.isdir(d):
                out.append(d)
    except Exception:
        return []
    return out


def read_power_supply(ps_dir: str):
    """
    Coba baca field standar Linux power_supply.
    Return dict yang aman walau sebagian field tidak ada.
    """
    def read_num(filename: str):
        s = _read_text(os.path.join(ps_dir, filename))
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None

    typ = _read_text(os.path.join(ps_dir, "type")) or None
    status = _read_text(os.path.join(ps_dir, "status")) or None
    cap = read_num("capacity")  # %

    # Satuan power_supply lazimnya micro-volt / micro-ampere
    v_now = read_num("voltage_now")
    c_now = read_num("current_now")
    p_now = read_num("power_now")

    def uv_to_v(uv):
        return (uv / 1_000_000.0) if (uv is not None) else None

    def ua_to_a(ua):
        return (ua / 1_000_000.0) if (ua is not None) else None

    def uw_to_w(uw):
        return (uw / 1_000_000.0) if (uw is not None) else None

    return {
        "name": os.path.basename(ps_dir),
        "type": typ,
        "status": status,
        "capacity_pct": cap,
        "voltage_v": uv_to_v(v_now),
        "current_a": ua_to_a(c_now),
        "power_w": uw_to_w(p_now),
        "path": ps_dir,
    }


def discover_thermal_zones(base: str = "/sys/class/thermal"):
    zones = []
    if not os.path.exists(base):
        return zones
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"):
            continue
        zone_path = os.path.join(base, entry)
        temp_path = os.path.join(zone_path, "temp")
        type_path = os.path.join(zone_path, "type")
        if not os.path.exists(temp_path):
            continue
        ztype = _read_text(type_path) or "unknown"
        zones.append((entry, ztype, temp_path))
    return zones


def read_max_temp_c(zones):
    m = None
    for _, _, tpath in zones:
        s = _read_text(tpath)
        if not s:
            continue
        try:
            raw = int(s)
            tc = raw / 1000.0 if raw > 1000 else float(raw)
            m = tc if (m is None or tc > m) else m
        except Exception:
            continue
    return m


def cpu_burn(iterations: int):
    # Beban matematis ringan-tapi-konsisten
    acc = 0.0
    for i in range(1, iterations + 1):
        acc += math.sin(i * 0.01) * math.cos(i * 0.01) / (1.0 + (i % 7))
    return acc


def img_burn(img, heavy: bool):
    # Operasi gambar untuk menambah beban mem/cpu (opsional)
    img.draw_rect(0, 0, img.width(), img.height(), image.Color.from_rgb(255, 0, 0), thickness=2)
    img.draw_string(4, 4, "BATTERY STRESS", image.Color.from_rgb(255, 255, 0), scale=1)
    if heavy:
        for k in range(8):
            img.draw_line(0, k * 20, img.width(), img.height() - k * 20, image.Color.from_rgb(0, 160, 255), thickness=1)
        for r in (20, 40, 60, 80):
            img.draw_circle(img.width() // 2, img.height() // 2, r, image.Color.from_rgb(0, 255, 0))
        _ = img.resize(img.width() // 2, img.height() // 2)
        _ = img.to_format(image.Format.FMT_JPEG)


def _try_parse_manual_voltage(s: str):
    """
    Terima input seperti:
      - "3.87"
      - "3,87"
      - "3.87V"
      - "" (skip)
    Return float voltage atau None kalau tidak valid/skip.
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    s = s.lower().replace("v", "").replace(",", ".").strip()
    try:
        return float(s)
    except Exception:
        return None


def main():
    log_interval_s = _env_float("LOG_INTERVAL_S", 5.0)
    profile = (os.getenv("LOAD_PROFILE") or "balanced").strip().lower()
    stop_v = _env_float("STOP_VOLTAGE_V", 3.30)
    stop_cap = _env_int("STOP_CAPACITY_PCT", 5)
    manual_prompt_s = _env_float("MANUAL_V_PROMPT_S", 0.0)
    manual_v_file = (os.getenv("MANUAL_V_FILE") or "").strip()

    if profile not in ("light", "balanced", "heavy"):
        profile = "balanced"

    zones = discover_thermal_zones()
    ps_dirs = discover_power_supplies()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.abspath(f"battery_stress_log_{stamp}.csv")

    print()
    print(DIVIDER)
    print("  MaixCAM Battery Endurance Stress Test")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Profile: {profile} | log_interval={log_interval_s}s")
    print(f"  Log file: {log_path}")
    print(DIVIDER)
    print()

    if not zones:
        print("[WARN] thermal zones tidak ditemukan (skip suhu).")
    if not ps_dirs:
        print("[WARN] power_supply tidak ditemukan, voltage/capacity kemungkinan tidak bisa dibaca.")
        print("       Saran: pantau pakai multimeter dan stop sekitar 3.3V (under load).")
        if manual_prompt_s > 0:
            print(f"       Manual prompt aktif: tiap {manual_prompt_s:.0f}s kamu akan diminta input tegangan (V).")
        if manual_v_file:
            print(f"       Manual file aktif: {manual_v_file}  (update isi file kapan saja).")
    else:
        print("Power supplies terdeteksi:")
        for d in ps_dirs:
            info = read_power_supply(d)
            print(f"  - {info['name']} (type={info['type']} status={info['status']}) @ {info['path']}")
        print()

    # Setup Maix modules (opsional)
    cam = None
    disp = None
    if MAIX_OK:
        try:
            # Resolusi kecil supaya stabil (bisa dinaikkan kalau mau)
            cam = camera.Camera(320, 240, image.Format.FMT_RGB888)
        except Exception:
            cam = None
        try:
            disp = display.Display()
        except Exception:
            disp = None

    heavy_img = (profile == "heavy")
    cpu_iters = 1200 if profile == "light" else (2600 if profile == "balanced" else 5200)

    # Header CSV
    with open(log_path, "w", buffering=1) as f:
        f.write(
            "ts_iso,uptime_s,profile,frames,fps,cpu_burn_iters,temp_max_c,"
            "ps_name,ps_type,ps_status,capacity_pct,voltage_v,current_a,power_w,"
            "manual_voltage_v\n"
        )
        f.flush()

        t0 = time.time()
        last_log = 0.0
        frames = 0
        last_fps_calc = t0
        last_frames = 0
        last_manual_prompt = 0.0
        manual_voltage_v = None
        last_manual_file_mtime = None

        while True:
            if MAIX_OK and app.need_exit():
                print("\nExit requested.")
                break

            # ---- Load: camera + img ops
            img = None
            if cam is not None:
                try:
                    img = cam.read()
                except Exception:
                    img = None
            if img is None and MAIX_OK:
                try:
                    img = image.Image(320, 240, image.Format.FMT_RGB888)
                except Exception:
                    img = None

            if img is not None and MAIX_OK:
                try:
                    img_burn(img, heavy=heavy_img)
                except Exception:
                    pass
                if disp is not None and profile != "light":
                    # light: skip display untuk hemat daya; balanced/heavy: tampilkan
                    try:
                        disp.show(img)
                    except Exception:
                        pass
                frames += 1

            # ---- Load: CPU burn
            _ = cpu_burn(cpu_iters)

            now = time.time()

            # ---- Manual voltage via file (kalau diset)
            if manual_v_file:
                try:
                    st = os.stat(manual_v_file)
                    mtime = st.st_mtime
                    if last_manual_file_mtime is None or mtime != last_manual_file_mtime:
                        last_manual_file_mtime = mtime
                        mv = _try_parse_manual_voltage(_read_text(manual_v_file))
                        if mv is not None:
                            manual_voltage_v = mv
                            print(f"[OK] manual_voltage_v={manual_voltage_v:.3f}V (from file)")
                except Exception:
                    # file belum ada / tidak bisa dibaca → ignore
                    pass

            # ---- Manual voltage prompt (jika diminta)
            if manual_prompt_s > 0 and (now - last_manual_prompt) >= manual_prompt_s:
                last_manual_prompt = now
                try:
                    s = input("Input tegangan LiPo (V), kosongkan untuk skip: ").strip()
                    mv = _try_parse_manual_voltage(s)
                    if mv is not None:
                        manual_voltage_v = mv
                        print(f"[OK] manual_voltage_v={manual_voltage_v:.3f}V")
                    else:
                        print("[SKIP] tegangan manual tidak diubah")
                except Exception:
                    # Jika stdin tidak tersedia, jangan crash
                    pass

            if (now - last_log) >= log_interval_s:
                uptime_s = now - t0
                dt = now - last_fps_calc
                fps = None
                if dt > 0.1:
                    fps = (frames - last_frames) / dt
                last_fps_calc = now
                last_frames = frames

                temp_max = read_max_temp_c(zones) if zones else None

                # Read power supplies (ambil yang paling "battery-like" dulu)
                ps_infos = [read_power_supply(d) for d in ps_dirs] if ps_dirs else [None]
                ps_infos = [p for p in ps_infos if p is not None] or [None]
                ps_infos.sort(key=lambda p: 0 if (p and (p.get("type") or "").lower() == "battery") else 1)
                ps = ps_infos[0]

                ts_iso = datetime.now().isoformat(timespec="seconds")
                row = {
                    "ts_iso": ts_iso,
                    "uptime_s": round(uptime_s, 1),
                    "profile": profile,
                    "frames": frames,
                    "fps": (round(fps, 2) if fps is not None else ""),
                    "cpu_burn_iters": cpu_iters,
                    "temp_max_c": (round(temp_max, 1) if temp_max is not None else ""),
                    "ps_name": (ps.get("name") if ps else ""),
                    "ps_type": (ps.get("type") if ps else ""),
                    "ps_status": (ps.get("status") if ps else ""),
                    "capacity_pct": (ps.get("capacity_pct") if ps else ""),
                    "voltage_v": (round(ps.get("voltage_v"), 3) if (ps and ps.get("voltage_v") is not None) else ""),
                    "current_a": (round(ps.get("current_a"), 3) if (ps and ps.get("current_a") is not None) else ""),
                    "power_w": (round(ps.get("power_w"), 3) if (ps and ps.get("power_w") is not None) else ""),
                    "manual_voltage_v": (round(manual_voltage_v, 3) if manual_voltage_v is not None else ""),
                }

                line = (
                    f"{row['ts_iso']},{row['uptime_s']},{row['profile']},{row['frames']},{row['fps']},"
                    f"{row['cpu_burn_iters']},{row['temp_max_c']},{row['ps_name']},{row['ps_type']},{row['ps_status']},"
                    f"{row['capacity_pct']},{row['voltage_v']},{row['current_a']},{row['power_w']},{row['manual_voltage_v']}\n"
                )
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass

                # Print live status (ringkas)
                vtxt = f"{row['voltage_v']}V" if row["voltage_v"] != "" else "V=NA"
                mvtxt = f"manualV={row['manual_voltage_v']}V" if row["manual_voltage_v"] != "" else ""
                ctxt = f"{row['capacity_pct']}%" if row["capacity_pct"] != "" else "%=NA"
                ttxt = f"{row['temp_max_c']}C" if row["temp_max_c"] != "" else "T=NA"
                fpst = f"{row['fps']}fps" if row["fps"] != "" else "fps=NA"
                extra = f" {mvtxt}" if mvtxt else ""
                print(f"[{ts_iso}] up={row['uptime_s']}s {fpst} temp={ttxt} batt={ctxt} {vtxt} frames={frames}{extra}")

                # Stop conditions (kalau data tersedia)
                cap = ps.get("capacity_pct") if ps else None
                vv = ps.get("voltage_v") if ps else None
                # kalau ps voltage tidak ada, pakai manual voltage kalau tersedia
                vv_eff = vv if vv is not None else manual_voltage_v
                if (cap is not None and cap <= stop_cap) or (vv_eff is not None and vv_eff <= stop_v):
                    print()
                    print(DIVIDER)
                    print("  STOP condition tercapai (aman).")
                    print(f"  capacity<= {stop_cap}% atau voltage<= {stop_v}V")
                    print(f"  Terakhir: cap={cap}% voltage={vv_eff}V")
                    print("  Saran: segera charge kembali, jangan dipaksa lebih rendah.")
                    print(DIVIDER)
                    print()
                    break

                last_log = now

    # Cleanup
    try:
        if cam is not None:
            del cam
        if disp is not None:
            del disp
    except Exception:
        pass


if __name__ == "__main__":
    main()

