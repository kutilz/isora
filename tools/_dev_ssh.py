"""Scratch SSH helper for I-Sora device dev work. Single persistent connection,
retry-with-backoff connect (boot/load storms drop the banner otherwise).
Delete when done."""
import time
import paramiko

HOST = "10.183.223.1"
USER = "root"
PASS = "root"
APP_DIR = "/root/isora"


def connect(retries=6, backoff=2.0):
    last = None
    for i in range(retries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username=USER, password=PASS, timeout=10,
                      banner_timeout=20, auth_timeout=15, look_for_keys=False,
                      allow_agent=False)
            return c
        except Exception as e:  # noqa
            last = e
            time.sleep(backoff * (i + 1))
    raise SystemExit(f"connect failed after {retries}: {last}")


def run(c, cmd, timeout=30):
    _in, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return o, e
