#!/usr/bin/env python3
"""
Release switch + rollback for the I-Sora app. Survives power loss at any point.

Runs from /etc/isora/release.py (installed by `tools/run.py --autostart`),
OUTSIDE the app tree it manages: an update that breaks the app must not be
able to break its own rescue. The app imports the same file from its tree
(`system.release`) only for the shared layout — so the on-disk format below is
a contract between versions and must only ever grow.

Layout
------
  /root/isora                -> symlink to the release that runs
  /root/isora-releases/
      <version>/             one complete app tree per version (+ VERSION)
      previous               symlink to the release to fall back to
      pending                "<version>"        — switch to it at next start
      trial                  "<version>\\n<n>"   — started n times, not yet
                                                   confirmed healthy
      bad                    one version per line — never install again
      release.log            what this script did, bounded

Why it cannot leave the device without an app
---------------------------------------------
Every change is a rename(2): a new symlink or a new state file is written
under a temporary name, fsync'd, then renamed over the old one, and the
directory is fsync'd. The rootfs is ext4 (journaled), so after a power cut
each name is either entirely old or entirely new. The order of the steps in
apply_pending() is chosen so that a cut between any two of them leaves a state
that the next boot either finishes or ignores; recover() covers the one case
where /root/isora itself can be missing (between the two renames of migrate()).

Commands (exit code 0 unless noted)
-----------------------------------
  boot    before the app starts: recover, apply pending, count the trial
  guard [TRIAL]  ~4 min after a trial start: still unconfirmed → roll back
                 (exit 3); TRIAL = the trial file at that start, "<ver> <n>"
  status  print the state as JSON
  migrate turn a plain /root/isora directory into the symlink layout
"""

import json
import os
import sys
import time

MAX_TRIES = 3          # starts allowed before an unconfirmed release is rolled back
_LOG_MAX_LINES = 300


class Layout:
    def __init__(self, root: str = "/root"):
        self.root = root
        self.app = os.path.join(root, "isora")
        self.releases = os.path.join(root, "isora-releases")
        self.previous = os.path.join(self.releases, "previous")
        self.pending = os.path.join(self.releases, "pending")
        self.trial = os.path.join(self.releases, "trial")
        self.bad = os.path.join(self.releases, "bad")
        self.log_path = os.path.join(self.releases, "release.log")

    def release_dir(self, version: str) -> str:
        return os.path.join(self.releases, version)


# ─── versions ────────────────────────────────────────────────────────────────

def parse_version(v):
    """"2026.10.21.1" or "2026.10.21.1+dev.x" → (2026, 10, 21, 1). Junk → None."""
    base = (v or "").strip().split("+", 1)[0]
    try:
        parts = tuple(int(p) for p in base.split("."))
    except ValueError:
        return None
    return parts if parts else None


def is_newer(candidate: str, current: str) -> bool:
    """A missing/unparseable current version counts as the oldest possible."""
    c = parse_version(candidate)
    if c is None:
        return False
    return c > (parse_version(current) or (0,))


def safe_version(v: str) -> bool:
    """Usable as a directory name: digits and dots only."""
    return bool(v) and len(v) <= 40 and all(ch.isdigit() or ch == "." for ch in v) \
        and parse_version(v) is not None


def read_version(app_dir: str) -> str:
    try:
        with open(os.path.join(app_dir, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return ""


# ─── atomic primitives ───────────────────────────────────────────────────────

def _fsync_dir(path: str):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path: str, text: str):
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(os.path.dirname(path))


def atomic_symlink(target: str, link: str):
    """Point `link` at `target` in one rename. `link` must not be a real dir."""
    tmp = "%s.tmp-%d" % (link, os.getpid())
    try:
        os.unlink(tmp)
    except OSError:
        pass
    os.symlink(target, tmp)
    os.replace(tmp, link)
    _fsync_dir(os.path.dirname(link))


def remove(path: str):
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    _fsync_dir(os.path.dirname(path))


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


# ─── state ───────────────────────────────────────────────────────────────────

def valid_release(path) -> bool:
    return bool(path) and os.path.isfile(os.path.join(path, "main.py"))


def current_target(L: Layout):
    """Real path of the running release, or None if /root/isora is not a link."""
    if not os.path.islink(L.app):
        return None
    return os.path.realpath(L.app)


def bad_versions(L: Layout) -> set:
    return {ln.strip() for ln in _read(L.bad).splitlines() if ln.strip()}


def read_trial(L: Layout):
    lines = _read(L.trial).split()
    if not lines:
        return None, 0
    try:
        tries = int(lines[1]) if len(lines) > 1 else 0
    except ValueError:
        tries = 0
    return lines[0], tries


def log(L: Layout, msg: str):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        os.makedirs(L.releases, exist_ok=True)
        lines = _read(L.log_path).splitlines()[-(_LOG_MAX_LINES - 1):] + [line]
        atomic_write(L.log_path, "\n".join(lines) + "\n")
    except OSError:
        pass


# ─── transitions ─────────────────────────────────────────────────────────────

def migrate(L: Layout) -> bool:
    """Plain /root/isora directory → releases/<version> + symlink.

    Two renames; a cut between them leaves /root/isora missing, which
    recover() repairs on the next boot by pointing at the newest release.
    """
    if os.path.islink(L.app) or not os.path.isdir(L.app):
        return False
    os.makedirs(L.releases, exist_ok=True)
    ver = read_version(L.app)
    name = ver.split("+", 1)[0] if safe_version(ver.split("+", 1)[0]) else "0"
    dest = L.release_dir(name)
    n = 1
    while os.path.lexists(dest):
        dest = L.release_dir("%s.%d" % (name, n))
        n += 1
    os.rename(L.app, dest)
    _fsync_dir(L.root)
    _fsync_dir(L.releases)
    atomic_symlink(dest, L.app)
    log(L, "migrate: %s -> %s" % (L.app, dest))
    return True


def _release_candidates(L: Layout) -> list:
    """Installed releases, newest first, excluding known-bad ones."""
    bad = bad_versions(L)
    out = []
    try:
        names = os.listdir(L.releases)
    except OSError:
        return out
    for name in names:
        path = L.release_dir(name)
        if name.startswith(".") or name in bad or os.path.islink(path):
            continue
        if parse_version(name) is None or not valid_release(path):
            continue
        out.append((parse_version(name), path))
    out.sort(reverse=True)
    return [p for _, p in out]


def recover(L: Layout) -> bool:
    """Make sure /root/isora points at something that can start."""
    if os.path.isdir(L.app) and not os.path.islink(L.app):
        return False                              # a plain tree (dev deploy): leave it
    if valid_release(L.app):
        return False
    choices = []
    if os.path.islink(L.previous):
        choices.append(os.path.realpath(L.previous))
    # A release that is only PENDING has not been through a trial yet; it
    # goes last, so a cut in the middle of migrate() can never start it
    # without the trial bookkeeping that would roll it back.
    pending = L.release_dir(_read(L.pending).strip()) if _read(L.pending).strip() else None
    cands = _release_candidates(L)
    choices += [p for p in cands if p != pending] + [p for p in cands if p == pending]
    for path in choices:
        if valid_release(path):
            atomic_symlink(path, L.app)
            log(L, "recover: %s was not startable, now -> %s" % (L.app, path))
            return True
    log(L, "recover: no startable release found")
    return False


def apply_pending(L: Layout) -> bool:
    ver = _read(L.pending).strip()
    if not ver:
        remove(L.pending)
        return False
    target = L.release_dir(ver)
    if not safe_version(ver) or not valid_release(target) or ver in bad_versions(L):
        log(L, "pending %r is not installable — dropped" % ver)
        remove(L.pending)
        return False
    if not os.path.islink(L.app):
        migrate(L)
    cur = current_target(L)
    if cur and os.path.realpath(cur) == os.path.realpath(target):
        # The switch happened and the power went before `pending` was removed.
        remove(L.pending)
        return False
    # Order matters (see module docstring). A cut after any step is finished
    # by the next boot, because `pending` is only removed last.
    if cur and valid_release(cur):
        atomic_symlink(cur, L.previous)
    atomic_write(L.trial, "%s\n0\n" % ver)
    atomic_symlink(target, L.app)
    remove(L.pending)
    log(L, "switch: %s -> %s (trial)" % (cur, target))
    return True


def rollback(L: Layout, reason: str) -> bool:
    cur = current_target(L)
    ver = os.path.basename(cur) if cur else ""
    prev = os.path.realpath(L.previous) if os.path.islink(L.previous) else None
    remove(L.trial)
    if not prev or not valid_release(prev) or (cur and os.path.realpath(cur) == prev):
        log(L, "rollback wanted (%s) but no previous release — keeping %s" % (reason, cur))
        return False
    if ver:
        bad = bad_versions(L)
        bad.add(ver)
        atomic_write(L.bad, "\n".join(sorted(bad)) + "\n")
    atomic_symlink(prev, L.app)
    log(L, "rollback: %s -> %s (%s); %s marked bad" % (cur, prev, reason, ver))
    return True


def count_trial(L: Layout) -> bool:
    """One more start of an unconfirmed release; too many → roll back."""
    ver, tries = read_trial(L)
    if ver is None:
        return False
    cur = current_target(L)
    if not cur or os.path.basename(cur) != ver:
        remove(L.trial)                            # stale: not what is running
        return False
    tries += 1
    if tries > MAX_TRIES:
        return rollback(L, "%d starts without becoming healthy" % (tries - 1))
    atomic_write(L.trial, "%s\n%d\n" % (ver, tries))
    return False


def boot(L: Layout):
    if not os.path.isdir(L.releases) and not os.path.lexists(L.app):
        return
    recover(L)
    if os.path.exists(L.pending):
        apply_pending(L)
    if os.path.exists(L.trial):
        count_trial(L)
    recover(L)


def guard(L: Layout, expect: str = None) -> bool:
    """Called a few minutes after a trial start. True = rolled back.

    `expect` is the trial file as it read when this guard was spawned
    ("<version> <starts>"). A guard outlives its own start when the app is
    restarted while it sleeps, and must then leave the NEXT start alone: that
    one has its own guard, and judging it early would roll back — and mark
    bad for good — a release that had not yet had its chance to confirm.
    Seen on a unit 2026-10-21: a switch 77 s into the previous trial.
    """
    ver, tries = read_trial(L)
    if ver is None:
        return False
    if expect is not None and expect.split() != [ver, str(tries)]:
        return False
    return rollback(L, "not confirmed healthy in time")


def confirm(L: Layout, version: str) -> bool:
    """The running app calls this once it is healthy."""
    ver, _ = read_trial(L)
    if ver is None or ver != version:
        return False
    remove(L.trial)
    log(L, "confirm: %s is healthy" % version)
    return True


def request(L: Layout, version: str):
    """Ask for `version` (already in releases/) to start at the next app start."""
    atomic_write(L.pending, version + "\n")


def status(L: Layout) -> dict:
    ver, tries = read_trial(L)
    return {
        "app": L.app,
        "running": current_target(L),
        "version": read_version(L.app),
        "previous": os.path.realpath(L.previous) if os.path.islink(L.previous) else None,
        "pending": _read(L.pending).strip() or None,
        "trial": {"version": ver, "starts": tries} if ver else None,
        "bad": sorted(bad_versions(L)),
    }


def main(argv) -> int:
    root = "/root"
    args = list(argv)
    if "--root" in args:
        i = args.index("--root")
        root = args[i + 1]
        del args[i:i + 2]
    cmd = args[0] if args else "status"
    L = Layout(root)
    if cmd == "boot":
        boot(L)
        return 0
    if cmd == "guard":
        return 3 if guard(L, args[1] if len(args) > 1 else None) else 0
    if cmd == "migrate":
        migrate(L)
        return 0
    if cmd == "status":
        print(json.dumps(status(L), indent=2))
        return 0
    print("usage: release.py [--root DIR] boot|guard [TRIAL]|status|migrate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
