"""
Tests for AnnouncePolicy.decide — the single nav-speech gate (Decision 1A/E1A).

decide(state, detections, now, cfg, force) -> (announcements, new_state)

Covers the eight branches from the eng-review test diagram:
new-object / unchanged-suppressed / cell-change / tier-change /
danger-timer-reannounce / on-demand-force / object-disappears-prune /
empty-silence, plus the per-label cooldown and the per-tick cap.
"""

from utils.announce_policy import decide


# Small config stub: a plain dict satisfies the cfg.get(key, default) contract
# used by both the real Config and these tests.
def _cfg(**over):
    base = {
        "announce_cooldown_s": 1.5,
        "announce_danger_remind_s": 3.0,
        "announce_max_per_tick": 2,
    }
    base.update(over)
    return base


def _det(label, pos="tengah", tier="far", is_danger=False, conf=0.9):
    return {"label": label, "position": pos, "tier": tier,
            "is_danger": is_danger, "confidence": conf}


def test_new_object_is_announced():
    ann, state = decide({}, [_det("person")], now=10.0, cfg=_cfg())
    assert [a["label"] for a in ann] == ["person"]
    assert state["person"]["last"] == 10.0


def test_unchanged_calm_scene_is_suppressed():
    _, s1 = decide({}, [_det("chair", "kiri", "far")], now=10.0, cfg=_cfg())
    ann, _ = decide(s1, [_det("chair", "kiri", "far")], now=20.0, cfg=_cfg())
    assert ann == []  # same label, same cell, same tier, not danger -> quiet


def test_grid_cell_change_is_announced():
    _, s1 = decide({}, [_det("person", "kiri", "far")], now=10.0, cfg=_cfg())
    ann, _ = decide(s1, [_det("person", "kanan", "far")], now=20.0, cfg=_cfg())
    assert [a["label"] for a in ann] == ["person"]


def test_distance_tier_change_is_announced():
    _, s1 = decide({}, [_det("person", "tengah", "far")], now=10.0, cfg=_cfg())
    ann, _ = decide(s1, [_det("person", "tengah", "near")], now=20.0, cfg=_cfg())
    assert [a["label"] for a in ann] == ["person"]  # far -> near must speak


def test_danger_reannounces_on_timer_even_when_unchanged():
    # SAFETY: a near/danger object you keep walking toward must not go silent.
    cfg = _cfg()
    _, s1 = decide({}, [_det("person", "tengah", "near")], now=10.0, cfg=cfg)
    # 1s later, unchanged: still inside remind window -> quiet
    ann_quiet, s2 = decide(s1, [_det("person", "tengah", "near")], now=11.0, cfg=cfg)
    assert ann_quiet == []
    # 3s+ after last announce, unchanged: re-announce
    ann_remind, _ = decide(s2, [_det("person", "tengah", "near")], now=13.5, cfg=cfg)
    assert [a["label"] for a in ann_remind] == ["person"]


def test_force_reads_out_everything_bypassing_suppression():
    # on-demand readout: same unchanged scene, but force speaks all of it.
    dets = [_det("person", "kiri", "far"), _det("chair", "kanan", "far")]
    _, s1 = decide({}, dets, now=10.0, cfg=_cfg())
    ann, _ = decide(s1, dets, now=10.2, cfg=_cfg(), force=True)
    assert sorted(a["label"] for a in ann) == ["chair", "person"]


def test_disappeared_object_is_pruned_from_state():
    _, s1 = decide({}, [_det("person"), _det("chair")], now=10.0, cfg=_cfg())
    _, s2 = decide(s1, [_det("person")], now=20.0, cfg=_cfg())
    assert "chair" not in s2  # gone -> no stale danger timer
    assert "person" in s2


def test_empty_detections_is_silence_and_clears_state():
    _, s1 = decide({}, [_det("person")], now=10.0, cfg=_cfg())
    ann, s2 = decide(s1, [], now=20.0, cfg=_cfg())
    assert ann == []
    assert s2 == {}


def test_cooldown_suppresses_rapid_changes():
    cfg = _cfg(announce_cooldown_s=1.5)
    _, s1 = decide({}, [_det("person", "kiri", "far")], now=10.0, cfg=cfg)
    # cell changes again 0.5s later -> within cooldown -> suppressed
    ann, _ = decide(s1, [_det("person", "kanan", "far")], now=10.5, cfg=cfg)
    assert ann == []


def test_per_tick_cap_limits_announcements_but_records_all_state():
    cfg = _cfg(announce_max_per_tick=2)
    dets = [
        _det("person", tier="near", is_danger=True, conf=0.9),
        _det("chair", tier="far", conf=0.8),
        _det("bottle", tier="far", conf=0.7),
    ]
    ann, state = decide({}, dets, now=10.0, cfg=cfg)
    assert len(ann) == 2                       # capped
    assert ann[0]["label"] == "person"         # danger ranked first
    assert set(state) == {"person", "chair", "bottle"}  # all tracked
