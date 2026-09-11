"""Isolate MODEL variance from CAMERA variance.

The device answering differently on every describe could be either the model
paraphrasing itself or the camera genuinely handing it a different frame
(sensor noise, auto-exposure, a hand drifting). This grabs ONE jpeg and sends
those exact same bytes N times, so anything that differs is the model alone.

Runs the calls on the device, because that is where the decrypted API key
lives. Scratch, delete when done.
"""
import os
import time
import _dev_ssh as d

N = int(os.environ.get("N", "3"))

c = d.connect()


def sh(cmd, t=180):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(str(s).encode("ascii", "replace").decode())


PROBE = '''
import sys, time
sys.path.insert(0, "/root/isora")
from config import cfg
from adapters import get_adapter

jpeg = open("/tmp/probe_frame.jpg", "rb").read()
print("frame bytes:", len(jpeg))
print("provider:", cfg.AI_PROVIDER, "| model:", cfg.get("openai_model"))
print("prompt chars:", len(cfg.PROMPT_SCENE))
a = get_adapter(cfg.AI_PROVIDER, cfg)
for i in range(N_RUNS):
    t0 = time.time()
    try:
        out = a.describe_scene(jpeg, cfg.PROMPT_SCENE)
    except Exception as e:
        out = "ERROR: %s" % e
    print("--- run %d (%.1fs) ---" % (i + 1, time.time() - t0))
    print(out)
'''.replace("N_RUNS", str(N))

# One frame, held constant for every run. The first GET always 404s: the AI
# loop only pays for to_jpeg() once someone has actually asked for a preview
# (orch.wants_preview()), so the request that asks is the one that misses.
sh("wget -q -O /dev/null http://127.0.0.1:8080/snapshot 2>/dev/null; echo x")
sz = "0"
for _ in range(6):
    time.sleep(2)
    sh("wget -q -O /tmp/probe_frame.jpg http://127.0.0.1:8080/snapshot; echo x")
    sz = sh("wc -c < /tmp/probe_frame.jpg 2>/dev/null").strip()
    if sz not in ("", "0"):
        break
p("snapshot bytes: " + sz)
if sz in ("", "0"):
    p("no snapshot - is the device in a mode that captures frames?")
    c.close()
    raise SystemExit(1)

sftp = c.open_sftp()
with sftp.open("/tmp/_probe.py", "w") as f:
    f.write(PROBE)
sftp.close()

p(sh("cd /root/isora && python3 /tmp/_probe.py 2>&1", t=300))
c.close()
