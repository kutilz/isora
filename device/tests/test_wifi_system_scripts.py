"""The WiFi helpers in device/system/ — run for real under a POSIX sh.

Why this exists
---------------
udhcpc never notices when wpa_supplicant moves to another network: a device
that roamed from the router to a phone hotspot kept the router's IP and
gateway, looked "connected", and had no internet until it was rebooted. The
fix is a wpa_cli action script (wifi_roam.sh) that renews the lease. It first
lived only on two units, hand-installed; this test pins its behaviour now that
the repo is the source of truth.

The interesting decisions are all about WHEN to renew:
  * different access point  → release + renew (the original bug)
  * same access point again → keep the lease (a weak-signal blip must not cut
                               every open connection for nothing)
  * no IP yet               → leave the boot-time DISCOVER alone, but restart
                               udhcpc if it has died
Each case is driven through the real script with stub wpa_cli / ip / udhcpc.
"""

import os
import pathlib
import shutil
import subprocess
import textwrap

import pytest

_SYSTEM = pathlib.Path(__file__).resolve().parent.parent / "system"
_SCRIPTS = ["wifi_roam.sh", "wifi_prefer.sh", "S31wifiroam"]
_SH = shutil.which("sh")
# Resolved before any test puts its stub `sleep` first on PATH.
_REAL_SLEEP = pathlib.Path(shutil.which("sleep") or "/bin/sleep").as_posix()

needs_sh = pytest.mark.skipif(_SH is None, reason="no POSIX sh on this machine")


@pytest.mark.parametrize("name", _SCRIPTS)
def test_script_is_lf_and_has_a_shebang(name):
    """A CRLF checkout turns '#!/bin/sh' into '#!/bin/sh\\r' — nothing would start."""
    raw = (_SYSTEM / name).read_bytes()
    assert raw.startswith(b"#!/bin/sh\n")
    assert b"\r\n" not in raw


@needs_sh
@pytest.mark.parametrize("name", _SCRIPTS)
def test_script_parses(name):
    proc = subprocess.run([_SH, "-n", (_SYSTEM / name).as_posix()],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


class _Rig:
    """Stub binaries + a fake udhcpc that records the signals it receives."""

    def __init__(self, tmp: pathlib.Path):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.run = tmp / "run"
        self.bin.mkdir()
        self.run.mkdir()
        self.trace = tmp / "wifi_roam.trace"
        self.signals = tmp / "signals.log"
        self.started = tmp / "udhcpc_started.log"
        self.status = tmp / "wpa_status"
        self.has_ip = tmp / "has_ip"
        self._stub("wpa_cli", 'cat "%s"' % self.status.as_posix())
        self.gw_up = tmp / "gw_up"
        self._stub("ip", textwrap.dedent("""\
            case "$*" in
                *route*) echo "default via 10.0.0.1 dev wlan0" ;;
                *) [ -f "%s" ] && echo "    inet 10.0.0.5/24 scope global wlan0" ;;
            esac
            exit 0""" % self.has_ip.as_posix()))
        self._stub("ping", '[ -f "%s" ]' % self.gw_up.as_posix())
        self._stub("udhcpc", 'echo "$@" >> "%s"' % self.started.as_posix())
        self._stub("logger", "exit 0")
        # The hook's own `sleep 1` between release and renew, shortened: the
        # stub only has to keep the two signals in order, not take a second.
        self._stub("sleep", 'exec "%s" 0.1' % _REAL_SLEEP)
        self._stub("fake_udhcpc", textwrap.dedent("""\
            trap 'echo USR2 >> "%s"' USR2
            trap 'echo USR1 >> "%s"' USR1
            while :; do sleep 0.05; done
        """ % (self.signals.as_posix(), self.signals.as_posix())))

    def _stub(self, name, body):
        p = self.bin / name
        p.write_bytes(("#!/bin/sh\n" + body + "\n").encode())
        p.chmod(0o755)

    def associate(self, ssid, bssid, has_ip=True):
        self.status.write_text("bssid=%s\nssid=%s\nwpa_state=COMPLETED\n" % (bssid, ssid),
                               newline="\n")
        if has_ip:
            self.has_ip.write_text("1")
        elif self.has_ip.exists():
            self.has_ip.unlink()

    def fire(self, event="CONNECTED", udhcpc_running=True):
        """Run the hook once; returns the signals the fake udhcpc received."""
        if self.signals.exists():
            self.signals.unlink()
        pidf = (self.run / "udhcpc.wlan0.pid").as_posix()
        script = (_SYSTEM / "wifi_roam.sh").as_posix()
        if udhcpc_running:
            driver = textwrap.dedent("""\
                fake_udhcpc & echo $! > "{pidf}"
                "{sleep}" 0.3
                sh "{script}" wlan0 {event}
                "{sleep}" 0.3
                kill $(cat "{pidf}")
            """)
        else:
            driver = textwrap.dedent("""\
                echo 999999 > "{pidf}"
                sh "{script}" wlan0 {event}
                "{sleep}" 0.3
            """)
        env = dict(os.environ)
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["WIFI_ROAM_RUN"] = self.run.as_posix()
        env["WIFI_ROAM_TRACE"] = self.trace.as_posix()
        proc = subprocess.run([_SH, "-c", driver.format(pidf=pidf, script=script, event=event,
                                                     sleep=_REAL_SLEEP)],
                              env=env, capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        return self.signals.read_text().split() if self.signals.exists() else []

    def trace_lines(self):
        return self.trace.read_text().splitlines() if self.trace.exists() else []


@pytest.fixture
def rig(tmp_path):
    return _Rig(tmp_path)


@needs_sh
def test_roaming_to_another_access_point_renews_the_lease(rig):
    rig.associate("NETGEAR30", "94:18:65:77:9f:61")
    rig.fire()                                    # first sighting of the router
    rig.associate("Robot PTOIR", "52:6e:38:2c:ce:2f")
    assert rig.fire() == ["USR2", "USR1"], "old lease must be released, then renewed"
    assert "DHCP lease baru" in rig.trace_lines()[-1]


@needs_sh
def test_hotspot_named_like_the_router_still_renews(rig):
    """Same SSID, different BSSID: the case that started all of this."""
    rig.associate("NETGEAR30", "94:18:65:77:9f:61")
    rig.fire()
    rig.associate("NETGEAR30", "aa:bb:cc:dd:ee:ff")
    assert rig.fire() == ["USR2", "USR1"]


@needs_sh
def test_reconnecting_to_the_same_access_point_keeps_the_lease(rig):
    rig.associate("NETGEAR30", "94:18:65:77:9f:61")
    rig.fire()
    assert rig.fire() == [], "a blip on the same AP must not drop the IP"
    assert "AP sama" in rig.trace_lines()[-1]


@needs_sh
def test_boot_without_ip_leaves_the_running_udhcpc_alone(rig):
    rig.associate("NETGEAR30", "94:18:65:77:9f:61", has_ip=False)
    assert rig.fire() == []
    assert "belum ada IP" in rig.trace_lines()[-1]
    assert not rig.started.exists()


@needs_sh
def test_no_ip_and_dead_udhcpc_starts_a_new_one(rig):
    rig.associate("NETGEAR30", "94:18:65:77:9f:61", has_ip=False)
    rig.fire(udhcpc_running=False)
    assert rig.started.exists(), "nobody is asking for an address — start udhcpc"
    assert "-i wlan0" in rig.started.read_text()


@needs_sh
def test_first_event_with_an_ip_renews(rig):
    """No remembered AP and the lease's gateway is silent: be safe and renew."""
    rig.associate("NETGEAR30", "94:18:65:77:9f:61")
    assert rig.fire() == ["USR2", "USR1"]


@needs_sh
def test_first_event_keeps_a_lease_whose_gateway_answers(rig):
    """Boot: wpa_cli attaches seconds after S30wifi's udhcpc got its lease.
    Releasing that fresh lease left a unit with no IP for minutes on a hotspot."""
    rig.associate("Robot PTOIR", "52:6e:38:2c:ce:2f")
    rig.gw_up.write_text("1")
    assert rig.fire() == []
    assert "gateway 10.0.0.1 menjawab" in rig.trace_lines()[-1]
    assert rig.fire() == [], "and the next blip on that AP keeps it too"


@needs_sh
def test_disconnected_events_do_nothing(rig):
    rig.associate("NETGEAR30", "94:18:65:77:9f:61")
    assert rig.fire(event="DISCONNECTED") == []
    assert rig.trace_lines() == []


@needs_sh
def test_trace_stays_bounded(rig):
    rig.trace.write_text(("x" * 99 + "\n") * 2000)       # ~200 KB
    rig.associate("NETGEAR30", "94:18:65:77:9f:61")
    rig.fire()
    assert len(rig.trace_lines()) <= 200
    assert rig.trace.stat().st_size < 65536
