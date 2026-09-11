"""Scratch: pull scene-timing + related lines from recent device logs. Delete when done."""
import _dev_ssh as d

c = d.connect()


def sh(cmd, t=30):
    o, e = d.run(c, cmd, t)
    return (o or "") + (e or "")


def p(s):
    print(s.encode("ascii", "replace").decode())


for f in ["isora_20260712_043642.log", "isora_20260712_050451.log"]:
    print("=====", f, "=====")
    out = sh(
        "grep -E 'scene-timing|Scene:|Sending frame|WORD-CACHE' "
        f"/root/logs/{f}"
    )
    p(out)

c.close()
