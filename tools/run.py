"""
I-Sora Runner — Deploy + jalankan mode di MaixCAM tanpa SSH manual.
Output di-stream langsung ke terminal PC. Ctrl+C menghentikan proses remote.

Requires: pip install paramiko

Usage:
    python tools/run.py                        # Deploy + run main.py
    python tools/run.py --mode stress          # Deploy + overnight stress test
    python tools/run.py --mode qris            # QRIS Benchmark
    python tools/run.py --mode longterm        # Long-term 5-hari
    python tools/run.py --mode benchmark       # System benchmark v2
    python tools/run.py --no-deploy            # Skip upload, langsung run
    python tools/run.py --background           # Run background (aman dari disconnect)
    python tools/run.py --stop                 # Stop proses yang sedang jalan
    python tools/run.py --logs                 # Tail log background
    python tools/run.py --status               # Lihat status JSON (stress/overnight)
    python tools/run.py --host 192.168.1.100   # IP custom
    python tools/run.py --extra "--dry-run"    # Argumen tambahan ke script target

  Autostart (boot otomatis):
    python tools/run.py --autostart            # Set I-Sora sebagai app autostart saat boot
    python tools/run.py --autostart-off        # Hapus autostart (boot ke launcher biasa)
    python tools/run.py --autostart-status     # Lihat app autostart saat ini
"""

import os
import sys
import time
import signal
import argparse
import threading

# Load .env dari project root kalau ada
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ─── Konfigurasi default ──────────────────────────────────────────────────────

DEFAULT_HOST = os.environ.get("ISORA_MAIX_HOST", "maixcam.local")
DEFAULT_PORT = int(os.environ.get("ISORA_MAIX_PORT", "22"))
DEFAULT_USER = os.environ.get("ISORA_MAIX_USER", "root")
DEFAULT_PASS = os.environ.get("ISORA_MAIX_PASS", "root")

REMOTE_BASE   = "/root/isora"
REMOTE_DEVICE = "/root/isora"
REMOTE_AUDIO  = "/root/audio"

PROJECT_ROOT  = os.path.join(os.path.dirname(__file__), "..")
DEVICE_DIR    = os.path.join(PROJECT_ROOT, "device")
AUDIO_DIR     = os.path.join(PROJECT_ROOT, "audio")

EXCLUDE_PATTERNS = {"__pycache__", ".pyc", ".pyo", ".DS_Store", "node_modules", ".git"}

# ─── Definisi mode ────────────────────────────────────────────────────────────

MODES = {
    "main": {
        "label":       "I-Sora SDK — Main",
        "cwd":         REMOTE_DEVICE,
        "script":      "main.py",
        "pid_file":    "/tmp/isora_main.pid",
        "log_file":    "/tmp/isora_main.log",
        "status_file": None,
        "url":         "http://{host}:8080",
        "url_note":    "Dashboard  → http://{host}:8080\n  Data Collect → http://{host}:8080/collect",
    },
    "stress": {
        "label":       "Overnight Stress Test (8 jam)",
        "cwd":         f"{REMOTE_DEVICE}/stress-test",
        "script":      "overnight_stress.py",
        "pid_file":    "/tmp/overnight_stress.pid",
        "log_file":    "/tmp/overnight_stress.log",
        "status_file": "/tmp/overnight_status.json",
        "url":         None,
        "url_note":    None,
    },
    "qris": {
        "label":       "QRIS Benchmark",
        "cwd":         f"{REMOTE_DEVICE}/stress-test",
        "script":      "qris_benchmark.py",
        "pid_file":    None,
        "log_file":    None,
        "status_file": None,
        "url":         None,
        "url_note":    None,
    },
    "longterm": {
        "label":       "Long-term Stress (5 Hari)",
        "cwd":         f"{REMOTE_DEVICE}/stress-test",
        "script":      "long_term_stress.py",
        "pid_file":    "/tmp/long_term.pid",
        "log_file":    "/tmp/long_term.log",
        "status_file": None,
        "url":         None,
        "url_note":    None,
    },
    "benchmark": {
        "label":       "System Benchmark v2",
        "cwd":         f"{REMOTE_DEVICE}/stress-test",
        "script":      "maixcam_benchmark_v2.py",
        "pid_file":    None,
        "log_file":    None,
        "status_file": None,
        "url":         None,
        "url_note":    None,
    },
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _color(code, text): return f"\033[{code}m{text}\033[0m"
def cyan(t):   return _color("96", t)
def green(t):  return _color("92", t)
def yellow(t): return _color("93", t)
def red(t):    return _color("91", t)
def bold(t):   return _color("1",  t)
def dim(t):    return _color("2",  t)

def log(msg):  print(f"  {msg}")
def ok(msg):   print(f"  {green('✓')} {msg}")
def warn(msg): print(f"  {yellow('!')} {msg}")
def err(msg):  print(f"  {red('✗')} {msg}")
def sep():     print(dim("  " + "─" * 58))


def connect(host, port, user, password):
    """Buka koneksi SSH ke MaixCAM. Returns SSHClient."""
    try:
        import paramiko
    except ImportError:
        err("paramiko tidak terinstall. Jalankan: pip install paramiko")
        sys.exit(1)

    print(f"\n  {cyan('⟶')} Menghubungkan ke {bold(user + '@' + host)} port {port}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=user, password=password, timeout=10)
        ok("Terhubung ke MaixCAM")
        return client
    except Exception as e:
        err(f"Gagal connect: {e}")
        print()
        print("  Pastikan:")
        print("    • MaixCAM menyala dan terhubung ke WiFi yang sama")
        print(f"    • IP benar (coba --host <IP>) — misal: python tools/run.py --host 192.168.1.XXX")
        print("    • Port 22 tidak diblokir")
        sys.exit(1)


def _should_exclude(path):
    for pat in EXCLUDE_PATTERNS:
        if pat in path or path.endswith(".pyc") or path.endswith(".pyo"):
            return True
    return False


def deploy(client, audio=False):
    """Upload device/ (dan opsional audio/) ke MaixCAM."""
    sftp = client.open_sftp()
    total = 0

    def upload_dir(local_dir, remote_dir):
        nonlocal total
        for root, dirs, files in os.walk(local_dir):
            dirs[:] = [d for d in dirs if not _should_exclude(d)]
            rel = os.path.relpath(root, local_dir)
            remote_root = (remote_dir + "/" + rel).replace("\\", "/").replace("/.", "")
            try:
                sftp.mkdir(remote_root)
            except IOError:
                pass
            for fname in files:
                if _should_exclude(fname):
                    continue
                lp = os.path.join(root, fname)
                rp = (remote_root + "/" + fname).replace("\\", "/")
                sftp.put(lp, rp)
                total += 1
                sys.stdout.write(f"\r  {cyan('↑')} {total} file ter-upload...    ")
                sys.stdout.flush()

    print(f"\n  {cyan('⟶')} Upload device/ → {REMOTE_DEVICE}")
    upload_dir(DEVICE_DIR, REMOTE_DEVICE)
    print()
    # A dev build only gives way to a release NEWER than the one it was built
    # on — otherwise the auto-updater would overwrite work in progress.
    from release import dev_version
    with sftp.open(REMOTE_DEVICE + "/VERSION", "w") as f:
        f.write(dev_version() + "\n")

    if audio:
        wav_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(".wav")]
        if wav_files:
            print(f"  {cyan('⟶')} Upload audio/ ({len(wav_files)} file) → {REMOTE_AUDIO}")
            upload_dir(AUDIO_DIR, REMOTE_AUDIO)
            print()

    # Pastikan direktori penting ada
    client.exec_command(
        "mkdir -p /root/logs /root/models /root/audio /root/captures "
        f"{REMOTE_DEVICE}/stress-test"
    )

    sftp.close()
    ok(f"Deploy selesai — {total} file")


def run_foreground(client, mode_cfg, extra_args, host):
    """Jalankan script di foreground, stream output ke terminal PC."""
    cwd    = mode_cfg["cwd"]
    script = mode_cfg["script"]
    cmd    = f"cd {cwd} && python {script} {extra_args}"

    sep()
    print(f"  {bold('▶')} {mode_cfg['label']}")
    print(dim(f"    $ {cmd}"))
    if mode_cfg.get("url_note"):
        print(f"\n  {yellow('🌐')} {mode_cfg['url_note'].format(host=host)}")
    print(dim("    Ctrl+C untuk berhenti\n"))
    sep()

    transport = client.get_transport()
    channel   = transport.open_session()
    channel.get_pty(term="xterm", width=120, height=40)
    channel.exec_command(cmd)

    # Kirim Ctrl+C ke remote saat user tekan Ctrl+C di PC
    def _sigint(sig, frame):
        print(f"\n  {yellow('!')} Mengirim SIGINT ke MaixCAM...")
        try:
            channel.send("\x03")
        except Exception:
            pass

    signal.signal(signal.SIGINT, _sigint)

    # Stream output
    try:
        while True:
            if channel.recv_ready():
                data = channel.recv(4096)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            if channel.exit_status_ready() and not channel.recv_ready():
                break
            time.sleep(0.02)
    except Exception:
        pass

    exit_code = channel.recv_exit_status()
    sep()
    if exit_code == 0:
        ok("Proses selesai (exit 0)")
    else:
        warn(f"Proses selesai (exit {exit_code})")


def run_background(client, mode_cfg, extra_args, host):
    """Jalankan script di background dengan nohup (aman dari disconnect)."""
    cwd      = mode_cfg["cwd"]
    script   = mode_cfg["script"]
    pid_file = mode_cfg.get("pid_file") or f"/tmp/isora_{mode_cfg['script'].replace('.py','')}.pid"
    log_file = mode_cfg.get("log_file") or f"/tmp/isora_{mode_cfg['script'].replace('.py','')}.log"

    # A manual relaunch is NOT a fresh boot, so the boot-chime flag from the last
    # boot is stale (tmpfs /tmp survives an app restart, only a reboot clears it).
    # Clear it so main.py's _boot_cue_fast replays "I-Sora menyala" on restart
    # instead of skipping on the stale flag. Only main.py uses the flag; harmless
    # for other modes.
    clear_flag = "rm -f /tmp/.boot_chime_played; " if script == "main.py" else ""
    cmd = (
        f"cd {cwd} && {clear_flag}"
        f"nohup python {script} {extra_args} > {log_file} 2>&1 & "
        f"echo $! > {pid_file} && echo $!"
    )
    if script == "main.py" and not extra_args:
        # A unit with the supervised init script: (re)start through it, so the
        # app stays supervised and no second copy runs beside a respawned one.
        cmd = (
            f"if [ -f {SUPERVISOR_PATH} ] && [ -x {APP_INIT_PATH} ]; then "
            f"{clear_flag}setsid {APP_INIT_PATH} restart </dev/null >/dev/null 2>&1; "
            f"sleep 2; cat {pid_file}; else {cmd}; fi"
        )

    sep()
    print(f"  {bold('▶')} {mode_cfg['label']} {yellow('[background]')}")
    print(dim(f"    Script : {cwd}/{script}"))
    print(dim(f"    Log    : {log_file}"))
    print(dim(f"    PID    : {pid_file}"))
    sep()

    _, stdout, _ = client.exec_command(cmd)
    pid = stdout.read().decode().strip()

    if pid.isdigit():
        ok(f"Berjalan di background — PID {bold(pid)}")
        print()
        print(f"  Lihat log  : python tools/run.py --logs --mode {mode_cfg.get('_key','main')}")
        print(f"  Stop       : python tools/run.py --stop --mode {mode_cfg.get('_key','main')}")
        if mode_cfg.get("url_note"):
            print(f"\n  {yellow('🌐')} {mode_cfg['url_note'].format(host=host)}")
    else:
        err("Gagal mendapatkan PID — mungkin script error saat launch")
        print(dim("  Cek log: ") + dim(f"python tools/run.py --logs --mode {mode_cfg.get('_key','main')}"))


def stop_process(client, mode_cfg):
    """Kill proses background via PID file."""
    pid_file = mode_cfg.get("pid_file")
    if not pid_file:
        warn("Mode ini tidak punya PID file — tidak bisa di-stop otomatis")
        return

    cmd = (
        f"if [ -f {pid_file} ]; then "
        f"  pid=$(cat {pid_file}); "
        f"  kill $pid 2>/dev/null && echo killed:$pid || echo notfound:$pid; "
        f"  rm -f {pid_file}; "
        f"else echo nopid; fi"
    )
    if mode_cfg.get("script") == "main.py":
        # Stop the supervisor too, or it would start the app again.
        cmd = (f"if [ -x {APP_INIT_PATH} ]; then pid=$(cat {pid_file} 2>/dev/null); "
               f"{APP_INIT_PATH} stop; echo killed:${{pid:-?}}; else {cmd}; fi")
    _, stdout, _ = client.exec_command(cmd)
    result = stdout.read().decode().strip()

    if result.startswith("killed:"):
        ok(f"Proses PID {result.split(':')[1]} dihentikan")
    elif result.startswith("notfound:"):
        warn(f"PID {result.split(':')[1]} tidak ditemukan (mungkin sudah berhenti)")
    else:
        warn("PID file tidak ada — proses mungkin tidak sedang jalan")


def tail_logs(client, mode_cfg, lines=50):
    """Tampilkan log dari background session."""
    log_file = mode_cfg.get("log_file")
    if not log_file:
        warn("Mode ini tidak punya log file")
        return

    cmd = f"tail -n {lines} -f {log_file} 2>/dev/null || echo '(log file belum ada)'"
    transport = client.get_transport()
    channel   = transport.open_session()
    channel.get_pty(term="xterm", width=120, height=40)
    channel.exec_command(cmd)

    sep()
    print(f"  {bold('📋')} Log — {log_file}  (Ctrl+C untuk keluar)")
    sep()

    def _sigint(sig, frame):
        channel.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    try:
        while True:
            if channel.recv_ready():
                data = channel.recv(4096)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            if channel.exit_status_ready() and not channel.recv_ready():
                break
            time.sleep(0.05)
    except Exception:
        pass


def show_status(client, mode_cfg):
    """Tampilkan status JSON jika ada (overnight stress, dll)."""
    status_file = mode_cfg.get("status_file")
    pid_file    = mode_cfg.get("pid_file")

    # Cek apakah proses jalan
    if pid_file:
        _, out, _ = client.exec_command(
            f"[ -f {pid_file} ] && pid=$(cat {pid_file}) && "
            f"kill -0 $pid 2>/dev/null && echo running:$pid || echo stopped"
        )
        proc_status = out.read().decode().strip()
        if proc_status.startswith("running:"):
            print(f"\n  Status proses : {green('● RUNNING')} (PID {proc_status.split(':')[1]})")
        else:
            print(f"\n  Status proses : {red('● STOPPED')}")

    if status_file:
        _, out, _ = client.exec_command(f"cat {status_file} 2>/dev/null || echo '{{}}'")
        raw = out.read().decode().strip()
        try:
            import json
            data = json.loads(raw)
            sep()
            print(f"  {bold('Status JSON')} — {status_file}")
            sep()
            for k, v in data.items():
                print(f"  {cyan(k):<30} {v}")
        except Exception:
            print(dim(f"\n  (status file belum ada atau tidak valid)"))
    print()


# ─── Autostart helpers ────────────────────────────────────────────────────────

# The MaixApp launcher (/maixapp/auto_start.txt) is a GUI app that needs the
# LCD; on a screen-less I-Sora unit it dies at boot, so that mechanism never
# fires. Autostart from /etc/rc.local instead — /etc/init.d/S99local runs it at
# the end of boot (after network + avahi). Reliable for a headless camera app.
RC_LOCAL = "/etc/rc.local"
RC_BEGIN = "# >>> I-Sora autostart >>>"
RC_END   = "# <<< I-Sora autostart <<<"

# Marker era-AuralAI dari blok yang sama. Perangkat yang di-flash sebelum
# rebrand masih memuatnya, dan blok itu meluncurkan /root/aural-ai/main.py
# dari rc.local (S99local). Membuangnya BUKAN kosmetik: S26isoraapp menjaga
# dirinya lewat /tmp/isora_main.pid sedangkan blok lama menulis
# /tmp/aural_main.pid — PID guard-nya tidak cocok, jadi kalau blok ini
# dibiarkan, dua instance app jalan berbarengan dan berebut kamera + audio.
# Pasangan masalah yang sama di sisi init.d: LEGACY_INIT_PATHS.
RC_BEGIN_LEGACY = "# >>> AuralAI autostart >>>"
RC_END_LEGACY   = "# <<< AuralAI autostart <<<"
RC_BLOCK = (
    RC_BEGIN + "\n"
    "# Nothing launches from here any more, and that is the point: rc.local is\n"
    "# S99local, dead-last in rcS — behind WiFi association, avahi, ssdpd and\n"
    "# dnsmasq, none of which the app needs in order to start.\n"
    "# The boot chime runs from /etc/init.d/S00aisorachime (first script, ~1.9s)\n"
    "# and the app from /etc/init.d/S26isoraapp (right after the WiFi module,\n"
    "# before association). Measured with tools/boot_timeline.py on isora-bfe2:\n"
    "# app spawn 14.82s -> 8.95s, time-to-ready 22.00s -> 19.19s.\n"
    "# The block is still written so --autostart-status has something to find\n"
    "# and --autostart-off has something to strip.\n"
    "# To revert: use RC_BLOCK_LEGACY and delete S26isoraapp.\n"
    + RC_END + "\n"
)

# Original autostart block (pre-boot-optimization). To revert:
# 1. Replace RC_BLOCK with RC_BLOCK_LEGACY above
# 2. Re-run: python tools/run.py --autostart
RC_BLOCK_LEGACY = (
    RC_BEGIN + "\n"
    "sleep 5\n"
    # Same MaixPy 4.5.1 override as APP_INIT_SCRIPT — the revert path has
    # to carry it too, or reverting turns a working unit into a crash loop.
    "[ -d /root/t451 ] && export PYTHONPATH=/root/t451 \\\n"
    "  LD_LIBRARY_PATH=/root/t451/lib\n"
    "cd /root/isora\n"
    "nohup python3 -u /root/isora/main.py >> /tmp/isora_main.log 2>&1 &\n"
    "echo $! > /tmp/isora_main.pid\n"
    + RC_END + "\n"
)

# Early boot-chime init script. Placed at S00a — the VERY FIRST init.d script,
# even before S00kmod (which insmods the ~25 soph camera/NPU/VPU modules, the
# biggest early-boot cost). Audio needs none of that: the cv182xa DAC is
# kernel-probed at ~0.78s and its playback node /dev/snd/pcmC1D0p is created by
# devtmpfs right then, well before any init.d script runs. The chime uses the
# i2s DAC, which is independent of the i2c bus that S00pmu/the sensor use, so it
# does not contend with module loading. Measured: "I-Sora menyala" at ~2.0s vs
# ~16.4s when it lived in rc.local/S99local (dead-last, behind WiFi).
#
# Safety, by design — this must NEVER stall boot just to make a sound:
#   • aplay is launched in a detached background subshell, so the init script
#     returns immediately; boot proceeds even if audio is slow or silent.
#   • It plays + sets the dedup flag ONLY if the DAC playback node already
#     exists this early (/dev/snd/pcmC1D0p) AND the PCM is present. If audio is
#     not ready yet, it does nothing and sets no flag — main.py's _boot_cue_fast
#     then plays the cue later (the existing ~16s path). Self-adaptive fallback.
#   • Always exits 0. Verified on-device: modules + camera still come up clean.
CHIME_INIT_PATH = "/etc/init.d/S00aisorachime"
CHIME_INIT_SCRIPT = (
    "#!/bin/sh\n"
    "# >>> I-Sora early boot chime >>>\n"
    "# Auto-installed by tools/run.py --autostart. Runs first (before module\n"
    "# load + WiFi) so the power-on cue is heard ~2s after boot. Non-blocking +\n"
    "# self-adaptive: defers to main.py's _boot_cue_fast if audio isn't ready.\n"
    "PCM=/root/audio/isora_menyala.pcm\n"
    "case \"$1\" in\n"
    "  start)\n"
    "    if [ -s \"$PCM\" ] && [ -e /dev/snd/pcmC1D0p ]; then\n"
    "      ( aplay -q -D hw:1,0 -t raw -f S16_LE -r 48000 -c 1 \"$PCM\" 2>/dev/null ) &\n"
    # The flag doubles as a boot-timing marker: its CONTENT is the uptime the
    # cue fired at, which tools/boot_timeline.py scores. main.py only tests for
    # existence, so carrying a value costs it nothing.
    "      cut -d\" \" -f1 /proc/uptime > /tmp/.boot_chime_played 2>/dev/null\n"
    "    fi\n"
    "    ;;\n"
    "  stop|restart|reload) ;;\n"
    "esac\n"
    "exit 0\n"
)


# App autostart init script. Placed at S26 — immediately after S25wifimod loads
# the WiFi driver, and before S30wifi associates. It used to launch from
# rc.local (S99local), which runs dead-last: behind association, avahi, ssdpd
# and dnsmasq, none of which the app needs in order to start. The web server
# binds 0.0.0.0 so it serves the moment an interface appears, MdnsPublisher
# retries on its own, and the cloud client is offline-safe.
#
# Measured on isora-bfe2 with tools/boot_timeline.py: spawn 14.82s -> 8.95s.
# Time-to-ready gains less than that (22.00s -> 19.19s) because the app's
# imports now run *concurrently* with association/avahi/dnsmasq and lose some
# CPU to them — startup stretches 7.2s -> 10.2s. Still a net win, and it is
# why the remaining boot cost now sits in the app-start window, not before it.
#
# Safety: the PID guard makes a double-start impossible if rc.local still
# carries a legacy launch block, and the script always exits 0, so nothing here
# can stall boot.
APP_INIT_PATH = "/etc/init.d/S26isoraapp"

# Nama era-AuralAI dari skrip init yang sama. Perangkat yang sudah pernah
# di-deploy masih menyimpannya, dan nama lama + baru akan jalan berdampingan
# (chime dobel, dua proses app). Setiap pemasangan/penghapusan ikut membuang
# nama lama ini, jadi satu kali redeploy sudah membereskannya.
LEGACY_INIT_PATHS = ("/etc/init.d/S00aauralchime", "/etc/init.d/S26auralapp")
APP_INIT_SCRIPT = (
    "#!/bin/sh\n"
    "# >>> I-Sora app autostart >>>\n"
    "# Auto-installed by tools/run.py --autostart. Starts the app right after\n"
    "# the WiFi module loads, instead of dead-last from rc.local/S99local.\n"
    "# To revert: delete this file and restore the launch block in /etc/rc.local\n"
    "# (RC_BLOCK_LEGACY in tools/run.py).\n"
    "R=/root/isora-releases\n"
    "H=/etc/isora/release.py\n"
    "S=/etc/isora/supervise.sh\n"
    "SUP=/tmp/isora_supervisor.pid\n"
    "alive() { [ -f \"$1\" ] && kill -0 \"$(cat \"$1\")\" 2>/dev/null; }\n"
    "case \"$1\" in\n"
    "  start)\n"
    "    if alive $SUP || alive /tmp/isora_main.pid; then\n"
    "      exit 0\n"
    "    fi\n"
    # Supervised start (device/system/supervise.sh): a crashed app comes back
    # by itself, a wedged one is killed and started again. It runs the release
    # switch and the trial guard on every start itself.
    "    if [ -f \"$S\" ]; then\n"
    "      rm -f /tmp/isora_stop\n"
    "      sh \"$S\" </dev/null >/dev/null 2>&1 &\n"
    "      echo $! > $SUP\n"
    "      exit 0\n"
    "    fi\n"
    # Unsupervised start: a unit whose /etc predates the supervisor.
    # Release switch + rollback (device/system/release.py, fed by
    # core/updater.py). Only pays for a python3 start when there is something
    # to do: a staged update, a release on trial, or no startable app at all.
    "    if [ -f \"$H\" ] && { [ -e \"$R/pending\" ] || [ -e \"$R/trial\" ] "
    "|| [ ! -f /root/isora/main.py ]; }; then\n"
    "      python3 \"$H\" boot >/dev/null 2>&1\n"
    "    fi\n"
    # MaixPy userspace override. On the MaixCAM Lite every MaixPy from
    # 4.10.3 up SIGSEGVs inside NN model load (a /dev/mem register poke),
    # so a working 4.5.1 tree is kept in /root/t451 and must precede the
    # image's own on both paths. Before the rebrand this lived ONLY in the
    # hand-edited rc.local block, so a device migrated without it boots
    # into a crash loop. Guarded by -d, hence a no-op on units whose
    # shipped MaixPy works.
    "    if [ -d /root/t451 ]; then\n"
    "      export PYTHONPATH=/root/t451\n"
    "      export LD_LIBRARY_PATH=/root/t451/lib\n"
    "    fi\n"
    "    cd /root/isora\n"
    "    nohup python3 -u /root/isora/main.py >> /tmp/isora_main.log 2>&1 &\n"
    "    echo $! > /tmp/isora_main.pid\n"
    # A release on trial must confirm itself healthy (core/updater.py,
    # confirm_when_healthy) within this window, or it is rolled back here —
    # also when it crashed before it could arm the hardware watchdog.
    # The guard carries the trial as it reads NOW, so if the app is restarted
    # while it sleeps it leaves the next start (with its own guard) alone.
    "    if [ -f \"$H\" ] && [ -e \"$R/trial\" ]; then\n"
    "      T=$(tr '\\n' ' ' < \"$R/trial\")\n"
    "      ( sleep 240; python3 \"$H\" guard \"$T\" >/dev/null 2>&1; "
    "[ $? -eq 3 ] && \"$0\" restart ) </dev/null >/dev/null 2>&1 &\n"
    "    fi\n"
    "    ;;\n"
    "  stop)\n"
    # Supervisor first, so it cannot start the app again behind our back.
    "    touch /tmp/isora_stop\n"
    "    alive $SUP && kill \"$(cat $SUP)\" 2>/dev/null\n"
    "    rm -f $SUP\n"
    "    if [ -f /tmp/isora_main.pid ]; then\n"
    "      kill \"$(cat /tmp/isora_main.pid)\" 2>/dev/null\n"
    "    fi\n"
    "    ;;\n"
    "  restart)\n"
    "    \"$0\" stop\n"
    # SIGTERM makes the app release the camera/NPU first; starting before it
    # has gone would trip the PID guard above or fight over the sensor.
    "    i=0\n"
    "    while alive /tmp/isora_main.pid && [ $i -lt 20 ]; do\n"
    "      sleep 1; i=$((i+1))\n"
    "    done\n"
    "    sleep 3\n"
    "    \"$0\" start\n"
    "    ;;\n"
    "esac\n"
    "exit 0\n"
)

# Files from device/system/ that live OUTSIDE the app tree (see the package
# docstring there). Remote path → (source file, mode). The release helper is
# deliberately not part of what the auto-updater replaces: it is the way back
# from a bad update, so it only changes when this script is re-run.
SYSTEM_DIR = os.path.join(os.path.dirname(__file__), "..", "device", "system")
SUPERVISOR_PATH = "/etc/isora/supervise.sh"
SYSTEM_FILES = {
    "/etc/isora/release.py":    ("release.py",     0o644),
    SUPERVISOR_PATH:            ("supervise.sh",   0o755),
    "/etc/wifi_roam.sh":        ("wifi_roam.sh",   0o755),
    "/etc/wifi_prefer.sh":      ("wifi_prefer.sh", 0o755),
    "/etc/init.d/S31wifiroam":  ("S31wifiroam",    0o755),
    "/etc/init.d/S03isoraclock": ("S03isoraclock", 0o755),
}


def install_system_files(client):
    """Copy device/system/* to /etc (LF endings, atomic per file) and restart
    the WiFi helpers so the new roam hook is live without a reboot."""
    import base64
    for remote, (name, mode) in SYSTEM_FILES.items():
        with open(os.path.join(SYSTEM_DIR, name), "rb") as f:
            data = f.read().replace(b"\r\n", b"\n")
        b64 = base64.b64encode(data).decode()
        _ssh(client,
             "mkdir -p %s && python3 -c \"import base64,os,sys;"
             "p=sys.argv[1];t=p+'.new';open(t,'wb').write(base64.b64decode(sys.argv[2]));"
             "os.chmod(t,%d);os.replace(t,p)\" '%s' '%s' && sync"
             % (os.path.dirname(remote), mode, remote, b64))
        if _ssh(client, "test -f %s && echo ok" % remote):
            ok("%s dipasang" % remote)
        else:
            err("Gagal memasang %s" % remote)
    # setsid: the respawn loop must outlive this SSH session. `stop` also
    # kills the pre-repo version's wpa_cli daemon (killall wpa_cli).
    _ssh(client, "setsid /etc/init.d/S31wifiroam restart </dev/null >/dev/null 2>&1 &")
    ok("Hook WiFi dijalankan ulang")
    # Clock keeper: stop (saves the clock right now) then start the saver loop.
    _ssh(client, "/etc/init.d/S03isoraclock stop; "
                 "setsid /etc/init.d/S03isoraclock start </dev/null >/dev/null 2>&1 &")
    ok("Penyimpan jam dijalankan (/root/.isora_clock)")

# S05tp insmods two touchscreen drivers picked from /boot/board's panel= line.
# On a unit with no LCD both probe the i2c bus, retry and fail — the Goodix one
# five times — spending ~2.3s of boot on hardware that is not there, and every
# later init script inherits the delay. Renamed out of rcS's `S??*` glob rather
# than deleted, so a unit that gets a panel back is one mv away from stock.
TOUCH_INIT_PATH     = "/etc/init.d/S05tp"
TOUCH_INIT_DISABLED = "/etc/init.d/.S05tp.disabled"


def _ssh(client, cmd):
    """Jalankan command SSH, kembalikan stdout string."""
    _, out, _ = client.exec_command(cmd)
    return out.read().decode().strip()


def _write_rc_local(client, content):
    """Tulis /etc/rc.local via base64 (hindari masalah quoting / CRLF)."""
    import base64
    b64 = base64.b64encode(content.encode("utf-8")).decode()
    _ssh(
        client,
        "python3 -c \"import base64,sys;"
        f"open('{RC_LOCAL}','wb').write(base64.b64decode(sys.argv[1]))\" '{b64}' "
        f"&& chmod +x {RC_LOCAL} && sync",
    )


def _strip_block(text):
    """Buang blok autostart I-Sora (dan pendahulunya, AuralAI) dari rc.local."""
    import re
    for begin, end in ((RC_BEGIN, RC_END), (RC_BEGIN_LEGACY, RC_END_LEGACY)):
        text = re.sub(
            re.escape(begin) + r".*?" + re.escape(end) + r"\n?",
            "", text, flags=re.S,
        )
    return text


def autostart_status(client):
    """Tampilkan status autostart (rc.local)."""
    sep()
    print(f"  {bold('🔍')} Autostart Status — MaixCAM (rc.local)")
    sep()

    rc = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN in rc or RC_BEGIN_LEGACY in rc:
        ok(f"I-Sora autostart AKTIF di {RC_LOCAL}")
    else:
        print(f"  {yellow('Belum di-set autostart')} — jalankan --autostart")

    disabled = _ssh(client, "test -e /boot/rclocal.disable && echo yes || echo no")
    if disabled == "yes":
        warn("/boot/rclocal.disable ADA — rc.local TIDAK jalan saat boot!")
    print()


def autostart_set(client, do_deploy=True):
    """
    Deploy kode (opsional) lalu pasang blok autostart I-Sora ke /etc/rc.local.
    Idempotent: blok lama di-refresh, bukan ditumpuk. Dipakai untuk device
    headless (layar dicopot) di mana launcher MaixApp tidak bisa jalan.
    """
    sep()
    print(f"  {bold('⚡')} Set Autostart → {cyan(RC_LOCAL)}")
    sep()

    if do_deploy:
        deploy(client)

    rc = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    rc = _strip_block(rc)
    if not rc.strip():
        rc = "#!/bin/sh\n"
    if not rc.startswith("#!"):
        rc = "#!/bin/sh\n" + rc
    if not rc.endswith("\n"):
        rc += "\n"
    rc = rc + RC_BLOCK

    _write_rc_local(client, rc)
    _ssh(client, "rm -f /boot/rclocal.disable 2>/dev/null; sync")
    # Buang skrip init era-AuralAI supaya tidak jalan berdampingan dengan yang baru.
    _ssh(client, "rm -f %s 2>/dev/null" % " ".join(LEGACY_INIT_PATHS))

    # Install the early boot-chime init script (S15, before WiFi). Written via
    # base64 to avoid quoting/CRLF issues, then chmod +x. Safe + self-adaptive
    # (see CHIME_INIT_SCRIPT) so it cannot stall boot.
    import base64 as _b64
    _b = _b64.b64encode(CHIME_INIT_SCRIPT.encode("utf-8")).decode()
    _ssh(
        client,
        "python3 -c \"import base64,sys;"
        f"open('{CHIME_INIT_PATH}','wb').write(base64.b64decode(sys.argv[1]))\" '{_b}' "
        f"&& chmod +x {CHIME_INIT_PATH} && sync",
    )
    if _ssh(client, f"test -x {CHIME_INIT_PATH} && echo ok"):
        ok(f"Early boot chime dipasang di {CHIME_INIT_PATH} (~4s, sebelum WiFi)")
    else:
        warn(f"Gagal memasang {CHIME_INIT_PATH} — chime jatuh ke jalur rc.local/python")

    # The app launcher itself (S26 — before WiFi association).
    _b = _b64.b64encode(APP_INIT_SCRIPT.encode("utf-8")).decode()
    _ssh(
        client,
        "python3 -c \"import base64,sys;"
        f"open('{APP_INIT_PATH}','wb').write(base64.b64decode(sys.argv[1]))\" '{_b}' "
        f"&& chmod +x {APP_INIT_PATH} && sync",
    )
    if _ssh(client, f"test -x {APP_INIT_PATH} && echo ok"):
        ok(f"App launcher dipasang di {APP_INIT_PATH} (~9s, sebelum WiFi assoc)")
    else:
        err(f"Gagal memasang {APP_INIT_PATH} — device TIDAK akan autostart")

    # Release helper (auto-update switch + rollback) and the WiFi roam hook.
    install_system_files(client)

    # Headless unit: the touchscreen probe costs ~2.3s on absent hardware.
    if _ssh(client, f"test -e {TOUCH_INIT_PATH} && echo yes") == "yes":
        _ssh(client, f"mv {TOUCH_INIT_PATH} {TOUCH_INIT_DISABLED} && sync")
        ok(f"Probe touchscreen dimatikan ({TOUCH_INIT_PATH})")

    check = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN in check:
        ok(f"Autostart diset di {RC_LOCAL}")
        print()
        print(f"  {green('✓')} Device akan otomatis jalan saat boot (headless).")
        print(f"  {yellow('🌐')} Dashboard → http://{'{host}'}:8080")
        print()
        print(dim("  Untuk membatalkan: python tools/run.py --autostart-off"))
    else:
        err("Verifikasi gagal — blok autostart tidak ditemukan di rc.local")


def autostart_clear(client):
    """Hapus blok autostart I-Sora dari /etc/rc.local."""
    sep()
    print(f"  {bold('🗑')} Hapus Autostart (rc.local)")
    sep()

    rc = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN not in rc and RC_BEGIN_LEGACY not in rc:
        warn("Tidak ada blok I-Sora di rc.local — tidak ada yang dihapus")
        return

    _write_rc_local(client, _strip_block(rc))
    # Also remove the early boot-chime + app init scripts, and hand the
    # touchscreen probe back, so the device fully reverts to a stock boot.
    _ssh(client, "rm -f %s %s %s 2>/dev/null"
         % (CHIME_INIT_PATH, APP_INIT_PATH, " ".join(LEGACY_INIT_PATHS)))
    _ssh(client, f"test -e {TOUCH_INIT_DISABLED} && "
                 f"mv {TOUCH_INIT_DISABLED} {TOUCH_INIT_PATH}; sync")
    check = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN not in check:
        ok("Autostart I-Sora dihapus dari rc.local")
        ok(f"Early boot chime ({CHIME_INIT_PATH}) dihapus")
        ok(f"App launcher ({APP_INIT_PATH}) dihapus — rc.local kembali dipakai")
    else:
        err("Gagal menghapus blok autostart")
    print()


def list_modes():
    print(f"\n  {bold('Mode yang tersedia:')}\n")
    for key, m in MODES.items():
        print(f"  {cyan(key):<14}  {m['label']}")
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="I-Sora Runner — deploy + run mode di MaixCAM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host",       default=DEFAULT_HOST, help=f"IP MaixCAM (default: {DEFAULT_HOST})")
    parser.add_argument("--port",       type=int, default=DEFAULT_PORT)
    parser.add_argument("--user",       default=DEFAULT_USER)
    parser.add_argument("--password",   default=DEFAULT_PASS)
    parser.add_argument("--mode",       default="main", choices=list(MODES.keys()), metavar="MODE",
                        help="Mode: " + ", ".join(MODES.keys()))
    parser.add_argument("--no-deploy",  action="store_true", help="Skip upload, langsung run")
    parser.add_argument("--audio",      action="store_true", help="Upload audio/ juga saat deploy")
    parser.add_argument("--background", action="store_true", help="Run di background (nohup)")
    parser.add_argument("--stop",       action="store_true", help="Hentikan proses yang berjalan")
    parser.add_argument("--logs",       action="store_true", help="Tail log background")
    parser.add_argument("--status",     action="store_true", help="Tampilkan status proses")
    parser.add_argument("--list",       action="store_true", help="Tampilkan daftar mode")
    parser.add_argument("--extra",           default="",    help='Argumen tambahan ke script, mis: "--dry-run"')
    # ── Autostart ──
    parser.add_argument("--autostart",       action="store_true", help="Set I-Sora sebagai app autostart saat boot")
    parser.add_argument("--autostart-off",   action="store_true", help="Hapus autostart")
    parser.add_argument("--autostart-status",action="store_true", help="Lihat app autostart saat ini")
    args = parser.parse_args()

    print(bold("\n  I-Sora Runner"))

    if args.list:
        list_modes()
        return

    mode_cfg = dict(MODES[args.mode])
    mode_cfg["_key"] = args.mode

    # ── Autostart modes ──
    if args.autostart_status:
        client = connect(args.host, args.port, args.user, args.password)
        autostart_status(client)
        client.close()
        return

    if getattr(args, 'autostart_off', False):
        client = connect(args.host, args.port, args.user, args.password)
        autostart_clear(client)
        client.close()
        return

    if args.autostart:
        client = connect(args.host, args.port, args.user, args.password)
        autostart_set(client, do_deploy=not args.no_deploy)
        client.close()
        return

    # ── Stop mode ──
    if args.stop:
        client = connect(args.host, args.port, args.user, args.password)
        stop_process(client, mode_cfg)
        client.close()
        return

    # ── Logs mode ──
    if args.logs:
        client = connect(args.host, args.port, args.user, args.password)
        tail_logs(client, mode_cfg)
        client.close()
        return

    # ── Status mode ──
    if args.status:
        client = connect(args.host, args.port, args.user, args.password)
        show_status(client, mode_cfg)
        client.close()
        return

    # ── Deploy + Run ──
    client = connect(args.host, args.port, args.user, args.password)

    if not args.no_deploy:
        deploy(client, audio=args.audio)

    if args.background:
        run_background(client, mode_cfg, args.extra, args.host)
    else:
        run_foreground(client, mode_cfg, args.extra, args.host)

    client.close()
    print()


if __name__ == "__main__":
    main()
