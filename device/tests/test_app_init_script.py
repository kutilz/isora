"""The init scripts tools/run.py writes to the device must be valid shell.

They live as Python string literals, so a lost quote or backslash only shows
up when the unit boots — as an app that never starts. The release switch made
S26isoraapp the place where rollback happens, so it is also checked for the
pieces that rollback depends on.
"""

import importlib.util
import pathlib
import shutil
import subprocess

import pytest

_RUN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "run.py"
_SH = shutil.which("sh")


@pytest.fixture(scope="module")
def run_mod():
    spec = importlib.util.spec_from_file_location("isora_tools_run", _RUN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(_SH is None, reason="no POSIX sh on this machine")
@pytest.mark.parametrize("name", ["APP_INIT_SCRIPT", "CHIME_INIT_SCRIPT"])
def test_init_script_parses(run_mod, name, tmp_path):
    path = tmp_path / "script.sh"
    path.write_bytes(getattr(run_mod, name).encode())
    proc = subprocess.run([_SH, "-n", path.as_posix()], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_app_init_runs_the_release_switch_before_the_app(run_mod):
    s = run_mod.APP_INIT_SCRIPT
    assert s.index('python3 "$H" boot') < s.index("nohup python3 -u /root/isora/main.py")
    assert 'python3 "$H" guard' in s
    assert "restart)" in s, "the updater switches releases through `restart`"


def test_app_init_hands_the_app_to_the_supervisor(run_mod):
    s = run_mod.APP_INIT_SCRIPT
    start = s[s.index("  start)"):s.index("  stop)")]
    stop = s[s.index("  stop)"):s.index("  restart)")]
    assert run_mod.SUPERVISOR_PATH in run_mod.SYSTEM_FILES
    assert 'sh "$S"' in start
    # Supervised start returns before the unsupervised fallback can also run.
    supervised = start[start.index('sh "$S"'):start.index("nohup python3 -u /root/isora/main.py")]
    assert "exit 0" in supervised
    # Stop takes the supervisor down BEFORE the app, or it would respawn it.
    assert stop.index("touch /tmp/isora_stop") < stop.index("isora_main.pid")
    assert stop.index("kill \"$(cat $SUP)\"") < stop.index("kill \"$(cat /tmp/isora_main.pid)\"")


def test_system_files_exist(run_mod):
    for remote, (name, mode) in run_mod.SYSTEM_FILES.items():
        assert (pathlib.Path(run_mod.SYSTEM_DIR) / name).is_file(), remote
