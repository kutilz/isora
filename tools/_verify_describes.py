"""App already running new code. Switch to context, run several describes,
watch word-cache warm -> HIT and confirm playback fix. Tolerant of slow
commands under boot load. Scratch — delete."""
import time, re, paramiko
import _dev_ssh as d


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
def sh(cmd, t=30):
    try:
        _i, o, e = c.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")
    except Exception as ex:
        return f"<err {type(ex).__name__}>"
def p(s): print(s.encode("ascii", "replace").decode())

# let load settle a touch
for _ in range(10):
    la = sh("cat /proc/loadavg").split()
    if la and float(la[0]) < 10:
        break
    time.sleep(5)
p("load now: " + sh("cat /proc/loadavg").strip())

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""
p("pid " + pid + "  log " + logf)

tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
def cmd(payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' --header=\"X-Auth-Token: $T\" "
              "--header='Content-Type: application/json' http://127.0.0.1:8080/command; echo")

cmd('{"cmd":"set_mode","mode":"context"}')
time.sleep(6)
p("mode: " + sh("wget -qO- http://127.0.0.1:8080/status | sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

for n in range(1, 7):
    p(f"\n===== DESCRIBE #{n} =====")
    cmd('{"cmd":"describe"}')
    time.sleep(27)
    p("word_cache .pcm files: " + sh("ls /root/audio/word_cache/*.pcm 2>/dev/null | wc -l").strip())
    if logf:
        p(san := sh(f"grep -E 'WORD-CACHE HIT|scene-timing\\] total|play END|play\\(\\) blocked|Scene:' {logf} | tail -6").encode("ascii", "replace").decode())

c.close()
