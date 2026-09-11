"""Camera orientation: the quarter-turn correction for a device whose mount
angle changed (chest clip vs. hung upside down vs. strapped sideways).

The geometry here is pure on purpose — a wrong `rotated_dims` silently corrupts
every bbox normalization downstream (spoken left/right, the ground-contact
distance hint, the phantom-detection movement test), and that is exactly the
class of bug that is invisible until someone wears the device.
"""

from utils.orientation import (
    VALID_ROTATIONS,
    normalize_rotation,
    rotate_image,
    rotated_dims,
    rotation_label,
    set_hw_flip,
    swaps_axes,
)


# ─── normalize_rotation ───────────────────────────────────────────────────────

def test_exact_quarter_turns_pass_through():
    for rot in VALID_ROTATIONS:
        assert normalize_rotation(rot) == rot


def test_wraps_past_a_full_turn():
    assert normalize_rotation(360) == 0
    assert normalize_rotation(450) == 90
    assert normalize_rotation(-90) == 270
    assert normalize_rotation(-180) == 180


def test_snaps_to_the_nearest_quarter_turn():
    # A near-miss (a rounded float from a slider, say) lands on the intended
    # turn rather than being discarded.
    assert normalize_rotation(89.6) == 90
    assert normalize_rotation(181) == 180


def test_junk_falls_back_to_no_rotation():
    # An unreadable orientation must leave the camera ALONE. Guessing a turn
    # the user never asked for is worse than ignoring a bad value.
    for junk in (None, "", "kiri", [], {}, float("nan"), float("inf")):
        assert normalize_rotation(junk) == 0


def test_numeric_strings_are_accepted():
    # Config round-trips through JSON and querystrings; "180" is the same turn.
    assert normalize_rotation("180") == 180
    assert normalize_rotation("90") == 90


# ─── axis swap + dims ─────────────────────────────────────────────────────────

def test_only_quarter_turns_swap_axes():
    assert not swaps_axes(0)
    assert not swaps_axes(180)
    assert swaps_axes(90)
    assert swaps_axes(270)


def test_rotated_dims_swaps_for_quarter_turns_only():
    assert rotated_dims(320, 224, 0) == (320, 224)
    assert rotated_dims(320, 224, 180) == (320, 224)
    assert rotated_dims(320, 224, 90) == (224, 320)
    assert rotated_dims(320, 224, 270) == (224, 320)


def test_rotated_dims_applied_twice_returns_the_original_shape():
    # Two quarter turns is a half turn, which restores the frame shape; two
    # half turns is no turn at all. Either way the shape must come back.
    for rot in VALID_ROTATIONS:
        w, h = rotated_dims(320, 224, rot)
        assert rotated_dims(w, h, rot) == (320, 224)


def test_rotation_label():
    assert rotation_label(0) == "normal"
    assert rotation_label(180) == "180°"
    assert rotation_label(-90) == "270°"


# ─── hardware flip probe ──────────────────────────────────────────────────────

class _FakeCam:
    """MaixPy's get/set-in-one accessor shape: cam.hmirror(1) sets, cam.hmirror() reads."""

    def __init__(self, obeys=True):
        self._h = 0
        self._v = 0
        self._obeys = obeys

    def hmirror(self, value=-1):
        if value != -1 and self._obeys:
            self._h = value
        return self._h

    def vflip(self, value=-1):
        if value != -1 and self._obeys:
            self._v = value
        return self._v


def test_hw_flip_reports_success_when_the_sensor_obeys():
    cam = _FakeCam()
    assert set_hw_flip(cam, True, True) is True
    assert cam.hmirror() == 1 and cam.vflip() == 1


def test_hw_flip_clears_both_axes():
    cam = _FakeCam()
    set_hw_flip(cam, True, True)
    assert set_hw_flip(cam, False, False) is True
    assert cam.hmirror() == 0 and cam.vflip() == 0


def test_hw_flip_reports_failure_when_the_build_ignores_the_write():
    # Some builds accept the call and do nothing. Read-back is what lets the
    # caller fall back to a software rotate instead of serving an upside-down
    # frame while the UI claims the orientation is fixed.
    assert set_hw_flip(_FakeCam(obeys=False), True, True) is False


def test_hw_flip_reports_failure_when_the_accessors_are_absent():
    class NoFlip:
        pass

    assert set_hw_flip(NoFlip(), True, True) is False


# ─── software rotate ──────────────────────────────────────────────────────────

class _FakeImg:
    def __init__(self, w, h):
        self._w, self._h = w, h
        self.calls = []

    def width(self):
        return self._w

    def height(self):
        return self._h

    def rotate(self, angle, w=None, h=None):
        self.calls.append((angle, w, h))
        return _FakeImg(w or self._w, h or self._h)


def test_no_rotation_returns_the_same_object_untouched():
    # The zero case is the common one and runs at 30fps — it must not copy.
    img = _FakeImg(320, 224)
    assert rotate_image(img, 0) is img
    assert img.calls == []


def test_half_turn_keeps_the_frame_shape():
    img = _FakeImg(320, 224)
    out = rotate_image(img, 180)
    assert img.calls == [(180, None, None)]
    assert (out.width(), out.height()) == (320, 224)


def test_quarter_turn_asks_for_the_swapped_canvas():
    # Explicit w/h: MaixPy's default (-1, -1) is build-dependent and can hand
    # back a centre crop of the turned frame instead of the whole thing.
    img = _FakeImg(320, 224)
    out = rotate_image(img, 90)
    assert img.calls == [(90, 224, 320)]
    assert (out.width(), out.height()) == (224, 320)


def test_rotate_falls_back_to_positional_args_on_older_builds():
    # Older MaixPy builds expose rotate(angle, w, h) with no keyword names.
    # Losing the explicit canvas there would hand back a cropped frame.
    class PositionalOnly(_FakeImg):
        def rotate(self, angle, *args, **kwargs):
            if kwargs:
                raise TypeError("rotate() got an unexpected keyword argument 'w'")
            self.calls.append((angle,) + args)
            return _FakeImg(224, 320)

    img = PositionalOnly(320, 224)
    out = rotate_image(img, 90)
    assert img.calls == [(90, 224, 320)]
    assert (out.width(), out.height()) == (224, 320)


def test_rotate_failure_returns_the_original_frame():
    # A rotate error must not stall the AI loop: an un-rotated frame is a bad
    # frame, a dead pipeline is a dead device.
    class Broken(_FakeImg):
        def rotate(self, *a, **k):
            raise RuntimeError("no memory")

    img = Broken(320, 224)
    assert rotate_image(img, 90) is img


def test_rotate_none_is_a_no_op():
    assert rotate_image(None, 180) is None
