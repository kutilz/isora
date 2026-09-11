"""Deploy verbosity toggle (config/orchestrator/web_server/buttons.html) in ONE
restart, then verify sedang->short / detail->long live, and watch cache HITs.
Scratch — delete."""
import os, re, time, paramiko
import _dev_ssh as d

FILES = [
    ("config.py",                   "/root/isora/config.py"),
    ("core/orchestrator.py",        "/root/isora/core/orchestrator.py"),
    ("server/web_server.py",        "/root/isora/server/web_server.py"),
    ("server/static/buttons.html",  "/root/isora/server/static/buttons.html"),
]
BASE = r"C:\Users\Ilyas\Documents\isora\device"


def patient_connect(tries=8):
    last = None
    for i in range(tries):
        try:
            cc = paramiko.SSHClient(); cc.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cc.connect(d.HOST, username=d.USER, password=d.PASS, timeout=12,
                       banner_timeout=30, auth_timeout=20, look_for_keys=False, allow_agent=False)
            return cc
        except Exception as e:
            last = e; time.sleep(7)
    raise SystemExit(f"unreachable: {last}")


c = patient_connect()
def sh(cmd, t=35):
    try:
        _i, o, e = c.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")
    except Exception as ex:
        return f"<err {type(ex).__name__}>"
def p(s): print(s.encode("ascii", "replace").decode())

sftp = c.open_sftp()
for loc, rem in FILES:
    sftp.put(os.path.join(BASE, *loc.split("/")), rem)
sftp.close()
p("deployed: " + ", ".join(f for f, _ in FILES))
comp = sh("cd /root/isora && for f in config.py core/orchestrator.py server/web_server.py; do "
          "python3 -m py_compile $f && echo \"ok $f\" || echo \"FAIL $f\"; done")
p(comp)
if "FAIL" in comp:
    p("compile failed — abort"); c.close(); raise SystemExit(1)

# ONE busybox-safe restart
sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(20):
    if not sh("pidof python3").strip():
        p(f"pid clear @{i}s"); break
    time.sleep(1)
sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
for i in range(55):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 40"):
        p(f"web up @{i}s"); break
    time.sleep(1)

p("status scene_verbosity field: " +
  sh("wget -qO- http://127.0.0.1:8080/status | grep -o '\"scene_verbosity\": *\"[a-z]*\"'").strip())

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""

tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
def post(path, payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' --header=\"X-Auth-Token: $T\" "
              f"--header='Content-Type: application/json' http://127.0.0.1:8080{path}; echo")

post("/command", '{"cmd":"set_mode","mode":"context"}')
time.sleep(6)

def last_scene():
    line = sh(f"grep '\"msg\": \"Scene:' {logf} | tail -1")
    msg = re.search(r'Scene: (.*?)"\}', line)
    txt = msg.group(1) if msg else "(none)"
    return txt, len(txt.split())

p("\n===== SEDANG (short) =====")
p("set: " + post("/config", '{"scene_verbosity":"sedang"}').strip())
for n in range(1, 5):
    post("/command", '{"cmd":"describe"}')
    time.sleep(26)
    txt, wc = last_scene()
    hit = "HIT" if "WORD-CACHE HIT" in sh(f"tail -n 40 {logf}") else "-"
    p(f"#{n} words={wc} cache={hit} files={sh('ls /root/audio/word_cache/*.pcm 2>/dev/null | wc -l').strip()}  | {txt[:90]}")

p("\n===== DETAIL (long) =====")
p("set: " + post("/config", '{"scene_verbosity":"detail"}').strip())
post("/command", '{"cmd":"describe"}')
time.sleep(26)
txt, wc = last_scene()
p(f"words={wc} | {txt[:120]}")

c.close()
