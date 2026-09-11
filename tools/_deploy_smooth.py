"""Deploy word-audio smoothing (trim + negative gap) in ONE restart, set sedang,
run steady describes to fire a HIT so the user can hear it. Scratch — delete."""
import os, re, time, paramiko
import _dev_ssh as d

FILES = [
    ("utils/word_cache.py",   "/root/isora/utils/word_cache.py"),
    ("core/audio_manager.py", "/root/isora/core/audio_manager.py"),
    ("config.py",             "/root/isora/config.py"),
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
comp = sh("cd /root/isora && for f in utils/word_cache.py core/audio_manager.py config.py; do "
          "python3 -m py_compile $f && echo ok || echo FAIL; done")
if "FAIL" in comp:
    p("compile FAIL"); c.close(); raise SystemExit(1)
p("py_compile ok")

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

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""

tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
def post(path, payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' --header=\"X-Auth-Token: $T\" "
              f"--header='Content-Type: application/json' http://127.0.0.1:8080{path}; echo")

post("/config", '{"scene_verbosity":"sedang"}')
post("/command", '{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
p("defaults now: " + sh("wget -qO- http://127.0.0.1:8080/status | grep -o '\"scene_verbosity\": *\"[a-z]*\"'").strip())

def last_scene():
    line = sh(f"grep '\"msg\": \"Scene:' {logf} | tail -1")
    mm = re.search(r'Scene: (.*?)"\}', line)
    return mm.group(1) if mm else "(none)"

for n in range(1, 6):
    post("/command", '{"cmd":"describe"}')
    time.sleep(30)
    recent = sh(f"tail -n 50 {logf}")
    hit = "HIT" if "WORD-CACHE HIT" in recent else "-"
    perr = "PLAY-ERR" if "Play error" in recent else ""
    p(f"#{n} cache={hit} {perr} | {last_scene()[:80]}")

c.close()
