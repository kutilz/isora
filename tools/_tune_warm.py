"""Bump warm rate live and run several describes on a STEADY scene to confirm a
real WORD-CACHE HIT fires. Diagnoses which words are still missing. Scratch."""
import re, time, paramiko
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
def sh(cmd, t=35):
    try:
        _i, o, e = c.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")
    except Exception as ex:
        return f"<err {type(ex).__name__}>"
def p(s): print(s.encode("ascii", "replace").decode())

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""

tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
def post(path, payload):
    return sh(tokget + f"; wget -qO- --post-data='{payload}' --header=\"X-Auth-Token: $T\" "
              f"--header='Content-Type: application/json' http://127.0.0.1:8080{path}; echo")

# live tune: warm a whole short sentence per describe, faster
p("tune: " + post("/config", '{"word_warm_per_call":16,"word_warm_gap_s":0.2,"scene_verbosity":"sedang"}').strip())
post("/command", '{"cmd":"set_mode","mode":"context"}')
time.sleep(6)

def last_scene():
    line = sh(f"grep '\"msg\": \"Scene:' {logf} | tail -1")
    mm = re.search(r'Scene: (.*?)"\}', line)
    return mm.group(1) if mm else "(none)"

for n in range(1, 7):
    post("/command", '{"cmd":"describe"}')
    time.sleep(30)   # give the warm thread time to finish the sentence
    txt = last_scene()
    recent = sh(f"tail -n 50 {logf}")
    hit = "HIT" if "WORD-CACHE HIT" in recent else "-"
    files = sh("ls /root/audio/word_cache/*.pcm 2>/dev/null | wc -l").strip()
    p(f"#{n} cache={hit} files={files} words={len(txt.split())} | {txt[:85]}")

# diagnose missing words of the final sentence
txt = last_scene()
dev_py = (
    "import sys; sys.path.insert(0,'/root/isora');"
    "from utils.word_cache import WordCache, tokenize;"
    "wc=WordCache('/root/audio/word_cache');"
    f"ws=tokenize({txt!r});"
    "miss=[w for w in ws if wc.lookup(w) is None];"
    "print('words:', ws); print('MISSING:', miss)"
)
p("\n-- final sentence cache check --")
p(sh('python3 -c "' + dev_py.replace('"', '\\"') + '"'))
c.close()
