"""
MaixCAM Battery/Power Check (Live)
=================================
Tujuan:
  - Cek apakah MaixCAM expose data baterai/tegangan lewat Linux power_supply:
      /sys/class/power_supply/<name>/{capacity,voltage_now,current_now,power_now,status,type}
  - Print ringkas secara periodik + optional simpan CSV.

Cara pakai:
  python stress-test/maixcam_battery_check.py

Env opsional:
  INTERVAL_S   (default 2)
  LOG_CSV      (default 1)  : 1 untuk simpan CSV, 0 untuk tidak
  LOG_PATH     (default auto)
"""

import os
import time
from datetime import datetime


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


def _read_int(path: str):
    s = _read_text(path)
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def discover_power_supplies(base: str = "/sys/class/power_supply"):
    if not os.path.exists(base):
        return []
    out = []
    try:
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if os.path.isdir(d):
                out.append(d)
    except Exception:
        return []
    return out


def read_power_supply(ps_dir: str):
    # Field standar power_supply (tidak semuanya ada)
    name = os.path.basename(ps_dir)
    typ = _read_text(os.path.join(ps_dir, "type")) or None
    status = _read_text(os.path.join(ps_dir, "status")) or None
    cap = _read_int(os.path.join(ps_dir, "capacity"))  # %

    # Biasanya satuan micro
    v_now_uv = _read_int(os.path.join(ps_dir, "voltage_now"))
    c_now_ua = _read_int(os.path.join(ps_dir, "current_now"))
    p_now_uw = _read_int(os.path.join(ps_dir, "power_now"))

    voltage_v = (v_now_uv / 1_000_000.0) if v_now_uv is not None else None
    current_a = (c_now_ua / 1_000_000.0) if c_now_ua is not None else None
    power_w = (p_now_uw / 1_000_000.0) if p_now_uw is not None else None

    return {
        "name": name,
        "type": typ,
        "status": status,
        "capacity_pct": cap,
        "voltage_v": voltage_v,
        "current_a": current_a,
        "power_w": power_w,
        "path": ps_dir,
    }


def fmt(x, nd=3, suffix=""):
    if x is None:
        return "NA"
    if isinstance(x, float):
        return f"{x:.{nd}f}{suffix}"
    return f"{x}{suffix}"


def main():
    interval_s = _env_float("INTERVAL_S", 2.0)
    log_csv = _env_int("LOG_CSV", 1) == 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.getenv("LOG_PATH") or os.path.abspath(f"battery_check_{stamp}.csv")

    ps_dirs = discover_power_supplies()

    print()
    print(DIVIDER)
    print("  MaixCAM Battery/Power Check (Live)")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Interval: {interval_s}s")
    print(DIVIDER)

    if not ps_dirs:
        print()
        print("[WARN] Tidak ada /sys/class/power_supply. Berarti:")
        print("  - board/OS tidak expose data baterai, atau")
        print("  - kamu memang supply lewat jalur yang tidak dimonitor.")
        print("Saran: pantau pakai multimeter (untuk LiPo 1S, stop sekitar 3.3V under load).")
        print()
        return

    print()
    print("Power supplies terdeteksi:")
    for d in ps_dirs:
        info = read_power_supply(d)
        print(f"  - {info['name']} (type={info['type']} status={info['status']}) @ {info['path']}")

    f = None
    if log_csv:
        f = open(log_path, "w", buffering=1)
        f.write("ts_iso,ps_name,ps_type,ps_status,capacity_pct,voltage_v,current_a,power_w\n")
        f.flush()
        print()
        print(f"[INFO] Logging CSV: {log_path}")

    print()
    print("Tekan Ctrl+C untuk berhenti.")
    print()

    try:
        while True:
            ts_iso = datetime.now().isoformat(timespec="seconds")
            infos = [read_power_supply(d) for d in ps_dirs]
            infos.sort(key=lambda p: 0 if (p.get("type") or "").lower() == "battery" else 1)

            for p in infos:
                line = (
                    f"[{ts_iso}] {p['name']:<10} type={p['type'] or 'NA':<8} status={p['status'] or 'NA':<12} "
                    f"cap={fmt(p['capacity_pct'], nd=0, suffix='%'):>4}  "
                    f"V={fmt(p['voltage_v'], nd=3, suffix='V'):>8}  "
                    f"I={fmt(p['current_a'], nd=3, suffix='A'):>8}  "
                    f"P={fmt(p['power_w'], nd=3, suffix='W'):>8}"
                )
                print(line)

                if f:
                    f.write(
                        f"{ts_iso},{p['name']},{p['type'] or ''},{p['status'] or ''},"
                        f"{p['capacity_pct'] if p['capacity_pct'] is not None else ''},"
                        f"{p['voltage_v'] if p['voltage_v'] is not None else ''},"
                        f"{p['current_a'] if p['current_a'] is not None else ''},"
                        f"{p['power_w'] if p['power_w'] is not None else ''}\n"
                    )
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass

            print()
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if f:
            try:
                f.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()

