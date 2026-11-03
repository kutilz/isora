"""core/updater.py — download, verify and stage releases; switch only when quiet.

End to end where it counts: a real package is built and signed by
tools/release.py (with a throwaway key), served through a fake opener, and
staged by the Updater exactly as on the device. Everything that should make
the device refuse an update is tried against that same package.
"""

import base64
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import tarfile
import tempfile
import types

import pytest

from core import updater as up
from system import release as rel
from utils import release_sig

_TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools" / "release.py"
_SANE = 1.8e9                     # 2027 — past the clock-sanity floor


class _Log:
    def __init__(self):
        self.lines = []

    def __getattr__(self, level):
        return lambda msg, **k: self.lines.append((level, msg))


def _load_tools(monkeypatch, tmp_path, keypair):
    spec = importlib.util.spec_from_file_location("isora_tools_release", _TOOLS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    key_path = tmp_path / "key.json"
    key_path.write_text(json.dumps({"d": keypair[0], "pub": keypair[1]}))
    monkeypatch.setattr(mod, "KEY_PATH", str(key_path))
    monkeypatch.setattr(mod, "DIST", str(tmp_path / "dist"))
    monkeypatch.setattr(mod, "_device_pubkey", lambda: keypair[1])
    monkeypatch.setattr(mod, "_git", lambda *a: "")
    return mod


@pytest.fixture(scope="module")
def keypair():
    return release_sig.generate_keypair()


@pytest.fixture
def built(monkeypatch, tmp_path, keypair):
    """A real signed release of the current device/ tree, version 2026.11.1.1."""
    tools = _load_tools(monkeypatch, tmp_path, keypair)
    tools.cmd_build(types.SimpleNamespace(version="2026.11.1.1", allow_dirty=True))
    dist = pathlib.Path(tools.DIST)
    manifest = json.loads((dist / "isora-device.json").read_text())
    blob = (dist / manifest["file"]).read_bytes()
    return types.SimpleNamespace(manifest=manifest, blob=blob, pub=keypair[1])


class _Opener:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        if url not in self.routes:
            raise OSError("404 %s" % url)
        return io.BytesIO(self.routes[url])


def _unit(tmp_path, built, app_version="2026.10.1.1", opener=None, **kw):
    """An Updater wired to a temp /root: plain app dir, boot helper present."""
    root = tmp_path / "root"
    app = root / "isora"
    app.mkdir(parents=True)
    (app / "main.py").write_text("# running app\n")
    (app / "VERSION").write_text(app_version + "\n")
    helper = root / "release.py"
    helper.write_text("# helper\n")
    init = root / "S26isoraapp"
    init.write_text("case $1 in\n  restart)\n  ;;\nesac\n")
    opener = opener or _Opener({
        up.MANIFEST_URL: json.dumps(built.manifest).encode(),
        built.manifest["url"]: built.blob,
    })
    u = up.Updater(orchestrator=kw.pop("orch", types.SimpleNamespace(mode="idle")),
                   logger=_Log(), layout=rel.Layout(str(root)), opener=opener,
                   helper=str(helper), app_init=str(init), app_dir=str(app),
                   pubkey_b64=kw.pop("pubkey_b64", built.pub),
                   wall=kw.pop("wall", lambda: _SANE), **kw)
    return u, opener


# ─── the happy path ─────────────────────────────────────────────────────────

def test_package_contents(built):
    with tarfile.open(fileobj=io.BytesIO(built.blob), mode="r:gz") as tf:
        names = tf.getnames()
        assert tf.extractfile("VERSION").read() == b"2026.11.1.1\n"
        roam = tf.getmember("system/wifi_roam.sh")
        assert roam.mode & 0o111, "shell scripts must stay executable"
        assert b"\r\n" not in tf.extractfile(roam).read()
    assert "main.py" in names and "core/updater.py" in names
    assert not any(n.startswith("tests/") for n in names), "tests are not shipped"
    assert not any(n.startswith("server/src/") for n in names), "UI source is not shipped"
    assert not any(n.endswith(".pyc") for n in names)


def test_newer_release_is_staged_and_requested(tmp_path, built):
    u, opener = _unit(tmp_path, built)
    assert u.check_once() == "staged"
    target = pathlib.Path(u.L.release_dir("2026.11.1.1"))
    assert (target / "main.py").is_file()
    assert rel.read_version(str(target)) == "2026.11.1.1"
    assert rel._read(u.L.pending).strip() == "2026.11.1.1"
    assert not [n for n in os.listdir(u.L.releases) if n.startswith((".dl-", ".staging-"))]
    # Checking again does not download the package a second time.
    downloads = opener.calls.count(built.manifest["url"])
    assert u.check_once() == "staged"
    assert opener.calls.count(built.manifest["url"]) == downloads


def test_same_or_older_is_left_alone(tmp_path, built):
    u, opener = _unit(tmp_path, built, app_version="2026.11.1.1")
    assert u.check_once() == "up-to-date"
    assert built.manifest["url"] not in opener.calls


def test_dev_build_on_the_same_base_is_not_overwritten(tmp_path, built):
    u, _ = _unit(tmp_path, built, app_version="2026.11.1.1+dev.20261101T0900")
    assert u.check_once() == "up-to-date"


def test_known_bad_release_is_not_installed_again(tmp_path, built):
    u, opener = _unit(tmp_path, built)
    os.makedirs(u.L.releases)
    rel.atomic_write(u.L.bad, "2026.11.1.1\n")
    assert u.check_once() == "known-bad"
    assert built.manifest["url"] not in opener.calls


# ─── refusing ───────────────────────────────────────────────────────────────

def test_nothing_happens_without_the_boot_helper(tmp_path, built):
    u, opener = _unit(tmp_path, built)
    os.unlink(u.helper)
    assert u.check_once() == "no-boot-helper"
    assert opener.calls == []


def test_waits_for_a_real_clock(tmp_path, built):
    u, opener = _unit(tmp_path, built, wall=lambda: 1000.0)
    assert u.check_once() == "clock-not-set"
    assert opener.calls == []


def test_can_be_switched_off(tmp_path, built, monkeypatch):
    u, opener = _unit(tmp_path, built)
    monkeypatch.setattr(up.Updater, "_cfg", staticmethod(
        lambda k, d: False if k == "auto_update" else d))
    assert u.check_once() == "disabled"


def test_manifest_signed_by_someone_else_is_refused(tmp_path, built):
    _, other = release_sig.generate_keypair()
    u, _ = _unit(tmp_path, built, pubkey_b64=other)
    with pytest.raises(up.UpdateError, match="signature"):
        u.check_once()
    assert not os.path.exists(u.L.pending)


def test_swapped_tarball_is_refused_and_leaves_nothing(tmp_path, built):
    evil = bytearray(built.blob)
    evil[-10] ^= 0xFF
    opener = _Opener({up.MANIFEST_URL: json.dumps(built.manifest).encode(),
                      built.manifest["url"]: bytes(evil)})
    u, _ = _unit(tmp_path, built, opener=opener)
    with pytest.raises(up.UpdateError, match="hash"):
        u.check_once()
    assert not os.path.exists(u.L.pending)
    assert not os.path.exists(u.L.release_dir("2026.11.1.1"))
    assert [n for n in os.listdir(u.L.releases) if n != "last_check"] == []


def test_oversized_download_is_cut_off(tmp_path, built):
    opener = _Opener({up.MANIFEST_URL: json.dumps(built.manifest).encode(),
                      built.manifest["url"]: built.blob + b"x" * 200000})
    u, _ = _unit(tmp_path, built, opener=opener)
    with pytest.raises(up.UpdateError, match="larger"):
        u.check_once()


@pytest.mark.parametrize("field,value", [
    ("format", 2), ("version", "../../etc"), ("url", "http://example.com/x.tgz"),
    ("size", 10 ** 9), ("sha256", "zz" * 32), ("sig", "!!notbase64"),
])
def test_malformed_manifests_are_refused(built, field, value):
    m = dict(built.manifest)
    m[field] = value
    with pytest.raises(up.UpdateError):
        up.check_manifest(m, built.pub)


def test_unsigned_size_change_is_refused(built):
    m = dict(built.manifest, size=built.manifest["size"] + 1)
    with pytest.raises(up.UpdateError, match="signature"):
        up.check_manifest(m, built.pub)


# ─── safe_extract ───────────────────────────────────────────────────────────

def _tar(tmp_path, members):
    path = tmp_path / "pkg.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    return str(path)


def _file(name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    return info, data


@pytest.mark.parametrize("name", ["../evil.py", "core/../../evil.py", "/etc/passwd"])
def test_paths_outside_the_package_are_refused(tmp_path, name):
    tar = _tar(tmp_path, [_file("main.py"), _file(name)])
    with pytest.raises(up.UpdateError):
        up.safe_extract(tar, str(tmp_path / "out"))
    assert not (tmp_path / "evil.py").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_links_and_devices_are_refused(tmp_path, kind):
    link = tarfile.TarInfo("core/link")
    link.type = kind
    link.linkname = "/etc/shadow"
    tar = _tar(tmp_path, [_file("main.py"), (link, None)])
    with pytest.raises(up.UpdateError):
        up.safe_extract(tar, str(tmp_path / "out"))


def test_plain_package_extracts(tmp_path):
    exe = tarfile.TarInfo("system/run.sh")
    exe.size = 3
    exe.mode = 0o755
    tar = _tar(tmp_path, [_file("main.py", b"ok"), _file("core/a.py", b"a"), (exe, b"#!x")])
    assert up.safe_extract(tar, str(tmp_path / "out")) == 3
    assert (tmp_path / "out" / "core" / "a.py").read_bytes() == b"a"


# ─── switching only when quiet ──────────────────────────────────────────────

class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def popen(monkeypatch):
    calls = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda args, **k: calls.append((args, k)))
    return calls


def _staged_unit(tmp_path, built, orch, clock):
    u, _ = _unit(tmp_path, built, orch=orch, clock=clock)
    assert u.check_once() == "staged"
    return u


def test_switches_after_ten_quiet_minutes(tmp_path, built, popen):
    clock = _Clock()
    orch = types.SimpleNamespace(mode="idle", audio_manager=types.SimpleNamespace(current_text=""))
    u = _staged_unit(tmp_path, built, orch, clock)
    assert not u.maybe_switch()                       # starts the quiet timer
    clock.t += up._IDLE_BEFORE_SWITCH_S - 1
    assert not u.maybe_switch()
    clock.t += 2
    assert u.maybe_switch()
    args, kw = popen[0]
    assert args == [u.app_init, "restart"] and kw["start_new_session"] is True


def test_any_use_restarts_the_quiet_timer(tmp_path, built, popen):
    clock = _Clock()
    orch = types.SimpleNamespace(mode="idle", audio_manager=types.SimpleNamespace(current_text=""))
    u = _staged_unit(tmp_path, built, orch, clock)
    u.maybe_switch()
    clock.t += up._IDLE_BEFORE_SWITCH_S - 60
    orch.mode = "explorer"                            # someone is walking with it
    assert not u.maybe_switch()
    orch.mode = "idle"
    clock.t += 120
    assert not u.maybe_switch(), "the quiet period starts over"
    orch.audio_manager.current_text = "orang di depan"
    clock.t += up._IDLE_BEFORE_SWITCH_S
    assert not u.maybe_switch()
    assert popen == []


def test_event_mode_never_switches_and_only_fetches_in_idle(tmp_path, built, popen, monkeypatch):
    clock = _Clock()
    orch = types.SimpleNamespace(mode="idle", audio_manager=types.SimpleNamespace(current_text=""))
    u = _staged_unit(tmp_path, built, orch, clock)    # staged before the event
    monkeypatch.setattr(up.Updater, "_cfg", staticmethod(
        lambda k, d: True if k == "event_mode" else d))
    orch.mode = "explorer"
    assert u.check_once() == "event-busy"
    assert u._interval_s() == up._EVENT_CHECK_S
    orch.mode = "idle"
    u.maybe_switch()
    clock.t += up._IDLE_BEFORE_SWITCH_S * 3           # a long pause between presenters
    assert not u.maybe_switch()
    assert popen == []


def test_no_switch_without_a_restartable_init_script(tmp_path, built, popen):
    clock = _Clock()
    orch = types.SimpleNamespace(mode="idle", audio_manager=None)
    u = _staged_unit(tmp_path, built, orch, clock)
    pathlib.Path(u.app_init).write_text("case $1 in start) ;; esac\n")
    u.maybe_switch()
    clock.t += up._IDLE_BEFORE_SWITCH_S * 2
    assert not u.maybe_switch()
    assert popen == []


# ─── confirming a release on trial ──────────────────────────────────────────

def _trial_unit(tmp_path, version="2026.11.1.1"):
    root = tmp_path / "root"
    app = root / "isora"
    app.mkdir(parents=True)
    (app / "VERSION").write_text(version + "\n")
    L = rel.Layout(str(root))
    os.makedirs(L.releases)
    rel.atomic_write(L.trial, "%s\n1\n" % version)
    return L, str(app)


def test_healthy_trial_is_confirmed(tmp_path):
    L, app = _trial_unit(tmp_path)
    orch = types.SimpleNamespace(loop_healthy=lambda s: True)
    assert up.confirm_when_healthy(orch, _Log(), layout=L, app_dir=app,
                                   sleep=lambda s: None)
    assert rel.read_trial(L) == (None, 0)


def test_unhealthy_trial_is_left_for_the_guard(tmp_path):
    L, app = _trial_unit(tmp_path)
    clock = _Clock()

    def _sleep(s):
        clock.t += s

    orch = types.SimpleNamespace(loop_healthy=lambda s: False)
    assert not up.confirm_when_healthy(orch, _Log(), layout=L, app_dir=app,
                                       sleep=_sleep, clock=clock)
    assert rel.read_trial(L)[0] == "2026.11.1.1"


def test_confirm_only_for_the_version_on_trial(tmp_path):
    L, app = _trial_unit(tmp_path)
    pathlib.Path(app, "VERSION").write_text("2026.10.1.1\n")
    orch = types.SimpleNamespace(loop_healthy=lambda s: True)
    assert not up.confirm_when_healthy(orch, _Log(), layout=L, app_dir=app,
                                       sleep=lambda s: None)
    assert rel.read_trial(L)[0] == "2026.11.1.1"


# ─── cleanup (needs symlinks: WSL/Linux) ────────────────────────────────────

def _symlinks_work():
    d = tempfile.mkdtemp()
    try:
        os.symlink(d, os.path.join(d, "l"))
        return True
    except (OSError, NotImplementedError):
        return False


@pytest.mark.skipif(not _symlinks_work(), reason="symlinks unavailable (run in WSL/Linux)")
def test_cleanup_keeps_running_previous_and_pending(tmp_path, built):
    u, _ = _unit(tmp_path, built)
    L = u.L
    for v in ("2026.9.1.1", "2026.10.1.1", "2026.10.2.1", "2026.11.1.1"):
        d = pathlib.Path(L.release_dir(v))
        d.mkdir(parents=True)
        (d / "main.py").write_text("x")
    os.rename(L.app, L.app + ".plain")
    rel.atomic_symlink(L.release_dir("2026.10.2.1"), L.app)
    rel.atomic_symlink(L.release_dir("2026.10.1.1"), L.previous)
    rel.request(L, "2026.11.1.1")
    pathlib.Path(L.releases, ".staging-2026.12.1.1").mkdir()
    u.cleanup()
    left = sorted(n for n in os.listdir(L.releases) if not n.startswith(("previous", "pending")))
    assert left == ["2026.10.1.1", "2026.10.2.1", "2026.11.1.1"]
