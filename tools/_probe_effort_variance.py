"""Does reasoning effort drive the wording drift?

gpt-5.6-terra rejects `temperature` on /v1/responses, so the only decoding knob
left on the shipped model is reasoning.effort. This sends the SAME jpeg bytes N
times at each effort level and prints the answers side by side, so "low vs
minimal vs none" is a measurement rather than a guess. Scratch, delete.
"""
import os
import time
import _dev_ssh as d

N = int(os.environ.get("N", "4"))
EFFORTS = os.environ.get("EFFORTS", "none,minimal,low").split(",")

c = d.connect()


def sh(cmd, t=300):
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
prompt = cfg.PROMPT_SCENE
print("frame bytes:", len(jpeg), "| model:", cfg.get("openai_model"))

for effort in EFFORTS_LIST:
    # set() only touches memory - no disk write, so the device keeps whatever
    # the operator configured once this probe exits.
    cfg.set("openai_reasoning_effort", effort)
    a = get_adapter(cfg.AI_PROVIDER, cfg)
    print("")
    print("=== effort=%s ===" % effort)
    for i in range(N_RUNS):
        t0 = time.time()
        try:
            out = a.describe_scene(jpeg, prompt)
        except Exception as e:
            out = "ERROR: %s" % e
        print("  [%.1fs] %s" % (time.time() - t0, out))
'''.replace("N_RUNS", str(N)).replace("EFFORTS_LIST", repr(EFFORTS))

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
    p("no snapshot")
    c.close()
    raise SystemExit(1)

sftp = c.open_sftp()
with sftp.open("/tmp/_probe_effort.py", "w") as f:
    f.write(PROBE)
sftp.close()

p(sh("cd /root/isora && python3 /tmp/_probe_effort.py 2>&1", t=600))
c.close()
