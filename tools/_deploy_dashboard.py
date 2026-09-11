"""Deploy the /buttons redesign + latency-metrics backend in ONE graceful restart,
then verify the new /status fields and the new page are served. No describe spam
(avoid load on the 1-core box). Scratch — delete when done."""
import os
import time
import paramiko
import _dev_ssh as d

FILES = [
    ("utils/scene_metrics.py", "/root/isora/utils/scene_metrics.py"),
    ("utils/word_cache.py",    "/root/isora/utils/word_cache.py"),
    ("core/audio_manager.py",  "/root/isora/core/audio_manager.py"),
    ("core/ai_engine.py",      "/root/isora/core/ai_engine.py"),
    ("core/orchestrator.py",   "/root/isora/core/orchestrator.py"),
    ("server/web_server.py",   "/root/isora/server/web_server.py"),
    ("server/static/buttons.html", "/root/isora/server/static/buttons.html"),
]
BASE = r"C:\Users\Ilyas\Documents\isora\device"


def patient_connect(tries=10):
    last = None
    for i in range(tries):
        try:
            cc = paramiko.SSHClient(); cc.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            cc.connect(d.HOST, username=d.USER, password=d.PASS, timeout=15,
                       banner_timeout=40, auth_timeout=25, look_for_keys=False, allow_agent=False)
            return cc
        except Exception as e:
            last = e; time.sleep(8)
    raise SystemExit(f"unreachable: {last}")


c = patient_connect()
def sh(cmd, t=35):
    try:
        _i, o, e = c.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")
    except Exception as ex:
        return f"<err {type(ex).__name__}>"
def p(s): print(s.encode("ascii", "replace").decode())

p("uptime: " + sh("uptime").strip())

sftp = c.open_sftp()
for loc, rem in FILES:
    sftp.put(os.path.join(BASE, *loc.split("/")), rem)
sftp.close()
p("deployed: " + ", ".join(os.path.basename(r) for _, r in FILES))

comp = sh("cd /root/isora && for f in utils/scene_metrics.py utils/word_cache.py "
          "core/audio_manager.py core/ai_engine.py core/orchestrator.py server/web_server.py; do "
          "python3 -m py_compile $f && echo ok || echo FAIL=$f; done")
if "FAIL" in comp:
    p("compile FAIL:\n" + comp); c.close(); raise SystemExit(1)
p("py_compile ok")

# One graceful restart (SIGTERM → wait pid clear → relaunch via setsid nohup).
sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(20):
    if not sh("pidof python3").strip():
        p(f"pid clear @{i}s"); break
    time.sleep(1)
sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
up = False
for i in range(55):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 60"):
        p(f"web up @{i}s"); up = True; break
    time.sleep(1)
if not up:
    p("web did NOT come up; tail main log:"); p(sh("tail -n 25 /tmp/isora_main.log")); c.close(); raise SystemExit(1)

# Verify the new /status fields are present + JSON-valid.
chk = '''
import json,urllib.request
s=json.load(urllib.request.urlopen("http://127.0.0.1:8080/status",timeout=8))
sm=s.get("scene_metrics") or {}
print("word_cache_enabled=", s.get("word_cache_enabled"))
print("word_cache_gap_ms =", s.get("word_cache_gap_ms"))
print("cached_words_total=", s.get("cached_words_total"))
print("scene_metrics keys=", sorted(sm.keys()))
print("summary=", (sm.get("summary") or {}))
'''
p("\n-- /status new fields --")
p(sh('python3 -c ' + repr(chk)))

# Confirm the redesigned page is actually served (tokens.css link + new markers).
page = sh("wget -qO- http://127.0.0.1:8080/buttons")
markers = ['/tokens.css', 'Mode suara deskripsi', 'Jarak antar kata',
           'Latensi deskripsi', 'setCacheMode', 'commitGap']
miss = [m for m in markers if m not in page]
p("\n-- /buttons page --")
p("served bytes: %d" % len(page))
p("all markers present" if not miss else "MISSING markers: %s" % miss)

# Confirm gap-clamp validation works (post out-of-range, expect clamp to -60).
tokget = ('T=$(wget -qO- http://127.0.0.1:8080/auth/token | '
          "sed 's/.*\"token\": *\"//;s/\".*//')")
def post(path, payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' --header=\"X-Auth-Token: $T\" "
              f"--header='Content-Type: application/json' http://127.0.0.1:8080{path}; echo")
p("\n-- config validation --")
p("post gap=-999 -> " + post("/config", '{"word_cache_gap_ms":-999}').strip())
p("gap now = " + sh('python3 -c \'import json,urllib.request;'
                    'print(json.load(urllib.request.urlopen("http://127.0.0.1:8080/status",timeout=8))["word_cache_gap_ms"])\'').strip())
# restore a sensible default
post("/config", '{"word_cache_gap_ms":-10}')

p("\n>>> READY. Open http://%s:8080/buttons — press Deskripsikan to populate the latency panel. <<<" % d.HOST)
c.close()
