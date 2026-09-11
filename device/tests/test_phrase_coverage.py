"""Offline guarantee gate (Workstream C1).

Enumerate every nav phrase the system can emit — object x position, plus the
planned distance-tier variants (near/far) — and assert the generator has a
PLANNED WAV for each. If this ever fails, some nav phrase would fall through to
a network gTTS call at runtime, breaking the "100% offline core nav" promise.

This asserts against the generator's *planned/enumerated* filename set
(`build_audio_list()` + tier variants), NOT the on-disk audio/ directory, which
may be incomplete in CI. Actually rendering the WAVs is a separate deploy step.
"""

import os
import sys

_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tools")
)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import generate_audio  # noqa: E402
import config  # noqa: E402

# The distance tiers the policy lane (Decision 5: per-class near/far) can emit.
NAV_TIERS = ("near", "far")


def _enumerate_nav_phrases():
    """Every nav phrase the device can emit → expected WAV filename.

    Mirrors AnnouncePolicy's output space: each detected object, at each of the
    9 grid positions, optionally qualified by a coarse distance tier.
    """
    expected = set()
    for label in config.NAV_OBJECTS:
        for pos in generate_audio.POSITIONS:
            # plain phrase (tier-less)
            expected.add(f"obj_{label}_{pos}.wav")
            # distance-tier variants
            for tier in NAV_TIERS:
                expected.add(f"obj_{label}_{pos}_{tier}.wav")
    return expected


def _planned_filenames():
    """All WAV filenames the generator plans to produce (incl. tier variants)."""
    planned = {fn for fn, _txt in generate_audio.build_audio_list()}
    planned |= set(generate_audio.nav_tier_filenames(NAV_TIERS))
    return planned


def test_every_nav_phrase_has_a_planned_wav():
    expected = _enumerate_nav_phrases()
    planned = _planned_filenames()
    missing = expected - planned
    assert not missing, (
        f"{len(missing)} nav phrase(s) would need network (no pre-rendered WAV): "
        f"{sorted(missing)[:10]}"
    )


def test_coverage_spans_all_objects_positions_and_tiers():
    # 12 objects x 9 positions x (1 plain + 2 tiers) = 324 nav phrases.
    expected = _enumerate_nav_phrases()
    assert len(config.NAV_OBJECTS) == 12
    assert len(generate_audio.POSITIONS) == 9
    assert len(expected) == 12 * 9 * (1 + len(NAV_TIERS))


def test_planned_set_is_consistent_with_canonical_objects():
    # No planned obj_*.wav references a label outside the single source of truth.
    planned_obj = {
        fn for fn in _planned_filenames() if fn.startswith("obj_")
    }
    for fn in planned_obj:
        # obj_<label>_<pos>[_<tier>].wav — label may itself contain no '_'
        # for our matured set, so the first token after 'obj_' is the label.
        rest = fn[len("obj_"):-len(".wav")]
        label = rest.split("_", 1)[0]
        assert label in config.NAV_OBJECTS, fn
