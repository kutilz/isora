"""Restart device (busybox-safe), switch to context mode, fire a real scene
describe, and dump the [scene-timing] ground-truth log lines. Scratch — delete."""
import time
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=30):
    o, e = d.run(c, cmd, timeout=t)
    return (o or "") + (e or "")


print("=== 1. graceful TERM ===")
print(sh("kill -TERM $(pidof python3) 2>/dev/null; echo sent").strip())

print("=== 2. wait for pidof empty (busybox-safe, never -9) ===")
for i in range(20):
    p = sh("pidof python3").strip()
    if not p:
        print(f"  clear after {i}s")
        break
    time.sleep(1)
else:
    print("  STILL ALIVE:", p, "-- aborting (won't double-instance)")
    c.close()
    raise SystemExit(1)

print("=== 3. detached relaunch (exact rc.local line) ===")
sh("setsid sh -c 'nohup python3 /root/isora/main.py >> /tmp/isora_main.log 2>&1 &' "
   "</dev/null >/dev/null 2>&1; echo launched")
time.sleep(1)
print("  new pid:", sh("pidof python3").strip())

print("=== 4. wait for web :8080 ===")
up = False
for i in range(45):
    s = sh("wget -qO- http://127.0.0.1:8080/status 2>/dev/null | head -c 80")
    if "mode" in s:
        print(f"  web up after ~{i}s: {s[:80]}")
        up = True
        break
    time.sleep(1)
if not up:
    print("  web never came up; recent log:")
    print(sh("tail -n 30 /tmp/isora_main.log"))
    c.close()
    raise SystemExit(1)

print("=== 5. switch to context mode + wait for a frame ===")
token_get = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
             "sed 's/.*\"token\": *\"//;s/\".*//')")
sh(token_get + "; wget -qO- --post-data='{\"cmd\":\"set_mode\",\"mode\":\"context\"}' "
   "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
   "http://127.0.0.1:8080/command; echo")
time.sleep(8)  # let mode settle + camera produce frames
print("  mode now:", sh("wget -qO- http://127.0.0.1:8080/status | sed 's/.*\"mode\": *\"//;s/\".*//'").strip())

print("=== 6. trigger describe ===")
print(sh(token_get + "; wget -qO- --post-data='{\"cmd\":\"describe\"}' "
         "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
         "http://127.0.0.1:8080/command; echo").strip())

print("=== 7. wait for pipeline + dump [scene-timing] ===")
time.sleep(22)
print(sh("grep -h 'scene-timing' /tmp/isora_main.log /root/logs/*.log 2>/dev/null | tail -n 40"))
print("=== also: last Scene line ===")
print(sh("grep -h 'Scene:' /tmp/isora_main.log 2>/dev/null | tail -n 2"))
c.close()
