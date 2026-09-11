"""Reset openai_reasoning_effort to the config.py default ('low') so live
config matches code default after the test loop left it on 'medium'. Scratch,
delete."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=20):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


tokget = ("T=$(wget -qO- http://127.0.0.1:8080/auth/token | "
          "sed 's/.*\"token\": *\"//;s/\".*//')")
out = sh(tokget + "; wget -qO- --post-data='{\"openai_reasoning_effort\":\"low\"}' "
         "--header=\"X-Auth-Token: $T\" --header='Content-Type: application/json' "
         "http://127.0.0.1:8080/config; echo")
print(out)
c.close()
