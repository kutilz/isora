"""MaixPy's UART comm listener is stopped at startup unless config keeps it.

`import maix` starts a native thread that polls UART0 for CommProtocol frames
~900 times a second. Nothing on this device speaks that protocol, and inside
the app the thread measured ~30% of the single core in idle — load that left
the WiFi driver starved. main._drop_maix_comm_listener removes it.
"""

import sys
import types

import main


class _Cfg(dict):
    pass


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, module=""):
        self.lines.append(("info", msg))

    def warn(self, msg, module=""):
        self.lines.append(("warn", msg))


def _fake_maix(monkeypatch, rm):
    comm = types.ModuleType("maix.comm")
    comm.rm_default_comm_listener = rm
    maix = types.ModuleType("maix")
    maix.comm = comm
    monkeypatch.setitem(sys.modules, "maix", maix)
    monkeypatch.setitem(sys.modules, "maix.comm", comm)


def test_listener_is_stopped_by_default(monkeypatch):
    calls = []
    _fake_maix(monkeypatch, lambda: calls.append("rm"))
    main._drop_maix_comm_listener(_Cfg(), _Log())
    assert calls == ["rm"]


def test_config_can_keep_the_listener(monkeypatch):
    calls = []
    _fake_maix(monkeypatch, lambda: calls.append("rm"))
    main._drop_maix_comm_listener(_Cfg(maix_comm_listener=True), _Log())
    assert calls == []


def test_a_maixpy_without_the_api_does_not_stop_boot(monkeypatch):
    def _boom():
        raise AttributeError("no such function")
    _fake_maix(monkeypatch, _boom)
    log = _Log()
    main._drop_maix_comm_listener(_Cfg(), log)
    assert log.lines and log.lines[0][0] == "warn"
