"""device/system/S03isoraclock - the wall clock kept across restarts.

The MaixCAM has no RTC battery: every boot starts in 1970 until NTP answers,
and until then HTTPS fails with "certificate is not yet valid", which the
device speaks as a connection failure. On 22 Oct 2026 that sent a user into
restart after restart on a phone hotspot. The script restores the last saved
time at boot and saves it while it is plausible. Driven here through the real
script with a stub `date`.
"""

import os
import pathlib
import shutil
import subprocess

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "system" / "S03isoraclock"
_SH = shutil.which("sh")
needs_sh = pytest.mark.skipif(_SH is None, reason="no POSIX sh on this machine")

UNSET = 18          # 1970, a few seconds after boot
NOW = 1792753768    # 23 Oct 2026
SAVED = 1792650000  # 22 Oct 2026


def test_script_is_lf_and_has_a_shebang():
    raw = _SCRIPT.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r\n" not in raw


@needs_sh
def test_script_parses():
    proc = subprocess.run([_SH, "-n", _SCRIPT.as_posix()], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


class _Rig:
    def __init__(self, tmp: pathlib.Path):
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.clock = tmp / "clock"          # what the stub `date +%s` prints
        self.set_log = tmp / "date_set.log" # every `date -s` the script runs
        self.file = tmp / "isora_clock"
        stub = self.bin / "date"
        stub.write_bytes((
            "#!/bin/sh\n"
            'if [ "$1" = "-s" ]; then echo "$2" >> "%s"; exit 0; fi\n'
            'cat "%s"\n' % (self.set_log.as_posix(), self.clock.as_posix())
        ).encode())
        stub.chmod(0o755)
        sync = self.bin / "sync"
        sync.write_bytes(b"#!/bin/sh\nexit 0\n")
        sync.chmod(0o755)

    def run(self, cmd, clock):
        self.clock.write_text("%d\n" % clock, newline="\n")
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["ISORA_CLOCK_FILE"] = self.file.as_posix()
        proc = subprocess.run([_SH, _SCRIPT.as_posix(), cmd], env=env,
                              capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr

    def sets(self):
        return self.set_log.read_text().split() if self.set_log.exists() else []


@pytest.fixture
def rig(tmp_path):
    return _Rig(tmp_path)


@needs_sh
def test_unset_clock_is_restored_from_the_saved_time(rig):
    rig.file.write_text("%d\n" % SAVED)
    rig.run("restore", UNSET)
    assert rig.sets() == ["@%d" % SAVED]


@needs_sh
def test_a_clock_that_is_already_set_is_left_alone(rig):
    rig.file.write_text("%d\n" % SAVED)
    rig.run("restore", NOW)
    assert rig.sets() == [], "never pull a synced clock back to an older save"


@needs_sh
@pytest.mark.parametrize("content", [None, "", "garbage\n", "18\n"])
def test_nothing_usable_saved_means_no_change(rig, content):
    if content is not None:
        rig.file.write_text(content)
    rig.run("restore", UNSET)
    assert rig.sets() == []


@needs_sh
def test_save_keeps_a_plausible_clock(rig):
    rig.run("save", NOW)
    assert rig.file.read_text().strip() == str(NOW)


@needs_sh
def test_save_ignores_an_unset_clock(rig):
    rig.file.write_text("%d\n" % SAVED)
    rig.run("save", UNSET)
    assert rig.file.read_text().strip() == str(SAVED), "1970 must never overwrite a real time"
