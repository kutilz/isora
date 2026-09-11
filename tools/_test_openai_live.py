"""App is already running with the new openai_adapter.py deployed (previous
restart succeeded despite a transient SSH hiccup). No restart needed here —
just live-tune config + trigger real describes across reasoning levels via
the same /command path a real button press uses. Scratch, delete."""
import re
import time
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=25):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


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


def post_config(payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' "
              "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
              "http://127.0.0.1:8080/config; echo")


print(post_config('{"ai_provider":"openai","openai_model":"gpt-5.6-terra"}'))

cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
print("mode:", sh("wget -qO- http://127.0.0.1:8080/status | "
                   "sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

for effort in ("low", "none", "medium"):
    print(post_config('{"openai_reasoning_effort":"%s"}' % effort))
    print(f"\n===== DESCRIBE effort={effort} =====")
    cmd('{"cmd":"describe"}')
    time.sleep(10)
    p(sh(f"grep -E 'scene-timing|Scene:|Sending frame|AI adapter error|Unexpected adapter' {logf} | tail -n 5"))
    time.sleep(2)

c.close()
