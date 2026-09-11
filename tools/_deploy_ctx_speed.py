"""Deploy audio_manager+config, restart, run N real describes, report timings."""
import os, re, sys, time, json
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=90):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


base = r"C:\Users\Ilyas\Documents\isora\device"
sftp = c.open_sftp()
for rel, dst in ((("core", "audio_manager.py"), "/root/isora/core/audio_manager.py"),
                 (("utils", "tts.py"), "/root/isora/utils/tts.py"),
                 (("core", "ai_engine.py"), "/root/isora/core/ai_engine.py"),
                 (("main.py",), "/root/isora/main.py"),
                 (("core", "orchestrator.py"), "/root/isora/core/orchestrator.py"),
                 (("server", "static", "buttons.html"), "/root/isora/server/static/buttons.html"),
                 (("server", "web_server.py"), "/root/isora/server/web_server.py"),
                 (("config.py",), "/root/isora/config.py")):
    sftp.put(os.path.join(base, *rel), dst)
    print("deployed", dst)
sftp.close()

sh("kill -TERM $(pidof python3) 2>/dev/null; echo x")
for i in range(25):
    if not sh("pidof python3").strip():
        print("pid clear @%ds" % i); break
    time.sleep(1)
sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo x")
for i in range(60):
    if "mode" in sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 40"):
        print("web up @%ds" % i); break
    time.sleep(1)

pid = sh("pidof python3").strip().split()[0]
m = re.findall(r"(/root/logs/\S+\.log)", sh("ls -l /proc/%s/fd 2>/dev/null | grep logs" % pid))
logf = m[0] if m else ""
print("log:", logf)
sftp = c.open_sftp()
sftp.put("_dev_drive.py", "/tmp/_dev_drive.py")
sftp.close()
p(sh("cd /root/isora && python3 /tmp/_dev_drive.py %s %s 2>&1" % (sys.argv[1] if len(sys.argv) > 1 else "3", logf), 400))
c.close()
