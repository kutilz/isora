"""Deploy the button barge-in + detection back-off fix in ONE graceful restart,
then verify a simulated MODE press is accepted and acted on (mode cycles), and
restore explorer mode so the user lands back in the exact scenario they hit.
Scratch — delete when done."""
import os
import time
import paramiko
import _dev_ssh as d

FILES = [
    ("utils/detection_gate.py", "/root/isora/utils/detection_gate.py"),
    ("config.py",               "/root/isora/config.py"),
    ("core/audio_manager.py",   "/root/isora/core/audio_manager.py"),
    ("core/orchestrator.py",    "/root/isora/core/orchestrator.py"),
    ("modes/explorer_mode.py",  "/root/isora/modes/explorer_mode.py"),
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

comp = sh("cd /root/isora && for f in utils/detection_gate.py config.py "
          "core/audio_manager.py core/orchestrator.py modes/explorer_mode.py; do "
          "python3 -m py_compile $f && echo ok || echo FAIL=$f; done")
if "FAIL" in comp:
    p("compile FAIL:\n" + comp); c.close(); raise SystemExit(1)
p("py_compile ok")

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
    p("web did NOT come up; tail:"); p(sh("tail -n 25 /tmp/isora_main.log")); c.close(); raise SystemExit(1)


def status_field(field):
    return sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | "
              f"tr ',' '\\n' | grep -o '\"{field}\": *[^,}}]*' | head -1").strip()


# Confirm new config knobs are live.
cfgj = sh("wget -qO- http://127.0.0.1:8080/config 2>/dev/null | tr ',' '\\n' | "
          "grep -E 'detection_repeat_limit|detection_repeat_remind_s|detection_mute_after_interaction_s'")
p("\n-- new config knobs --\n" + cfgj.strip())

# Verify a simulated MODE press is ACCEPTED and ACTED ON (explorer -> context).
p("\n-- button responsiveness --")
p("mode before : " + status_field("mode"))
press = sh("wget -qO- --post-data='{\"button\":\"mode\",\"long\":false}' "
           "--header='Content-Type: application/json' http://127.0.0.1:8080/button; echo")
p("press /button: " + press.strip())
time.sleep(3)
p("mode after  : " + status_field("mode") + "   (expect context = press acted on)")

# Restore explorer so the user is back in the exact scenario they reported.
tokget = ('T=$(wget -qO- http://127.0.0.1:8080/auth/token | '
          "sed 's/.*\"token\": *\"//;s/\".*//')")
sh(tokget + "; wget -qO- --post-data='{\"cmd\":\"set_mode\",\"mode\":\"explorer\"}' "
   "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
   "http://127.0.0.1:8080/command; echo")
time.sleep(2)
p("mode restored: " + status_field("mode"))

# Show the recent log so we can see the barge-in / press handling.
pid = sh("pidof python3").strip()
logf = ""
for ln in sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs").splitlines():
    if "/root/logs/" in ln:
        logf = ln.split()[-1]; break
if logf:
    p("\n-- recent log (button/mode) --")
    p(sh(f"grep -E 'Simulated|Mode:|barge|user_press|mode_' {logf} | tail -8"))

p("\n>>> READY. Device in explorer. Press tombol di /buttons — sekarang langsung 'landing', spam 'orang di depan' auto-quiet setelah 3x. <<<")
c.close()
