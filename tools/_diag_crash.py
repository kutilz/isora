"""Check device state after a failed restart: is python3 alive? what's in the
log / stderr? Scratch, delete."""
import re
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=20):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


p("pidof python3: " + sh("pidof python3"))
p("--- /tmp/isora_main.log tail ---")
p(sh("tail -n 60 /tmp/isora_main.log"))
p("--- py_compile check on changed files ---")
for f in ("adapters/openai_adapter.py", "adapters/gemini_adapter.py",
          "adapters/claude_adapter.py", "config.py", "core/cloud.py"):
    out = sh(f"python3 -m py_compile /root/isora/{f} && echo COMPILE_OK_{f}")
    p(out)

c.close()
