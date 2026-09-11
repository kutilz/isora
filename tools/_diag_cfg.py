"""Scratch: dump AI-relevant config via a remote temp script (avoids shell
quoting issues with -c). Delete when done."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=40):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = '''
import sys
sys.path.insert(0, "/root/isora")
from config import cfg
for k in ("ai_provider","gemini_model","openai_model","claude_model","ai_timeout_s",
          "ai_slow_warn_s","prompt_scene","word_cache_enabled"):
    print(k, "=", repr(cfg.get(k)))
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_diag_cfg_remote.py", "w") as f:
    f.write(dev)
sftp.close()

p(sh("python3 /tmp/_diag_cfg_remote.py"))
p(sh("rm -f /tmp/_diag_cfg_remote.py; echo done"))

c.close()
