"""Decompose the 16s synth + 18.8s playback on-device: gTTS vs ffmpeg time, and
real mp3 duration vs the PCM byte-derived duration (sample-rate sanity).
Scratch — delete."""
import _dev_ssh as d

DEVICE_PY = r'''
import time, os, glob, subprocess, sys
sys.path.insert(0, "/root/isora")
cache = "/root/audio/tts_cache"

def mp3_dur(path):
    try:
        out = subprocess.run(["ffmpeg","-i",path], stderr=subprocess.PIPE,
                             stdout=subprocess.DEVNULL).stderr.decode("utf-8","replace")
        for line in out.splitlines():
            if "Duration" in line:
                return line.strip().split(",")[0]
    except Exception as e:
        return "err:%s" % e
    return "?"

# 1) inspect the most recent cached utterance from the real run
wavs = sorted(glob.glob(cache+"/*.wav"), key=os.path.getmtime)
if wavs:
    w = wavs[-1]
    p = os.path.splitext(w)[0]+".pcm"
    print("LAST wav:", os.path.basename(w), "bytes=", os.path.getsize(w))
    print("LAST mp3 real duration:", mp3_dur(w))
    if os.path.exists(p):
        b = os.path.getsize(p)
        print("LAST pcm bytes=", b, " claimed_dur_s(@48k)=", round(b/96000,2))

# 2) time a FRESH gTTS synth (unique text -> no cache hit) + ffmpeg convert
tok = str(int(time.time()))
text = "Ini kalimat uji untuk mengukur waktu sintesis suara nomor " + tok
try:
    from gtts import gTTS
    t0 = time.time()
    gTTS(text=text, lang="id", slow=False).save("/tmp/probe.mp3")
    g = time.time()-t0
    print("gTTS synth_s=", round(g,2), " mp3_bytes=", os.path.getsize("/tmp/probe.mp3"))
    print("probe mp3 real duration:", mp3_dur("/tmp/probe.mp3"))
    t0 = time.time()
    r = subprocess.run(["ffmpeg","-v","error","-y","-i","/tmp/probe.mp3",
                        "-f","s16le","-acodec","pcm_s16le","-ar","48000","-ac","1",
                        "/tmp/probe.pcm"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE)
    f = time.time()-t0
    pb = os.path.getsize("/tmp/probe.pcm") if os.path.exists("/tmp/probe.pcm") else -1
    print("ffmpeg convert_s=", round(f,2), " pcm_bytes=", pb,
          " claimed_dur_s(@48k)=", round(pb/96000,2) if pb>0 else "n/a")
    if r.stderr: print("ffmpeg err:", r.stderr.decode("utf-8","replace")[:200])
except Exception as e:
    print("PROBE ERROR:", e)
'''

c = d.connect()
# pass script via stdin to python3 to avoid quoting hell
chan = c.get_transport().open_session()
chan.exec_command("python3 -")
chan.sendall(DEVICE_PY.encode("utf-8"))
chan.shutdown_write()
out = b""
import time as _t
deadline = _t.time() + 90
while _t.time() < deadline:
    if chan.recv_ready():
        out += chan.recv(65536)
    if chan.exit_status_ready() and not chan.recv_ready():
        break
    _t.sleep(0.2)
out += chan.recv(65536) if chan.recv_ready() else b""
print(out.decode("utf-8", "replace").encode("ascii", "replace").decode())
c.close()
