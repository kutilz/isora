"""device/system/supervise.sh - keeps main.py running.

The app used to be started once with nohup: a SIGSEGV in NN load, the OOM
killer or a camera call wedged holding the GIL left the glasses silent until
someone pulled the power, which a blind user cannot diagnose and a demo cannot
afford. Driven here through the real script with a stub app, short timings and
a reboot command that only leaves a marker.
"""

import os
import pathlib
import shutil
import signal
import subprocess
import time

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "system" / "supervise.sh"
_SH = shutil.which("sh")
needs_sh = pytest.mark.skipif(
    _SH is None or not os.path.exists("/proc/uptime") and os.name != "nt",
    reason="needs a POSIX sh with /proc/uptime")


def test_script_is_lf_and_has_a_shebang():
    raw = _SCRIPT.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r\n" not in raw


@needs_sh
def test_script_parses():
    proc = subprocess.run([_SH, "-n", _SCRIPT.as_posix()], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_release_switch_runs_before_every_start():
    s = _SCRIPT.read_text()
    loop = s[s.index("while [ ! -e \"$STOP\" ]"):]
    assert loop.index('python3 "$H" boot') < loop.index("exec $APP_CMD")
    assert 'python3 "$H" guard' in loop


class _Rig:
    """One supervisor run in a scratch dir. The stub app is a shell script
    that counts its starts in `starts` and then does what `plan` says for
    that start number (the last entry repeats)."""

    def __init__(self, tmp: pathlib.Path, plan, **env):
        self.tmp = tmp
        self.run = tmp / "run"
        self.state = tmp / "state"
        self.app = tmp / "app"
        for d in (self.run, self.state, self.app):
            d.mkdir()
        (self.app / "main.py").write_text("")
        cases = "\n".join(
            "  %d) %s ;;" % (i + 1, step) for i, step in enumerate(plan[:-1]))
        script = (
            "#!/bin/sh\n"
            "R=%s\n"
            "echo x >> \"$R/starts\"\n"
            "n=$(wc -l < \"$R/starts\" | tr -dc 0-9)\n"
            "case $n in\n%s\n  *) %s ;;\nesac\n"
        ) % (self.tmp.as_posix(), cases, plan[-1])
        stub = tmp / "stub.sh"
        stub.write_bytes(script.encode())
        self.env = dict(os.environ)
        self.env.update({
            "ISORA_RUN": self.run.as_posix(),
            "ISORA_STATE": self.state.as_posix(),
            "ISORA_APP_DIR": self.app.as_posix(),
            "ISORA_APP_CMD": "sh %s" % stub.as_posix(),
            "ISORA_HELPER": (tmp / "no-helper").as_posix(),
            "ISORA_REBOOT_CMD": "touch %s" % (tmp / "rebooted").as_posix(),
            "ISORA_POLL_S": "1",
            "ISORA_STALE_S": "2",
            "ISORA_GRACE_S": "60",
            "ISORA_HEALTHY_S": "100",
            "ISORA_DELAYS": "1 1 1",
        })
        self.env.update(env)
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([_SH, _SCRIPT.as_posix()], env=self.env,
                                     stdin=subprocess.DEVNULL)
        return self

    def wait(self, timeout=30):
        return self.proc.wait(timeout=timeout)

    def starts(self):
        p = self.tmp / "starts"
        return len(p.read_text().splitlines()) if p.exists() else 0

    def until(self, cond, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.2)
        return False

    def log(self):
        p = self.run / "isora_main.log"
        return p.read_text() if p.exists() else ""

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(plan, **env):
        r = _Rig(tmp_path, plan, **env)
        made.append(r)
        return r
    yield make
    for r in made:
        r.stop()


# A start that writes its heartbeat once and then hangs, like a wedged app.
_BEAT_THEN_HANG = "cut -d. -f1 /proc/uptime > \"$ISORA_RUN/isora_alive\"; exec sleep 300"


@needs_sh
def test_a_crash_is_restarted(rig):
    r = rig(["exit 1", "exit 0"]).start()
    assert r.wait() == 0
    assert r.starts() == 2
    assert "app died (exit 1" in r.log()


@needs_sh
@pytest.mark.parametrize("rc", ["0", "130", "143"])
def test_a_deliberate_exit_is_not_restarted(rig, rc):
    # exit 0 = main.py caught SIGTERM and shut down; 130/143 = SIGINT/SIGTERM
    # before the handler was installed. All are someone stopping it on purpose.
    r = rig(["exit %s" % rc]).start()
    assert r.wait() == 0
    assert r.starts() == 1
    assert "not a crash" in r.log()


@needs_sh
def test_a_wedged_app_is_killed_and_started_again(rig):
    r = rig([_BEAT_THEN_HANG, "exit 0"]).start()
    assert r.wait() == 0
    assert r.starts() == 2
    assert "app wedged (no heartbeat" in r.log()


@needs_sh
def test_an_app_that_never_beats_is_killed_after_the_grace(rig):
    r = rig(["exec sleep 300", "exit 0"], ISORA_GRACE_S="2").start()
    assert r.wait() == 0
    assert r.starts() == 2
    assert "no heartbeat 2s after start" in r.log()


@needs_sh
def test_a_shutdown_in_progress_is_not_taken_for_a_wedge(rig):
    # main.py writes isora_stopping before releasing the camera; a slow release
    # must not be SIGKILLed (that is what leaks the VI channel).
    hang_while_stopping = ("touch \"$ISORA_RUN/isora_stopping\"; sleep 6; exit 0")
    # Grace 3 s, not 1: on a loaded Windows box the stub's own startup (MSYS
    # forks) can outlast 1 s before the touch, which is a slow test, not a wedge.
    r = rig([hang_while_stopping], ISORA_GRACE_S="3").start()
    assert r.wait() == 0
    assert r.starts() == 1
    assert "wedged" not in r.log()


@needs_sh
def test_repeated_failures_reboot_once_and_only_once(rig):
    r = rig(["exit 1"]).start()
    assert r.until(lambda: (r.tmp / "rebooted").exists())
    assert (r.state / ".isora_autoreboot").exists()
    (r.tmp / "rebooted").unlink()
    # Still failing after the reboot "happened": it must not reboot again.
    n = r.starts()
    assert r.until(lambda: r.starts() >= n + 3)
    assert not (r.tmp / "rebooted").exists()
    assert "already did since the last healthy run" in r.log()


@needs_sh
def test_a_healthy_run_rearms_the_reboot(rig):
    beat_loop = ("i=0; while [ $i -lt 6 ]; do cut -d. -f1 /proc/uptime > "
                 "\"$ISORA_RUN/isora_alive\"; sleep 1; i=$((i+1)); done; exit 0")
    # Stale threshold well above the beat: forks are slow on a loaded PC.
    r = rig([beat_loop], ISORA_HEALTHY_S="2", ISORA_STALE_S="10")
    (r.state / ".isora_autoreboot").write_text("earlier\n")
    r.start()
    assert r.wait() == 0
    assert not (r.state / ".isora_autoreboot").exists()


@needs_sh
@pytest.mark.skipif(os.name == "nt", reason="SIGTERM to an MSYS sh from Python is not delivered as a trap")
def test_term_during_backoff_ends_at_once_without_another_start(rig):
    # S26isoraapp stop kills the supervisor. If it only noticed after its
    # backoff sleep, a `restart` could start a second supervisor meanwhile.
    r = rig(["exit 1"], ISORA_DELAYS="20 20 20").start()
    assert r.until(lambda: "restarting in 20s" in r.log())
    t = time.monotonic()
    r.proc.send_signal(signal.SIGTERM)
    r.wait(timeout=5)
    assert time.monotonic() - t < 3
    time.sleep(1)
    assert r.starts() == 1
