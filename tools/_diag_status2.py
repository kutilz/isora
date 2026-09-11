"""Check /status + tail scene-timing log after the openai deploy restart.
Scratch, delete."""
import re
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=20):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


p("pid: " + sh("pidof python3"))
p("status: " + sh("wget -qO- http://127.0.0.1:8080/status --timeout=8 2>&1 | head -c 300"))

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""
p("log: " + logf)
p(sh(f"tail -n 15 {logf}"))

c.close()
