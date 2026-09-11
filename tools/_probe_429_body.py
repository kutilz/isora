"""What exactly is the 429 telling us (quota type, retry-after)? Scratch, delete."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=40):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = r'''
import sys, json, urllib.request as ur, urllib.error
sys.path.insert(0, "/root/isora")
from config import cfg

key = cfg.get("gemini_api_key", "") or cfg.GEMINI_API_KEY
model = cfg.get("gemini_model", "gemini-flash-latest")
url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
payload = json.dumps({"contents":[{"parts":[{"text":"Reply with exactly one word: OK"}]}],
                       "generationConfig":{"maxOutputTokens":5,"thinkingConfig":{"thinkingBudget":0}}}).encode()
req = ur.Request(url, data=payload, headers={"Content-Type":"application/json"}, method="POST")
try:
    with ur.urlopen(req, timeout=20) as r:
        print("OK", r.status, r.read()[:300])
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print("headers:", dict(e.headers))
    print("body:", e.read().decode(errors="replace")[:800])
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_p429.py", "w") as f:
    f.write(dev)
sftp.close()

p(sh("python3 /tmp/_p429.py", t=40))
p(sh("rm -f /tmp/_p429.py; echo done"))
c.close()
