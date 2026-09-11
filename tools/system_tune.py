"""System tuning for a headless I-Sora unit — reversible.

The problem this solves
───────────────────────
On a MaixCAM running as a wearable, the stock image still boots the MaixCAM
*launcher* — the on-screen app menu. It renders continuously to a display
nobody is looking at, and on this single-core RISC-V it costs roughly twice as
much CPU as the entire I-Sora pipeline:

    /maixapp/apps/launcher/launcher daemon    ~57% CPU, permanently
    python3 /root/isora/main.py            ~26% CPU

That is why the device runs hot "even when it isn't doing anything" — the heat
was never mainly YOLO. And the SoC exposes no cpufreq/DVFS at all (there is no
/sys/devices/system/cpu/cpu0/cpufreq directory), so clock scaling is not
available as a lever: the only way to run cooler is to stop doing pointless
work.

What --apply does
─────────────────
  1. Backs up /etc/init.d/S06maixapp once, to /root/.isora/S06maixapp.orig
  2. Makes the launcher start conditional on a flag file
  3. Creates the flag file, so the launcher no longer starts at boot
  4. Stops the launcher that is running right now

Reverting
─────────
  --revert   removes the flag file. The patched init script starts the
             launcher again on the next boot; nothing else changes.
  --restore  puts the original, unpatched S06maixapp back.

The flag-file design is deliberate: undoing this must never require re-editing
a boot script over SSH on a device that may not boot if the edit goes wrong.

Usage
─────
  python tools/system_tune.py --host isora-bfe2.local --status
  python tools/system_tune.py --host isora-bfe2.local --apply
  python tools/system_tune.py --host isora-bfe2.local --revert
"""

import argparse
import os
import sys
import time

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko tidak terinstall. Jalankan: pip install paramiko")
    sys.exit(1)

DEFAULT_HOST = os.environ.get("ISORA_MAIX_HOST", "maixcam.local")
DEFAULT_USER = os.environ.get("ISORA_MAIX_USER", "root")
DEFAULT_PASS = os.environ.get("ISORA_MAIX_PASS", "root")

INIT_SCRIPT = "/etc/init.d/S06maixapp"
BACKUP_DIR = "/root/.isora"
BACKUP = BACKUP_DIR + "/S06maixapp.orig"
FLAG = "/root/.isora_launcher_disabled"

MARKER = "I-Sora: launcher start made conditional"

# The stock line that starts the launcher, and the guarded replacement.
LAUNCH_LINE = "(/maixapp/apps/launcher/launcher_daemon &)"
GUARDED = "\n".join([
    "# >>> " + MARKER + " (tools/system_tune.py) >>>",
    "# The launcher renders an on-screen menu this headless unit never shows,",
    "# at ~57% of the single core. Delete the flag file to bring it back.",
    "if [ ! -f " + FLAG + " ]; then",
    "    (/maixapp/apps/launcher/launcher_daemon &)",
    "fi",
    "# <<< I-Sora <<<",
])


def connect(host, user, password, retries=5):
    """Connect with backoff — a loaded MaixCAM drops the SSH banner often."""
    last = None
    for i in range(retries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(host, username=user, password=password, timeout=15,
                      banner_timeout=30, auth_timeout=25,
                      look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            last = e
            time.sleep(2.0 * (i + 1))
    print("ERROR: gagal connect ke %s: %s" % (host, last))
    sys.exit(1)


def run(c, cmd, timeout=30):
    _in, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return o.strip(), e.strip()


def cpu_temp(c):
    o, _ = run(c, "cat /sys/class/thermal/thermal_zone0/temp")
    try:
        return int(o) / 1000.0
    except (TypeError, ValueError):
        return None


def _is_patched(c):
    # grep -q, not -c: `grep -c ... || echo 0` prints BOTH grep's "0" and the
    # fallback "0" on a miss, which reads as a non-zero count.
    out, _ = run(c, "grep -q '%s' %s 2>/dev/null && echo yes || echo no"
                    % (MARKER, INIT_SCRIPT))
    return out.strip() == "yes"


def _launcher_procs(c):
    # busybox pgrep does not take -f the way procps does (it silently matches
    # nothing), so count from ps instead. The [a] trick keeps grep's own
    # process out of the count.
    out, _ = run(c, "ps w | grep -c '[a]pps/launcher/launcher'")
    return out.strip().splitlines()[0] if out.strip() else "0"


def status(c):
    running = _launcher_procs(c)
    flag, _ = run(c, "test -f %s && echo yes || echo no" % FLAG)
    backup, _ = run(c, "test -f %s && echo yes || echo no" % BACKUP)
    top, _ = run(c, "top -bn1 | head -12")
    temp = cpu_temp(c)
    load, _ = run(c, "cat /proc/loadavg")

    print("-" * 62)
    print("  launcher berjalan : %s"
          % ("tidak" if running in ("0", "") else "ya (%s proses)" % running))
    print("  init script patch : %s" % ("ya" if _is_patched(c) else "belum"))
    print("  flag nonaktif     : %s" % flag)
    print("  backup asli       : %s" % backup)
    print("  suhu SoC          : %s" % ("%.1f C" % temp if temp else "?"))
    print("  loadavg           : %s" % load)
    print("-" * 62)
    print(top)


def _patch_init_script(c):
    """Rewrite the launcher start line into a flag-guarded block.

    Done with sed on the device (no python-in-python quoting), matching the
    line by its distinctive path so surrounding formatting is irrelevant. If
    the line is not found, nothing is written at all — an unexpected init
    script means a different image, and a half-edited boot script on a device
    the user cannot see is not a risk worth taking for a CPU saving.
    """
    found, _ = run(c, "grep -qF '%s' %s && echo yes || echo no"
                      % (LAUNCH_LINE, INIT_SCRIPT))
    if found.strip() != "yes":
        return False, "baris start launcher tidak ditemukan"

    # Build the replacement as a here-doc-free sed script: write the guarded
    # block to a temp file, then splice it in with sed's 'r' (read file) after
    # deleting the original line.
    lines = GUARDED.split("\n")
    run(c, "rm -f /tmp/.isora_guard")
    for ln in lines:
        run(c, "printf '%%s\\n' %s >> /tmp/.isora_guard" % _sh_quote(ln))

    # Delete the stock line, then insert the guard block at that position.
    cmd = (
        "line=$(grep -nF '%s' %s | head -1 | cut -d: -f1) && "
        "sed -i \"${line}r /tmp/.isora_guard\" %s && "
        "sed -i \"${line}d\" %s && "
        "rm -f /tmp/.isora_guard && echo patched"
    ) % (LAUNCH_LINE, INIT_SCRIPT, INIT_SCRIPT, INIT_SCRIPT)
    out, err = run(c, cmd)
    if "patched" not in out:
        return False, (out or err or "sed gagal")
    return True, ""


def _sh_quote(s):
    """POSIX single-quote a string for safe interpolation into a shell command."""
    return "'" + s.replace("'", "'\\''") + "'"


def apply(c):
    temp_before = cpu_temp(c)
    load_before, _ = run(c, "cat /proc/loadavg")

    # 1. Back up once. Never overwrite: a second --apply must not capture an
    #    already-patched script as "the original".
    run(c, "mkdir -p %s" % BACKUP_DIR)
    exists, _ = run(c, "test -f %s && echo yes || echo no" % BACKUP)
    if exists != "yes":
        _, err = run(c, "cp %s %s" % (INIT_SCRIPT, BACKUP))
        if err:
            print("ERROR: gagal backup %s: %s" % (INIT_SCRIPT, err))
            sys.exit(1)
        print("  backup  -> %s" % BACKUP)
    else:
        print("  backup  -> sudah ada, dipertahankan (%s)" % BACKUP)

    # 2. Guard the launcher start (idempotent).
    if _is_patched(c):
        print("  patch   -> sudah terpasang")
    else:
        ok, why = _patch_init_script(c)
        if not ok:
            print("ERROR: gagal patch %s: %s" % (INIT_SCRIPT, why))
            print("       Init script berbeda dari image standar — "
                  "TIDAK ada yang diubah.")
            sys.exit(1)
        print("  patch   -> %s" % INIT_SCRIPT)

    # 3. The flag is the actual switch.
    run(c, "touch %s" % FLAG)
    print("  flag    -> %s (hapus file ini untuk mengembalikan launcher)" % FLAG)

    # 4. Stop what is running now. Daemon first, so it cannot respawn the UI.
    run(c, "killall launcher_daemon 2>/dev/null; sleep 1; "
           "killall launcher 2>/dev/null")
    time.sleep(3)
    still = _launcher_procs(c)
    print("  stop    -> %s"
          % ("launcher berhenti" if still in ("0", "")
             else "MASIH ADA %s proses" % still))

    print("\n  Menunggu suhu turun (90 detik)...")
    time.sleep(90)
    temp_after = cpu_temp(c)
    load_after, _ = run(c, "cat /proc/loadavg")
    if temp_before and temp_after:
        print("  suhu    : %.1f C -> %.1f C (%+.1f C)"
              % (temp_before, temp_after, temp_after - temp_before))
    print("  loadavg : %s  ->  %s" % (load_before, load_after))


def revert(c):
    run(c, "rm -f %s" % FLAG)
    print("  flag dihapus -> launcher aktif lagi pada boot berikutnya.")
    print("  Untuk menjalankannya sekarang tanpa reboot:")
    print("    (/maixapp/apps/launcher/launcher_daemon &)")


def restore(c):
    exists, _ = run(c, "test -f %s && echo yes || echo no" % BACKUP)
    if exists != "yes":
        print("ERROR: tidak ada backup di %s — tidak ada yang direstore." % BACKUP)
        sys.exit(1)
    run(c, "cp %s %s && chmod +x %s" % (BACKUP, INIT_SCRIPT, INIT_SCRIPT))
    run(c, "rm -f %s" % FLAG)
    print("  %s dikembalikan ke versi asli, flag dihapus." % INIT_SCRIPT)


def main():
    ap = argparse.ArgumentParser(
        description="I-Sora system tuning (launcher MaixCAM) — reversible")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--password", default=DEFAULT_PASS)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="Lihat kondisi sekarang")
    g.add_argument("--apply", action="store_true",
                   help="Matikan launcher (persist + sekarang)")
    g.add_argument("--revert", action="store_true",
                   help="Aktifkan lagi (hapus flag)")
    g.add_argument("--restore", action="store_true",
                   help="Kembalikan init script asli")
    args = ap.parse_args()

    print("I-Sora system tune -> %s" % args.host)
    c = connect(args.host, args.user, args.password)
    try:
        if args.status:
            status(c)
        elif args.apply:
            apply(c)
        elif args.revert:
            revert(c)
        elif args.restore:
            restore(c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
