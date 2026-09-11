import sys, re, glob, os
sys.path.insert(0, "/root/isora")
from utils.word_cache import WordCache, tokenize, plan_utterance

wc = WordCache("/root/audio/word_cache")

# newest log by mtime among the 2026-named files the running app writes
logs = glob.glob("/root/logs/isora_*.log")
logs.sort(key=lambda p: os.path.getmtime(p))
logf = logs[-1] if logs else ""
print("LOG", logf)

scenes = []
for line in open(logf, encoding="utf-8", errors="replace"):
    mm = re.search(r'Scene: (.*?)"\}', line)
    if mm:
        scenes.append(mm.group(1))

print("CACHED", len(glob.glob("/root/audio/word_cache/*.pcm")))
for s in scenes[-8:]:
    ws = tokenize(s)
    miss = [w for w in ws if wc.lookup(w) is None]
    plan = plan_utterance(s, wc.lookup)
    print("plan=%-14s MISS=%d %s | %s" % (plan.mode, len(miss), miss, s[:55]))
