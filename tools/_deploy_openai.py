"""Deploy the openai_adapter.py rewrite (Responses API + reasoning effort) +
the decrypt-bug fixes in gemini/claude adapters, restart, switch provider to
openai + set model/effort live, then trigger a real describe and read back
[scene-timing]. Busybox-safe restart pattern from _measure_ctx2.py. Scratch,
delete."""
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
for rel in ("adapters/openai_adapter.py", "adapters/gemini_adapter.py",
            "adapters/claude_adapter.py", "config.py", "core/cloud.py"):
    local = os.path.join(base, *rel.split("/"))
    remote = f"/root/isora/{rel}"
    sftp.put(local, remote)
    print("deployed", rel)
sftp.close()

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

# ── switch provider to openai (live /config) + context mode ────────────────
tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")


def cmd(payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' "
              "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
              "http://127.0.0.1:8080/command; echo")


def post_config(payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' "
              "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
              "http://127.0.0.1:8080/config; echo")


print(post_config('{"ai_provider":"openai","openai_model":"gpt-5.6-terra",'
                   '"openai_reasoning_effort":"low"}'))

cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
print("mode:", sh("wget -qO- http://127.0.0.1:8080/status | "
                   "sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

print(f"\n===== DESCRIBE (openai/gpt-5.6-terra/low) =====")
cmd('{"cmd":"describe"}')
time.sleep(10)
p(sh(f"grep -E 'scene-timing|Scene:|Sending frame|AI adapter error' {logf} | tail -n 8"))

c.close()
