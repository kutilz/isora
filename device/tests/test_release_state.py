"""system/release.py — the switch + rollback that runs before the app starts.

The promise being tested: whatever moment the power goes, the next boot finds
an app it can start, and a release that does not come up healthy is replaced
by the one before it. Power cuts are simulated by making the N-th atomic step
raise, for every N, and then booting again with nothing patched.

Needs real symlinks (the device's layout is one). Windows without developer
mode cannot create them, so there the module is skipped; run it in WSL:
    python3 -m pytest device/tests/test_release_state.py
"""

import os
import pathlib
import tempfile

import pytest

from system import release as rel


def _symlinks_work():
    d = tempfile.mkdtemp()
    try:
        os.symlink(d, os.path.join(d, "l"))
        return True
    except (OSError, NotImplementedError):
        return False


pytestmark = pytest.mark.skipif(not _symlinks_work(),
                                reason="symlinks unavailable (run in WSL/Linux)")


def _make_release(L, version, extra=""):
    d = pathlib.Path(L.release_dir(version))
    d.mkdir(parents=True)
    (d / "main.py").write_text("# app %s %s\n" % (version, extra))
    (d / "VERSION").write_text(version + "\n")
    return str(d)


def _running(L):
    return os.path.basename(os.path.realpath(L.app))


@pytest.fixture
def L(tmp_path):
    return rel.Layout(str(tmp_path))


@pytest.fixture
def installed(L):
    """A unit that has been on the release layout: 1.0 running."""
    old = _make_release(L, "2026.10.1.1")
    rel.atomic_symlink(old, L.app)
    return L


# ─── versions ────────────────────────────────────────────────────────────────

def test_version_order():
    assert rel.is_newer("2026.10.21.1", "2026.10.20.3")
    assert rel.is_newer("2026.10.21.2", "2026.10.21.1+dev.20261021T1200")
    assert not rel.is_newer("2026.10.21.1", "2026.10.21.1+dev.x"), \
        "a dev build is only replaced by something newer than its base"
    assert rel.is_newer("2026.10.21.1", ""), "no VERSION = oldest"
    assert not rel.is_newer("junk", "")
    assert not rel.safe_version("../etc")
    assert rel.safe_version("2026.10.21.1")


# ─── migrate + recover ──────────────────────────────────────────────────────

def test_migrate_turns_a_plain_tree_into_the_layout(L):
    pathlib.Path(L.app).mkdir()
    (pathlib.Path(L.app) / "main.py").write_text("legacy")
    assert rel.migrate(L)
    assert os.path.islink(L.app)
    assert rel.valid_release(L.app)
    assert _running(L) == "0"


def test_recover_repairs_a_missing_app(installed):
    L = installed
    os.unlink(L.app)                         # e.g. a cut inside migrate()
    rel.boot(L)
    assert rel.valid_release(L.app)


def test_recover_prefers_a_tried_release_over_a_pending_one(L):
    old = _make_release(L, "2026.10.1.1")
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    assert not os.path.lexists(L.app)
    rel.recover(L)
    assert os.path.realpath(L.app) == os.path.realpath(old), \
        "an untried release must not start without its trial bookkeeping"


def test_plain_dev_tree_is_left_alone(L):
    pathlib.Path(L.app).mkdir()
    (pathlib.Path(L.app) / "main.py").write_text("dev")
    rel.boot(L)
    assert not os.path.islink(L.app)


# ─── switch, trial, confirm, rollback ───────────────────────────────────────

def test_pending_switches_and_starts_a_trial(installed):
    L = installed
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    assert _running(L) == "2026.10.2.1"
    assert os.path.basename(os.path.realpath(L.previous)) == "2026.10.1.1"
    assert rel.read_trial(L) == ("2026.10.2.1", 1)
    assert not os.path.exists(L.pending)


def test_confirm_ends_the_trial(installed):
    L = installed
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    assert rel.confirm(L, "2026.10.2.1")
    assert rel.read_trial(L) == (None, 0)
    for _ in range(rel.MAX_TRIES + 2):
        rel.boot(L)
    assert _running(L) == "2026.10.2.1"


def test_repeated_unconfirmed_starts_roll_back(installed):
    L = installed
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    for _ in range(rel.MAX_TRIES):
        rel.boot(L)
        assert _running(L) == "2026.10.2.1"
    rel.boot(L)
    assert _running(L) == "2026.10.1.1"
    assert "2026.10.2.1" in rel.bad_versions(L)
    assert rel.read_trial(L) == (None, 0)


def test_guard_rolls_back_an_unconfirmed_release(installed):
    L = installed
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    assert rel.guard(L) is True
    assert _running(L) == "2026.10.1.1"
    assert rel.main(["--root", L.root, "guard"]) == 0, "nothing left to roll back"


def test_a_guard_from_an_earlier_start_leaves_the_next_one_alone(installed):
    # The app was restarted into a new release while the previous start's
    # guard still slept. That guard must not judge the new release, which has
    # its own guard and has not had its 240 s yet.
    L = installed
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    stale = "2026.10.1.9 1"
    assert rel.main(["--root", L.root, "guard", stale]) == 0
    assert _running(L) == "2026.10.2.1"
    assert rel.read_trial(L) == ("2026.10.2.1", 1)
    # Same release, but started again since: also not this guard's business.
    rel.boot(L)
    assert rel.guard(L, "2026.10.2.1 1") is False
    assert _running(L) == "2026.10.2.1"
    # Its own start's guard still rolls it back.
    assert rel.main(["--root", L.root, "guard", "2026.10.2.1 2 "]) == 3
    assert _running(L) == "2026.10.1.1"


def test_bad_versions_are_never_switched_to_again(installed):
    L = installed
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    rel.guard(L)
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    assert _running(L) == "2026.10.1.1"


def test_pending_from_a_plain_tree_migrates_first(L):
    pathlib.Path(L.app).mkdir()
    (pathlib.Path(L.app) / "main.py").write_text("legacy")
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")
    rel.boot(L)
    assert _running(L) == "2026.10.2.1"
    assert os.path.basename(os.path.realpath(L.previous)) == "0"
    rel.guard(L)
    assert _running(L) == "0", "the old plain tree is the way back"


def test_junk_pending_is_dropped(installed):
    L = installed
    rel.atomic_write(L.pending, "../../etc\n")
    rel.boot(L)
    assert _running(L) == "2026.10.1.1"
    assert not os.path.exists(L.pending)


# ─── power cuts ──────────────────────────────────────────────────────────────

class _Cut(Exception):
    pass


def _cut_after(monkeypatch, n):
    """Make the (n+1)-th atomic step 'lose power' (raise before it happens)."""
    calls = {"n": 0}
    real = {name: getattr(rel, name) for name in ("atomic_write", "atomic_symlink", "remove")}

    def wrap(name):
        def f(*a, **k):
            if calls["n"] >= n:
                raise _Cut()
            calls["n"] += 1
            return real[name](*a, **k)
        return f

    for name in real:
        monkeypatch.setattr(rel, name, wrap(name))
    return real


@pytest.mark.parametrize("cut_at", range(0, 8))
@pytest.mark.parametrize("start", ["layout", "plain"])
def test_power_cut_during_a_switch_never_strands_the_device(tmp_path, monkeypatch,
                                                            cut_at, start):
    L = rel.Layout(str(tmp_path))
    if start == "plain":
        pathlib.Path(L.app).mkdir()
        (pathlib.Path(L.app) / "main.py").write_text("legacy")
        (pathlib.Path(L.app) / "VERSION").write_text("2026.10.1.1+dev.x\n")
    else:
        rel.atomic_symlink(_make_release(L, "2026.10.1.1"), L.app)
    _make_release(L, "2026.10.2.1")
    rel.request(L, "2026.10.2.1")

    real = _cut_after(monkeypatch, cut_at)
    try:
        rel.boot(L)
    except _Cut:
        pass
    for name, fn in real.items():                        # power is back
        monkeypatch.setattr(rel, name, fn)

    rel.boot(L)                                          # the next boot
    assert rel.valid_release(L.app), "no startable app after a cut at step %d" % cut_at
    running = _running(L)
    if running == "2026.10.2.1":
        ver, tries = rel.read_trial(L)
        assert ver == "2026.10.2.1" and tries >= 1, \
            "the new release must be on trial, or a bad one could never roll back"
        assert rel.valid_release(L.previous)
    # Whatever happened, finishing the boots converges on a sane state:
    rel.boot(L)
    assert rel.valid_release(L.app)
    assert not os.path.exists(L.pending) or rel._read(L.pending).strip() == "2026.10.2.1"
