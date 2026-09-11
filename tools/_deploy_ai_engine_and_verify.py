"""Deploy the ai_engine.py stage-tag fix, restart, run one describe on the
already-configured openai provider, confirm [scene-timing] now says
dominant=openai (not gemini) and gemini_ms still populates for the dashboard.
Then restore explorer mode. Scratch, delete."""
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


sftp = c.open_sftp()
base = r"C:\Users\Ilyas\Documents\isora\device"
sftp.put(os.path.join(base, "core", "ai_engine.py"), "/root/isora/core/ai_engine.py")
sftp.close()
print("deployed ai_engine.py")

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

tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")


def cmd(payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' "
              "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
              "http://127.0.0.1:8080/command; echo")


print("ai_provider check:", sh(
    "python3 -c \"import sys; sys.path.insert(0,'/root/isora'); "
    "from config import cfg; print(cfg.get('ai_provider'), cfg.get('openai_model'), "
    "cfg.get('openai_reasoning_effort'))\""
))

cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
cmd('{"cmd":"describe"}')
time.sleep(9)
p(sh(f"grep -E 'scene-timing|Scene:|Sending frame' {logf} | tail -n 4"))

# check dashboard snapshot reflects gemini_ms populated
p(sh("wget -qO- http://127.0.0.1:8080/status | grep -o '\"scene_metrics[^}]*}' | head -c 400"))

# restore explorer mode
cmd('{"cmd":"set_mode","mode":"explorer"}')
time.sleep(2)
print("final mode:", sh("wget -qO- http://127.0.0.1:8080/status | "
                         "sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

c.close()
