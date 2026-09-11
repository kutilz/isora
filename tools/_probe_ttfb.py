"""Break down a REAL generateContent call into connect/TLS/send/TTFB/body,
using raw sockets (not urllib) so we can see exactly when bytes start coming
back — isolates 'Google is slow to generate' from 'our upload/link is slow'.
Scratch, delete."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=90):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = r'''
import sys, socket, ssl, time, json, base64
sys.path.insert(0, "/root/isora")
import urllib.request as ur
from config import cfg

key = cfg.get("gemini_api_key", "") or cfg.GEMINI_API_KEY
model = cfg.get("gemini_model", "gemini-flash-latest")
prompt = cfg.get("prompt_scene", "Describe the scene in 1-2 sentences.")
HOST = "generativelanguage.googleapis.com"

jpeg = ur.urlopen("http://127.0.0.1:8080/snapshot", timeout=5).read()

parts = [{"text": prompt}, {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}]
payload = json.dumps({"contents": [{"parts": parts}],
                       "generationConfig": {"maxOutputTokens": 220,
                                             "thinkingConfig": {"thinkingBudget": 0}}}).encode()
path = f"/v1beta/models/{model}:generateContent?key={key}"

def run(n):
    t0 = time.monotonic()
    addrs = socket.getaddrinfo(HOST, 443, socket.AF_INET, socket.SOCK_STREAM)
    ip = addrs[0][4][0]
    t_dns = time.monotonic()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((ip, 443))
    t_tcp = time.monotonic()

    ctx = ssl.create_default_context()
    ssock = ctx.wrap_socket(sock, server_hostname=HOST)
    t_tls = time.monotonic()

    req = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + payload
    ssock.sendall(req)
    t_sent = time.monotonic()

    first = ssock.recv(1)
    t_first_byte = time.monotonic()

    body = [first]
    while True:
        chunk = ssock.recv(65536)
        if not chunk:
            break
        body.append(chunk)
    t_done = time.monotonic()
    ssock.close()

    raw = b"".join(body)
    print(f"run{n}: dns={(t_dns-t0)*1000:.0f}ms tcp={(t_tcp-t_dns)*1000:.0f}ms "
          f"tls={(t_tls-t_tcp)*1000:.0f}ms send={(t_sent-t_tls)*1000:.0f}ms "
          f"TTFB={(t_first_byte-t_sent)*1000:.0f}ms body_dl={(t_done-t_first_byte)*1000:.0f}ms "
          f"TOTAL={(t_done-t0)*1000:.0f}ms bytes={len(raw)}")
    # peek status line
    try:
        print("   status:", raw.split(b"\r\n", 1)[0])
    except Exception:
        pass

for i in range(3):
    try:
        run(i)
    except Exception as e:
        print("run", i, "FAILED:", e)
    time.sleep(3)
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_probe_ttfb_remote.py", "w") as f:
    f.write(dev)
sftp.close()

p(sh("python3 /tmp/_probe_ttfb_remote.py", t=150))
p(sh("rm -f /tmp/_probe_ttfb_remote.py; echo done"))

c.close()
