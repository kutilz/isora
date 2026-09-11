"""On-device: run N real describes through the app, report time-to-first-word."""
import sys, os, re, json, time
sys.path.insert(0, "/root/isora")
import urllib.request as ur
from config import cfg

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
BASE = "http://127.0.0.1:8080"
TOK = cfg.get("device_token", "")


def post(path, obj):
    req = ur.Request(BASE + path, data=json.dumps(obj).encode(),
                     headers={"Content-Type": "application/json", "X-Auth-Token": TOK},
                     method="POST")
    return ur.urlopen(req, timeout=15).read().decode()


def status():
    return json.loads(ur.urlopen(BASE + "/status", timeout=10).read())


if status().get("mode") != "context":
    post("/command", {"cmd": "set_mode", "mode": "context"})
    for _ in range(25):
        time.sleep(1)
        if status().get("mode") == "context":
            break
print("mode =", status().get("mode"), "| stream_chunks =", cfg.get("scene_stream_chunks"))

logf = sys.argv[2] if len(sys.argv) > 2 else ""
if not logf:
    logs = ["/root/logs/" + f for f in os.listdir("/root/logs") if f.endswith(".log")]
    logf = max(logs, key=os.path.getmtime) if logs else ""
print("log =", logf)


def logsize():
    try:
        return os.path.getsize(logf)
    except OSError:
        return 0


def wait_idle(limit=40):
    """Don't start the next describe until the previous one has finished
    speaking — otherwise its chunks just queue behind live audio."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        try:
            if not status().get("audio_text"):
                time.sleep(1.0)
                if not status().get("audio_text"):
                    return
        except Exception:
            pass
        time.sleep(0.5)


for i in range(N):
    wait_idle()
    # keep the camera warm so the frame is fresh
    try:
        ur.urlopen(BASE + "/snapshot", timeout=8).read()
    except Exception:
        pass
    off = logsize()
    t0 = time.monotonic()
    post("/command", {"cmd": "describe"})
    first_audio = None
    text = ""
    deadline = t0 + 45
    while time.monotonic() < deadline:
        time.sleep(0.2)
        try:
            cap = status().get("last_caption", {}).get("text", "")
        except Exception:
            continue
        if cap and cap not in ("sedang menganalisis", "masih memproses",
                               "koneksi lambat") and not cap.startswith("chime"):
            first_audio = time.monotonic() - t0
            text = cap
            break
    print("\n--- describe #%d ---" % (i + 1))
    print("  press -> first spoken word: %s" % (
        ("%.2fs" % first_audio) if first_audio else "TIMEOUT"))
    print("  said: %r" % text[:90])
    time.sleep(2.5)
    with open(logf, "rb") as f:
        f.seek(off)
        tail = f.read().decode("utf-8", "replace")
    for ln in tail.splitlines():
        if any(k in ln for k in ("scene-timing", "Scene:", "Sending frame")):
            try:
                j = json.loads(ln)
                print("   |", j["msg"][:120])
            except Exception:
                pass
    time.sleep(3)

print("\nload:", open("/proc/loadavg").read().strip())
