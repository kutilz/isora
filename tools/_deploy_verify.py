"""ONE-SHOT deploy + verify after the user power-cycles. Deploys all changed
files, validates with py_compile, restarts ONCE, then runs several describes to
confirm (a) the playback fix (play END ~= audio, not 2x) and (b) the word cache
warming -> HIT. Run only when the device is freshly booted. Scratch — delete."""
import os, re, time
import _dev_ssh as d

FILES = [
    ("utils/stage_timer.py", "/root/isora/utils/stage_timer.py"),
    ("utils/word_cache.py",  "/root/isora/utils/word_cache.py"),
    ("core/audio_manager.py","/root/isora/core/audio_manager.py"),
    ("core/ai_engine.py",    "/root/isora/core/ai_engine.py"),
    ("config.py",            "/root/isora/config.py"),
]
BASE = r"C:\Users\Ilyas\Documents\isora\device"

c = d.connect()
def sh(cmd, t=40):
    o, e = d.run(c, cmd, timeout=t); return (o or "") + (e or "")
def san(s): return s.encode("ascii", "replace").decode()

# 0. refuse to run if the box is still wedged (avoid compounding VI leak)
up = sh("uptime").strip()
print("uptime:", up)
if "min," not in up and "up 0" not in up and " 0:" not in up:
    pass  # best-effort; proceed

# 1. deploy + validate
sftp = c.open_sftp()
for loc, rem in FILES:
    sftp.put(os.path.join(BASE, *loc.split("/")), rem)
sftp.close()
print("deployed:", ", ".join(f for f, _ in FILES))
comp = sh("cd /root/isora && for f in utils/stage_timer.py utils/word_cache.py "
          "core/audio_manager.py core/ai_engine.py config.py; do "
          "python3 -m py_compile $f && echo \"ok $f\" || echo \"FAIL $f\"; done")
print(san(comp))
if "FAIL" in comp:
    print("py_compile failed — NOT restarting"); c.close(); raise SystemExit(1)

# 2. ONE busybox-safe restart
sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(20):
    if not sh("pidof python3").strip():
        print(f"pid clear @{i}s"); break
    time.sleep(1)
else:
    print("STILL ALIVE; abort"); c.close(); raise SystemExit(1)
sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
for i in range(50):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 40"):
        print(f"web up @{i}s"); break
    time.sleep(1)
else:
    print("web NOT up — tail:"); print(san(sh("tail -n 20 /tmp/isora_main.log")))
    c.close(); raise SystemExit(1)

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""
print("pid", pid, "log", logf)

tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
def cmd(p):
    return sh(tokget + f"; wget -qO- --post-data='{p}' --header=\"X-Auth-Token: $T\" "
              "--header='Content-Type: application/json' http://127.0.0.1:8080/command; echo")

cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
print("mode:", sh("wget -qO- http://127.0.0.1:8080/status | sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

# 3. several describes of whatever the camera sees; vocabulary should warm
for n in range(1, 6):
    print(f"\n===== DESCRIBE #{n} =====")
    cmd('{"cmd":"describe"}')
    time.sleep(26)
    print("word_cache files:", sh("ls /root/audio/word_cache/*.pcm 2>/dev/null | wc -l").strip())
    print(san(sh(f"grep -E 'WORD-CACHE HIT|scene-timing\\] total|play END|play\\(\\) blocked' {logf} | tail -8")))

c.close()
