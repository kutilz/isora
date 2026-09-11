"""Deploy volume mode (chord = MODE+ACTION) + its chimes, restart, verify live.

Scratch — delete when landed.
"""
import os, time, paramiko
import _dev_ssh as d

ROOT  = r"C:\Users\Ilyas\Documents\isora"
CODE = [
    ("device/config.py",                    "/root/isora/config.py"),
    ("device/core/orchestrator.py",         "/root/isora/core/orchestrator.py"),
    ("device/server/web_server.py",         "/root/isora/server/web_server.py"),
    ("device/server/static/buttons.html",   "/root/isora/server/static/buttons.html"),
]
WAVS = ["chime_vol_enter.wav", "chime_vol_exit.wav", "chime_vol_up.wav",
        "chime_vol_down.wav", "chime_vol_limit.wav", "atur_volume.wav"]


def patient_connect(tries=8):
    last = None
    for _ in range(tries):
        try:
            cc = paramiko.SSHClient()
            cc.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cc.connect(d.HOST, username=d.USER, password=d.PASS, timeout=12,
                       banner_timeout=30, auth_timeout=20,
                       look_for_keys=False, allow_agent=False)
            return cc
        except Exception as e:
            last = e
            time.sleep(6)
    raise SystemExit(f"unreachable: {last}")


c = patient_connect()


def sh(cmd, t=40):
    _i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace")


def p(m):
    print(m, flush=True)


# ── upload ───────────────────────────────────────────────────────────────────
sftp = c.open_sftp()
for local, remote in CODE:
    sftp.put(os.path.join(ROOT, local.replace("/", os.sep)), remote)
    p(f"  -> {remote}")
for w in WAVS:
    sftp.put(os.path.join(ROOT, "audio", w), f"/root/audio/{w}")
    p(f"  -> /root/audio/{w}")
sftp.close()

# ── restart ──────────────────────────────────────────────────────────────────
sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(20):
    if not sh("pidof python3").strip():
        p(f"pid clear @{i}s")
        break
    time.sleep(1)
sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
for i in range(60):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 40"):
        p(f"web up @{i}s")
        break
    time.sleep(1)


def status_vol():
    return sh("wget -qO- http://127.0.0.1:8080/status "
              "| grep -o '\"audio_volume\": *[0-9]*'").strip()


def press(which):
    return sh("wget -qO- --post-data='{\"button\":\"%s\"}' "
              "--header='Content-Type: application/json' "
              "http://127.0.0.1:8080/button; echo" % which).strip()


p("start: " + status_vol())

# 1. chord opens volume mode
p("chord -> " + press("chord"))
time.sleep(2)

# 2. two MODE presses = two steps down
p("mode  -> " + press("mode"))
time.sleep(2)
p("mode  -> " + press("mode"))
time.sleep(2)
p("after 2 steps down: " + status_vol())

# 3. one ACTION press = one step up
p("action-> " + press("action"))
time.sleep(2)
p("after 1 step up: " + status_vol())

# 4. idle timeout closes the mode and persists the level
time.sleep(8)
p("persisted: " + sh("grep -o '\"audio_volume\": *[0-9]*' /root/config.json").strip())

# 5. presses outside the mode must behave normally again
p("mode  -> " + press("mode"))
time.sleep(3)
p("volume unchanged by a normal press: " + status_vol())
p("mode now: " + sh("wget -qO- http://127.0.0.1:8080/status | grep -o '\"mode\": *\"[a-z]*\"'").strip())

# ── what the device logged / whether any cue was missing ─────────────────────
logf = sh("ls -t /root/logs/*.log 2>/dev/null | head -1").strip()
p("\n--- log ---")
p(sh(f"grep -E 'Volume|Cue missing|Play error|Traceback' {logf} | tail -25"))

c.close()
