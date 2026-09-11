"""Restore device to explorer mode after our context-mode latency testing.
Scratch, delete."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=20):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
out = sh(tokget + "; wget -qO- --post-data='{\"cmd\":\"set_mode\",\"mode\":\"explorer\"}' "
         "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
         "http://127.0.0.1:8080/command; echo")
print(out)
print(sh("wget -qO- http://127.0.0.1:8080/status | head -c 60"))
c.close()
