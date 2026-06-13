"""
AuralAI Runner — Deploy + jalankan mode di MaixCAM tanpa SSH manual.
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
    python tools/run.py --autostart            # Set AuralAI sebagai app autostart saat boot
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

DEFAULT_HOST = os.environ.get("AURAL_MAIX_HOST", "maixcam.local")
DEFAULT_PORT = int(os.environ.get("AURAL_MAIX_PORT", "22"))
DEFAULT_USER = os.environ.get("AURAL_MAIX_USER", "root")
DEFAULT_PASS = os.environ.get("AURAL_MAIX_PASS", "root")

REMOTE_BASE   = "/root/aural-ai"
REMOTE_DEVICE = "/root/aural-ai"
REMOTE_AUDIO  = "/root/audio"

PROJECT_ROOT  = os.path.join(os.path.dirname(__file__), "..")
DEVICE_DIR    = os.path.join(PROJECT_ROOT, "device")
AUDIO_DIR     = os.path.join(PROJECT_ROOT, "audio")

EXCLUDE_PATTERNS = {"__pycache__", ".pyc", ".pyo", ".DS_Store", "node_modules", ".git"}

# ─── Definisi mode ────────────────────────────────────────────────────────────

MODES = {
    "main": {
        "label":       "AuralAI SDK — Main",
        "cwd":         REMOTE_DEVICE,
        "script":      "main.py",
        "pid_file":    "/tmp/aural_main.pid",
        "log_file":    "/tmp/aural_main.log",
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
    pid_file = mode_cfg.get("pid_file") or f"/tmp/aural_{mode_cfg['script'].replace('.py','')}.pid"
    log_file = mode_cfg.get("log_file") or f"/tmp/aural_{mode_cfg['script'].replace('.py','')}.log"

    cmd = (
        f"cd {cwd} && "
        f"nohup python {script} {extra_args} > {log_file} 2>&1 & "
        f"echo $! > {pid_file} && echo $!"
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
# LCD; on a screen-less AuralAI unit it dies at boot, so that mechanism never
# fires. Autostart from /etc/rc.local instead — /etc/init.d/S99local runs it at
# the end of boot (after network + avahi). Reliable for a headless camera app.
RC_LOCAL = "/etc/rc.local"
RC_BEGIN = "# >>> AuralAI autostart >>>"
RC_END   = "# <<< AuralAI autostart <<<"
RC_BLOCK = (
    RC_BEGIN + "\n"
    "sleep 5\n"
    "cd /root/aural-ai\n"
    "nohup python3 /root/aural-ai/main.py >> /tmp/aural_main.log 2>&1 &\n"
    "echo $! > /tmp/aural_main.pid\n"
    + RC_END + "\n"
)


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
    """Buang blok autostart AuralAI lama dari isi rc.local."""
    import re
    return re.sub(
        re.escape(RC_BEGIN) + r".*?" + re.escape(RC_END) + r"\n?",
        "", text, flags=re.S,
    )


def autostart_status(client):
    """Tampilkan status autostart (rc.local)."""
    sep()
    print(f"  {bold('🔍')} Autostart Status — MaixCAM (rc.local)")
    sep()

    rc = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN in rc:
        ok(f"AuralAI autostart AKTIF di {RC_LOCAL}")
    else:
        print(f"  {yellow('Belum di-set autostart')} — jalankan --autostart")

    disabled = _ssh(client, "test -e /boot/rclocal.disable && echo yes || echo no")
    if disabled == "yes":
        warn("/boot/rclocal.disable ADA — rc.local TIDAK jalan saat boot!")
    print()


def autostart_set(client, do_deploy=True):
    """
    Deploy kode (opsional) lalu pasang blok autostart AuralAI ke /etc/rc.local.
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
    """Hapus blok autostart AuralAI dari /etc/rc.local."""
    sep()
    print(f"  {bold('🗑')} Hapus Autostart (rc.local)")
    sep()

    rc = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN not in rc:
        warn("Tidak ada blok AuralAI di rc.local — tidak ada yang dihapus")
        return

    _write_rc_local(client, _strip_block(rc))
    check = _ssh(client, f"cat {RC_LOCAL} 2>/dev/null")
    if RC_BEGIN not in check:
        ok("Autostart AuralAI dihapus dari rc.local")
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
        description="AuralAI Runner — deploy + run mode di MaixCAM",
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
    parser.add_argument("--autostart",       action="store_true", help="Set AuralAI sebagai app autostart saat boot")
    parser.add_argument("--autostart-off",   action="store_true", help="Hapus autostart")
    parser.add_argument("--autostart-status",action="store_true", help="Lihat app autostart saat ini")
    args = parser.parse_args()

    print(bold("\n  AuralAI Runner"))

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
