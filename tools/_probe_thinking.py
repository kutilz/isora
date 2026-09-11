"""Root-cause probe: is Gemini's ~16.6s latency + garbled output caused by
default 'thinking' mode? Runs ON the device (has working key resolution),
calling the real endpoint 3 ways with the SAME frame: (a) current code path
(no thinkingConfig), (b) thinkingBudget=0, (c) thinkingBudget=0 + lower
maxOutputTokens. Prints elapsed ms + response text for each. Scratch, delete."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=60):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = r'''
import sys, time, json, base64
sys.path.insert(0, "/root/isora")
import urllib.request, urllib.error
from config import cfg

key = cfg.get("gemini_api_key", "") or cfg.GEMINI_API_KEY
model = cfg.get("gemini_model", "gemini-flash-latest")
prompt = cfg.get("prompt_scene", "Describe the scene in 1-2 sentences.")
print("key present:", bool(key), "len", len(key or ""))
print("model:", model)

# grab a real frame via the local web API snapshot endpoint (no camera import needed)
import urllib.request as ur
try:
    jpeg = ur.urlopen("http://127.0.0.1:8080/snapshot", timeout=5).read()
except Exception as e:
    print("snapshot fetch failed:", e)
    jpeg = b""
print("jpeg bytes:", len(jpeg))

def call(extra_gen_config, max_tokens, label):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    parts = [{"text": prompt}]
    if jpeg:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}})
    gen_cfg = {"maxOutputTokens": max_tokens}
    gen_cfg.update(extra_gen_config)
    payload = {"contents": [{"parts": parts}], "generationConfig": gen_cfg}
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
        try:
            text = cand["content"]["parts"][0]["text"]
        except Exception:
            text = f"<no text; finishReason={cand.get('finishReason')}>"
        print(f"\n== {label} == elapsed={dt:.0f}ms finishReason={cand.get('finishReason')}")
        print("usage:", usage)
        print("text:", text[:300])
    except urllib.error.HTTPError as e:
        dt = (time.monotonic() - t0) * 1000
        body = e.read().decode(errors="replace")[:300]
        print(f"\n== {label} == elapsed={dt:.0f}ms HTTP {e.code}: {body}")
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        print(f"\n== {label} == elapsed={dt:.0f}ms ERROR: {e}")

call({}, 1024, "current (no thinkingConfig, max=1024)")
call({"thinkingConfig": {"thinkingBudget": 0}}, 1024, "thinkingBudget=0, max=1024")
call({"thinkingConfig": {"thinkingBudget": 0}}, 200, "thinkingBudget=0, max=200")
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_probe_thinking_remote.py", "w") as f:
    f.write(dev)
sftp.close()

p(sh("python3 /tmp/_probe_thinking_remote.py", t=90))
p(sh("rm -f /tmp/_probe_thinking_remote.py; echo done"))

c.close()
