"""Deploy the structured scene-prompt pack, confirm the on-device config
migration fired, then fire repeated describes on an UNCHANGED scene to measure
wording consistency. Scratch, delete when done."""
import os
import re
import time
import json
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=60):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(str(s).encode("ascii", "replace").decode())


# ── deploy ──────────────────────────────────────────────────────────────────
base = r"C:\Users\Ilyas\Documents\isora\device"
files = [
    ("utils/scene_prompt.py",        "utils/scene_prompt.py"),
    ("config.py",                    "config.py"),
    ("utils/presets.py",             "utils/presets.py"),
    ("adapters/openai_adapter.py",   "adapters/openai_adapter.py"),
    ("adapters/gemini_adapter.py",   "adapters/gemini_adapter.py"),
    ("adapters/claude_adapter.py",   "adapters/claude_adapter.py"),
    ("core/cloud.py",                "core/cloud.py"),
    ("server/web_server.py",         "server/web_server.py"),
]
sftp = c.open_sftp()
for local, remote in files:
    sftp.put(os.path.join(base, local.replace("/", os.sep)),
             "/root/isora/" + remote)
    p("  put " + remote)
sftp.close()
sh("rm -rf /root/isora/__pycache__ /root/isora/utils/__pycache__ "
   "/root/isora/adapters/__pycache__ /root/isora/core/__pycache__ "
   "/root/isora/server/__pycache__; echo x")
p("deployed + pycache cleared")

# ── dev-only: force the migration to re-run ─────────────────────────────────
# While the pack is still being iterated on, the version number has not shipped
# to anyone, so bumping it (and growing the legacy table with a 4 KB literal)
# would be bookkeeping for nobody. Dropping the three keys makes _load treat
# this unit as un-migrated and re-apply whatever the pack currently says.
# Never do this on a unit whose prompt an operator may have edited.
if os.environ.get("DEV_RESET") == "1":
    sh("python3 -c \"import json;p='/root/config.json';d=json.load(open(p));"
       "[d.pop(k,None) for k in ('prompt_scene','prompt_scene_sedang',"
       "'prompt_pack_version')];json.dump(d,open(p,'w'),indent=2)\"; echo reset")
    p("DEV_RESET: prompt keys dropped, migration will re-run")

# ── config BEFORE ───────────────────────────────────────────────────────────
before = sh("head -c 200 /root/config.json > /dev/null; "
            "grep -c prompt_pack_version /root/config.json || echo 0").strip()
p("prompt_pack_version present before restart: " + before)

# ── busybox-safe restart ────────────────────────────────────────────────────
sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(20):
    if not sh("pidof python3").strip():
        p("pid clear @%ds" % i)
        break
    time.sleep(1)
else:
    p("STILL ALIVE; abort")
    c.close()
    raise SystemExit(1)

sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
for i in range(60):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 40"):
        p("web up @%ds" % i)
        break
    time.sleep(1)
else:
    p("web never came up:")
    p(sh("tail -n 40 /tmp/isora_main.log"))
    c.close()
    raise SystemExit(1)

# ── did the migration land on disk? ─────────────────────────────────────────
raw = sh("cat /root/config.json")
try:
    cfg = json.loads(raw)
except Exception as e:
    p("config unreadable: %s" % e)
    cfg = {}
p("")
p("prompt_pack_version = %r" % cfg.get("prompt_pack_version"))
p("ai_temperature      = %r" % cfg.get("ai_temperature"))
ps = cfg.get("prompt_scene", "")
p("prompt_scene len    = %d" % len(ps))
p("  has ladder        = %s" % ("URUTAN PRIORITAS" in ps))
p("  has held-object   = %s" % ("BENDA YANG DIPEGANG" in ps))
p("  has environments  = %s" % ("LINGKUNGAN" in ps))
p("  has consistency   = %s" % ("persis sama" in ps))

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)",
               sh("ls -l /proc/%s/fd 2>/dev/null | grep logs" % pid))
logf = m[0] if m else ""
p("log: " + logf)

# ── consistency probe: N describes, scene untouched ─────────────────────────
tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")


def cmd(payload):
    return sh(tokget + (" ; wget -qO- --post-data='%s' " % payload) +
              "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
              "http://127.0.0.1:8080/command; echo")


cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
p("mode: " + sh("wget -qO- http://127.0.0.1:8080/status | "
                "sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

RUNS = int(os.environ.get("RUNS", "3"))
for n in range(1, RUNS + 1):
    p("\n===== DESCRIBE #%d =====" % n)
    cmd('{"cmd":"describe"}')
    time.sleep(20)
    p(sh("grep -E 'Scene:|scene-timing' %s | tail -n 2" % logf))

p("\n===== ALL SCENE LINES THIS RUN =====")
p(sh("grep 'Scene:' %s | tail -n %d" % (logf, RUNS)))

c.close()
