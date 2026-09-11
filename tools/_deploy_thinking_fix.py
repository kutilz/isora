"""Deploy the thinkingConfig fix to gemini_adapter.py, restart, trigger a real
describe via the web API, and read back [scene-timing] to confirm the win.
Busybox-safe restart pattern copied from _measure_ctx2.py. Scratch, delete."""
import os
import re
import time
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=40):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


# ── deploy ──────────────────────────────────────────────────────────────────
sftp = c.open_sftp()
base = r"C:\Users\Ilyas\Documents\isora\device"
sftp.put(os.path.join(base, "adapters", "gemini_adapter.py"),
         "/root/isora/adapters/gemini_adapter.py")
sftp.close()
print("deployed gemini_adapter.py")

# ── busybox-safe restart ────────────────────────────────────────────────────
sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(20):
    if not sh("pidof python3").strip():
        print(f"pid clear @{i}s")
        break
    time.sleep(1)
else:
    print("STILL ALIVE; abort")
    c.close()
    raise SystemExit(1)

sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
for i in range(45):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 40"):
        print(f"web up @{i}s")
        break
    time.sleep(1)

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""
print("log:", logf)

# ── set context mode, warm camera, trigger 2 describes ─────────────────────
tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")


def cmd(payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' "
              "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
              "http://127.0.0.1:8080/command; echo")


cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
print("mode:", sh("wget -qO- http://127.0.0.1:8080/status | "
                   "sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

for n in (1, 2):
    print(f"\n===== DESCRIBE #{n} =====")
    t0 = time.monotonic()
    cmd('{"cmd":"describe"}')
    time.sleep(14)
    p(sh(f"grep -E 'scene-timing|Scene:' {logf} | tail -n 6"))

c.close()
