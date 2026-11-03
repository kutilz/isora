"""Logger: what survives a restart.

The device is switched off by pulling power and reset by the hardware
watchdog the same way, so the log on the SD card is the only account of what
happened before a restart. Two things used to make it hard to read:

  * before NTP the clock reads 1970 and the app always starts at the same
    uptime, so every start appended to the same isora_19700101_000018.log
    (80 boots in one file on isora-iiot);
  * nothing was fsync'd, so the last lines before a power cut were lost.
"""

import json
import os
import time

from utils import logger as logger_mod
from utils.logger import Logger


def _logs(d):
    return sorted(n for n in os.listdir(d) if n.endswith(".log"))


def test_every_start_gets_its_own_numbered_file(tmp_path):
    a = Logger(log_path=str(tmp_path), sync_interval_s=0)
    b = Logger(log_path=str(tmp_path), sync_interval_s=0)
    a.info("first")
    b.info("second")
    names = _logs(tmp_path)
    assert len(names) == 2, "two starts in the same second must not share a file"
    assert names[0].startswith("isora_00001_")
    assert names[1].startswith("isora_00002_")


def test_numbering_ignores_old_timestamp_only_names(tmp_path):
    (tmp_path / "isora_19700101_000018.log").write_text("")
    (tmp_path / "isora_00041_20261022_102200.log").write_text("")
    Logger(log_path=str(tmp_path), sync_interval_s=0)
    assert any(n.startswith("isora_00042_") for n in _logs(tmp_path))


def test_entries_carry_seconds_since_boot(tmp_path):
    log = Logger(log_path=str(tmp_path), sync_interval_s=0)
    log.info("hello", module="T")
    entry = json.loads((tmp_path / _logs(tmp_path)[0]).read_text().splitlines()[0])
    assert abs(entry["up"] - time.monotonic()) < 5


def test_sync_fsyncs_only_when_something_was_written(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(logger_mod.os, "fsync", lambda fd: calls.append(fd))
    log = Logger(log_path=str(tmp_path), sync_interval_s=0)
    log.sync()
    assert calls == []
    log.info("x")
    log.sync()
    assert len(calls) == 1
    log.sync()
    assert len(calls) == 1, "nothing new: no second fsync"


def test_background_sync_runs_on_its_own(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(logger_mod.os, "fsync", lambda fd: calls.append(fd))
    log = Logger(log_path=str(tmp_path), sync_interval_s=0.05)
    log.info("x")
    deadline = time.monotonic() + 3
    while not calls and time.monotonic() < deadline:
        time.sleep(0.02)
    log._closed.set()
    assert calls, "the LogSync thread never fsync'd"
