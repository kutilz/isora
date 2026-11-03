"""The ready greeting is spoken on every boot that has nothing else to say.

It used to be skipped whenever cloud pairing was enabled (the default), on the
assumption that core/cloud.py would speak instead — which it only does for an
unpaired, not-yet-set-up device. A paired unit, or a set-up one whose cloud was
unreachable, said "menghubungkan ke wifi" and then nothing, every boot. And the
greeting waited for an IP, so a unit with no WiFi never said it at all.
"""

import types

import pytest

import core.onboarding as ob


class _Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


class _AM:
    def __init__(self):
        self.said = []

    def queue_cue(self, wav, **k):
        self.said.append(wav)

    def queue(self, text, **k):
        self.said.append(text)


class _Log:
    def __getattr__(self, _n):
        return lambda *a, **k: None


@pytest.fixture
def boot(monkeypatch):
    from config import cfg

    def run(has_ip=False, **conf):
        monkeypatch.setattr(cfg, "_data", {**cfg._data, "data_collection_mode": False,
                                           "url_ack": False, "url_announce_enabled": True,
                                           **conf})
        clock = _Clock()
        monkeypatch.setattr(ob, "time", clock)
        am = _AM()
        orch = types.SimpleNamespace(_running=True, audio_manager=am)
        a = ob.OnboardingAnnouncer(orch, _Log())
        monkeypatch.setattr(a, "_web_ready", lambda: True)
        monkeypatch.setattr(a, "_has_ip", lambda: has_ip)
        monkeypatch.setattr(a, "_prewarm", lambda: None)
        a.wait_and_announce_on_boot()
        return am.said
    return run


GREETING = ["chime_ready.wav", "Isora siap digunakan."]


def test_paired_unit_with_cloud_is_greeted(boot):
    assert boot(has_ip=True, cloud_enabled=True, paired=True, setup_completed=True) == GREETING


def test_set_up_unit_whose_cloud_never_answers_is_greeted(boot):
    # cloud.py speaks only for an unpaired AND unconfigured device.
    assert boot(has_ip=True, cloud_enabled=True, paired=False, setup_completed=True) == GREETING


def test_greeting_does_not_wait_for_wifi(boot):
    assert boot(has_ip=False, cloud_enabled=True, paired=True, setup_completed=True) == GREETING


def test_first_boot_with_cloud_leaves_the_prompt_to_cloud(boot):
    # Its pairing prompt opens with "Isora siap." — no double greeting.
    assert boot(has_ip=True, cloud_enabled=True, paired=False, setup_completed=False) == []


def test_first_boot_with_no_wifi_still_says_it_is_ready(boot):
    assert boot(has_ip=False, cloud_enabled=True, paired=False, setup_completed=False) == GREETING


def test_mode_ambil_data_stays_quiet(boot):
    assert boot(has_ip=True, cloud_enabled=True, paired=True, setup_completed=True,
                data_collection_mode=True) == []


# ─── ACTION on an unpaired unit ──────────────────────────────────────────────
# Pairing used to take ACTION in every mode while unpaired, so a unit with an
# AI key but no relay answered every describe with "Gagal menghubungkan".

@pytest.mark.parametrize("mode,key,pairs", [
    ("idle", True, True),        # idle: ACTION has nothing else to do
    ("idle", False, True),
    ("context", True, False),    # a key: describe must work
    ("explorer", True, False),   # a key: online navigation must work
    ("context", False, True),    # no key: nothing to describe, pair instead
])
def test_action_pairs_only_where_it_has_nothing_else_to_do(monkeypatch, mode, key, pairs):
    import core.cloud as cloud
    from core.orchestrator import Orchestrator
    monkeypatch.setattr(cloud, "_ai_key_present", lambda: key)
    fake = types.SimpleNamespace(mode=mode)
    assert Orchestrator._action_means_pair(fake) is pairs
