"""Encrypt-at-rest an OpenAI API key on the device (mirrors set_api_key.py's
logic, run remotely since that script assumes it's executed ON the device).
Reads the key from env var OPENAI_TMP_KEY so it never touches disk locally.
Uploads a small script to /tmp on the device, runs it, deletes it. Scratch,
delete this file when done (it contains no secret itself)."""
import os
import sys
import _dev_ssh as d

key = os.environ.get("OPENAI_TMP_KEY", "").strip()
if not key:
    print("Set $env:OPENAI_TMP_KEY first.")
    sys.exit(1)

c = d.connect()


def sh(cmd, t=30):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


dev = '''
import sys, json
sys.path.insert(0, "/root/isora")
from utils.secure_keys import encrypt, decrypt

CONFIG_PATH = "/root/config.json"
with open(CONFIG_PATH) as f:
    data = json.load(f)

key = sys.stdin.readline().rstrip("\\n")
enc = encrypt(key)
if decrypt(enc) != key:
    print("ERROR: round-trip mismatch, aborting")
    sys.exit(2)

data["openai_api_key_enc"] = enc
data["openai_api_key"] = ""
with open(CONFIG_PATH, "w") as f:
    json.dump(data, f, indent=2)
print("OK: openai_api_key_enc stored (len=%d)" % len(enc))
'''

sftp = c.open_sftp()
with sftp.open("/tmp/_set_key_remote.py", "w") as f:
    f.write(dev)
sftp.close()

# Pipe the key over stdin (not argv, so it never shows in `ps`).
i, o, e = c.exec_command("python3 /tmp/_set_key_remote.py", timeout=20)
i.write(key + "\n")
i.flush()
i.channel.shutdown_write()
out = o.read().decode() + e.read().decode()
p(out)

p(sh("rm -f /tmp/_set_key_remote.py; echo cleaned"))

c.close()
