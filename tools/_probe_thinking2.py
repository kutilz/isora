"""Confirm thinking is really off + check run-to-run variance with the exact
deployed config (thinkingBudget=0, max=220), 5x back to back, real frame.
Scratch, delete."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=90):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = r'''
import sys, time, json, base64
sys.path.insert(0, "/root/isora")
import urllib.request as ur, urllib.error
from config import cfg

key = cfg.get("gemini_api_key", "") or cfg.GEMINI_API_KEY
model = cfg.get("gemini_model", "gemini-flash-latest")
prompt = cfg.get("prompt_scene", "Describe the scene in 1-2 sentences.")

jpeg = ur.urlopen("http://127.0.0.1:8080/snapshot", timeout=5).read()
print("jpeg bytes:", len(jpeg))

def call(n):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    parts = [{"text": prompt}, {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}]
    payload = {"contents": [{"parts": parts}],
               "generationConfig": {"maxOutputTokens": 220, "thinkingConfig": {"thinkingBudget": 0}}}
    req = ur.Request(url, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with ur.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        dt = (time.monotonic() - t0) * 1000
        data = json.loads(raw)
        cand = data.get("candidates", [{}])[0]
        usage = data.get("usageMetadata", {})
        text = cand.get("content", {}).get("parts", [{}])[0].get("text", "<none>")
        thoughts = usage.get("thoughtsTokenCount", 0)
        outtok = usage.get("candidatesTokenCount")
        snippet = text[:80]
        print("run%d: elapsed=%.0fms thoughts=%r out=%r text=%r" % (n, dt, thoughts, outtok, snippet))
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        print(f"run{n}: elapsed={dt:.0f}ms ERROR: {e}")

for i in range(5):
    call(i)
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_probe_thinking2_remote.py", "w") as f:
    f.write(dev)
sftp.close()

p(sh("python3 /tmp/_probe_thinking2_remote.py", t=120))
p(sh("rm -f /tmp/_probe_thinking2_remote.py; echo done"))

c.close()
