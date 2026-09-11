"""Unit tests for the pure generation-time helpers (Lane C).

`atempo_chain` and the single-source-of-truth (SSOT) object-set derivation are
pure → exercised off-device. ffmpeg's `atempo` filter caps at 2.0x per instance,
so rates above that must be chained (product of factors == requested rate).
"""

import os
import sys

# tools/ is not a package; import generate_audio the way the script lives on disk.
_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tools")
)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import generate_audio  # noqa: E402
import config  # noqa: E402


def _product(args):
    """Multiply the atempo=<f> factors in an -filter:a chain back together."""
    prod = 1.0
    for a in args:
        assert a.startswith("atempo="), a
        prod *= float(a.split("=", 1)[1])
    return prod


def test_atempo_chain_normal_speed_is_noop():
    # 1.0x = no time-compression → empty filter list (skip atempo entirely).
    assert generate_audio.atempo_chain(1.0) == []


def test_atempo_chain_single_filter_under_cap():
    assert generate_audio.atempo_chain(1.6) == ["atempo=1.6"]


def test_atempo_chain_at_cap_is_single_filter():
    assert generate_audio.atempo_chain(2.0) == ["atempo=2.0"]


def test_atempo_chain_above_cap_splits_to_two():
    # ffmpeg caps each atempo at 2.0 → 2.5 must chain.
    chain = generate_audio.atempo_chain(2.5)
    assert chain == ["atempo=2.0", "atempo=1.25"]
    assert abs(_product(chain) - 2.5) < 1e-9


def test_atempo_chain_four_x_chains_two_max_filters():
    chain = generate_audio.atempo_chain(4.0)
    # 4.0 = 2.0 * 2.0 → two capped filters, product preserved.
    assert all(a == "atempo=2.0" for a in chain)
    assert abs(_product(chain) - 4.0) < 1e-9


def test_atempo_chain_preserves_rate_for_arbitrary_high_rate():
    for rate in (2.1, 3.0, 3.3, 5.0):
        chain = generate_audio.atempo_chain(rate)
        assert abs(_product(chain) - rate) < 1e-9, (rate, chain)
        # Every link must respect ffmpeg's 2.0 cap.
        assert all(float(a.split("=", 1)[1]) <= 2.0 + 1e-9 for a in chain)


# ─── SSOT: RELEVANT_LABELS is DERIVED from NAV_OBJECTS, can't drift ───────────

def test_nav_objects_canonical_set_present():
    expected = {
        "person", "motorcycle", "car", "bicycle", "bus", "truck",
        "dog", "cat", "chair", "bottle", "handbag", "backpack",
    }
    assert set(config.NAV_OBJECTS.keys()) == expected
    # Indonesian phrasing IDs preserved for the matured set.
    assert config.NAV_OBJECTS["person"] == "orang"
    assert config.NAV_OBJECTS["backpack"] == "ransel"


def test_relevant_labels_derived_from_nav_objects():
    assert config.RELEVANT_LABELS == set(config.NAV_OBJECTS.keys())


def test_generate_audio_objects_is_the_canonical_map():
    # generate_audio must consume the single source of truth, not its own copy.
    assert generate_audio.OBJECTS == config.NAV_OBJECTS
