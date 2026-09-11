"""Boot timeline - where the seconds between power-on and "siap digunakan" go.

Boot cost was being argued from impressions ("terasa lama"). This measures it,
so a change to the init order is judged by a number that moves.

Everything here is read against /proc/uptime, never the wall clock. The device
boots at the epoch and NTP jumps the clock forward at an unpredictable point
*during* boot, so two file mtimes -- or two log lines -- can sit in different
time bases and their difference means nothing. dmesg stamps, /proc/PID/stat
starttime and the marker main.py writes are all monotonic instead.

    python tools/boot_timeline.py                 # auto-discover over USB
    python tools/boot_timeline.py --host 10.0.0.5
    python tools/boot_timeline.py --budget 15     # exit 1 if ready is slower
"""

import argparse
import json
import re
import subprocess
import sys

USER, PASSWORD = "root", "root"


def discover_host():
    """The USB gadget hands the PC a DHCP lease; the device is .1 on that /24."""
    try:
        out = subprocess.run(["ipconfig"], capture_output=True, text=True,
                             timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for m in re.finditer(r"IPv4[^:]*:\s*(\d+\.\d+\.\d+)\.(\d+)", out):
        net, host = m.group(1), int(m.group(2))
        if host == 1:
            continue                       # that is a gateway, not our lease
        cand = f"{net}.1"
        if subprocess.run(["ping", "-n", "1", "-w", "800", cand],
                          capture_output=True).returncode == 0:
            return cand
    return None


def connect(host):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=USER, password=PASSWORD, timeout=10,
              banner_timeout=20, auth_timeout=15,
              look_for_keys=False, allow_agent=False)
    return c


PROBE = r"""
python3 - <<'PY'
import json, os, re, subprocess
out = {}
with open("/proc/uptime") as f:
    out["uptime"] = float(f.read().split()[0])

def num(path):
    # First float in a file, or None.
    try:
        with open(path) as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None

out["ready"] = num("/tmp/isora_boot_ready")
out["chime"] = num("/tmp/.boot_chime_played")

# App spawn, straight off the kernel: field 22 of /proc/PID/stat is the process
# start time in clock ticks since boot. Immune to every clock jump.
out["spawn"] = None
tck = os.sysconf("SC_CLK_TCK")
mine = {str(os.getpid()), str(os.getppid())}
for pid in os.listdir("/proc"):
    if not pid.isdigit() or pid in mine:
        continue
    try:
        with open("/proc/%s/cmdline" % pid, "rb") as f:
            argv = f.read().decode("utf-8", "replace").split(chr(0))
        # An ARGUMENT that is main.py, not a command line that merely mentions
        # it -- this probe's own shell carries its source, main.py included.
        if not any(a.endswith("/main.py") or a == "main.py" for a in argv):
            continue
        with open("/proc/%s/stat" % pid) as f:
            fields = f.read().rsplit(") ", 1)[1].split()
        out["spawn"] = int(fields[19]) / tck          # field 22, 1-based
        out["pid"] = int(pid)
    except (OSError, IndexError, ValueError):
        pass

dm = subprocess.run(["dmesg"], capture_output=True, text=True).stdout
def last(pat):
    hits = [float(m.group(1)) for m in
            re.finditer(r"\[\s*(\d+\.\d+)\][^\n]*" + pat, dm)]
    return max(hits) if hits else None
out["touch_probe"] = last(r"(hyn_probe: Exit|GTP works in interrupt mode)")
out["udev"] = last(r"udevd\[\d+\]: starting")
out["wifi_fw"] = last(r"rwnx_load_firmware")
print(json.dumps(out))
PY
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--budget", type=float,
                    help="fail if time-to-ready exceeds this many seconds")
    args = ap.parse_args()

    host = args.host or discover_host()
    if not host:
        sys.exit("device not found - pass --host")

    client = connect(host)
    _i, o, e = client.exec_command(PROBE, timeout=60)
    raw = o.read().decode("utf-8", "replace").strip()
    client.close()
    try:
        d = json.loads(raw.splitlines()[-1])
    except (ValueError, IndexError):
        sys.exit(f"probe failed: {raw or e.read().decode('utf-8', 'replace')}")

    uptime = d["uptime"]
    rows = [
        ("boot chime  (S00aisorachime)", d["chime"]),
        ("touch probe done  (dead LCD)", d["touch_probe"]),
        ("udev started",                 d["udev"]),
        ("wifi firmware loaded",         d["wifi_fw"]),
        ("app spawned",                  d["spawn"]),
        ("READY  (all threads running)", d["ready"]),
    ]

    print(f"\n  Boot timeline - {host}  (uptime {uptime:.0f}s, "
          f"app pid {d.get('pid', '?')})\n")
    prev = 0.0
    for name, t in rows:
        # A stale marker from an earlier boot cannot describe this one.
        if t is None or not (0.0 <= t <= uptime + 1.0):
            print(f"    {name:<32}      --")
            continue
        print(f"    {name:<32} {t:7.2f}s   (+{t - prev:5.2f})")
        prev = t

    ready = d["ready"]
    if ready is None or not (0.0 <= ready <= uptime + 1.0):
        sys.exit("\n  no readiness marker for this boot - either the app has "
                 "not finished starting, or it predates _mark_boot_ready()")
    print(f"\n  time-to-ready: {ready:.2f}s")
    if args.budget:
        if ready > args.budget:
            sys.exit(f"  OVER BUDGET (>{args.budget:.0f}s)")
        print(f"  within budget ({args.budget:.0f}s)")


if __name__ == "__main__":
    main()
