"""Which mode the device stands in the moment it powers on.

Booting straight into explorer means a device that starts talking about its
surroundings before anyone asked it to — while it is still in a bag, on a
table, being handed over. The neutral 'idle' mode is the state where the
device is on, reachable, and quiet.
"""

from core.orchestrator import Orchestrator

resolve = Orchestrator.resolve_boot_mode


def test_an_unconfigured_device_boots_neutral():
    assert resolve(None, last_mode="explorer") == "idle"
    assert resolve("", last_mode="explorer") == "idle"


def test_a_configured_boot_mode_is_honoured():
    # A pendamping who always uses the device for navigation should not have to
    # press the button every power-on.
    assert resolve("explorer", last_mode="qris") == "explorer"
    assert resolve("context", last_mode="qris") == "context"
    assert resolve("idle", last_mode="explorer") == "idle"


def test_last_resumes_the_mode_the_device_was_switched_off_in():
    assert resolve("last", last_mode="context") == "context"
    assert resolve("LAST", last_mode="explorer") == "explorer"


def test_last_with_nothing_remembered_falls_back_to_neutral():
    # First boot after a flash, or a config.json that lost the key.
    assert resolve("last", last_mode=None) == "idle"
    assert resolve("last", last_mode="") == "idle"


def test_an_unusable_boot_mode_never_guesses_explorer():
    for junk in ("ekplorer", "yolo", 3, [], {}, True, "data_collection"):
        assert resolve(junk, last_mode="qris") == "idle"


def test_the_mode_button_walks_every_mode_and_comes_home():
    # A blind user navigates modes only by pressing and listening. If any mode
    # is unreachable, or the cycle skips home, they have no way back to quiet.
    seen  = []
    mode  = "idle"
    for _ in range(len(Orchestrator.MODES)):
        seen.append(mode)
        mode = Orchestrator.next_mode(mode)
    assert set(seen) == set(Orchestrator.MODES)
    assert mode == "idle"          # one full lap returns to the neutral state


def test_the_button_recovers_from_an_unknown_current_mode():
    assert Orchestrator.next_mode("data_collection") == "idle"
    assert Orchestrator.next_mode(None) == "idle"
