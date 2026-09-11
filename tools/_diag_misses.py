"""Why no HIT? For the last few scene sentences, show which exact words are
missing from the word cache. Gentle: one connection, two commands. Scratch."""
import re, time, paramiko
import _dev_ssh as d


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

pid = sh("pidof python3").strip()
m = re.findall(r"(/root/logs/\S+\.log)", sh(f"ls -l /proc/{pid}/fd 2>/dev/null | grep logs"))
logf = m[0] if m else ""
p("log: " + logf)
p("cached words total: " + sh("ls /root/audio/word_cache/*.pcm 2>/dev/null | wc -l").strip())
p("recent HIT/miss markers:")
p(sh(f"grep -E 'WORD-CACHE HIT' {logf} | tail -3") or "  (no HIT lines)")

dev = f'''
import sys, re
sys.path.insert(0, "/root/isora")
from utils.word_cache import WordCache, tokenize
wc = WordCache("/root/audio/word_cache")
scenes = []
for line in open("{logf}", encoding="utf-8", errors="replace"):
    mm = re.search(r'Scene: (.*?)"\\}}', line)
    if mm:
        scenes.append(mm.group(1))
for s in scenes[-6:]:
    ws = tokenize(s)
    miss = [w for w in ws if wc.lookup(w) is None]
    print("MISS", miss, "|", s[:70])
'''
p("\n-- last 6 sentences, missing words --")
p(sh('python3 -c ' + repr(dev)))
c.close()
