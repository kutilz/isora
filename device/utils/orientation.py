"""Camera orientation — quarter-turn rotation of the live frame.

Why this exists
───────────────
The device is worn/mounted, and the mount angle is not fixed: clipped to a
chest strap it sits upright, hung the other way round it sits upside down, and
on a cane/bag strap it can end up on its side. A rotated sensor makes every
downstream signal wrong — "orang di kiri atas" comes out as "kanan bawah", the
ground-contact distance hint reads the sky, and the collected dataset is
unusable. So the correction belongs at the frame source, once, not in each
consumer.

`camera_rotation` (0/90/180/270, clockwise, persisted in /root/config.json)
survives a power cycle: the helper re-mounts the device once and it stays fixed.

Two ways to apply it
────────────────────
  180° → hardware. The sensor ISP can mirror horizontally and flip vertically;
         doing both IS a half turn, costs zero CPU, and never touches the frame
         buffer. This is the common case (device hung upside down), so it gets
         the free path when the MaixPy build exposes hmirror()/vflip().
  90/270° (or 180° on a build without the ISP controls) → software
         `image.rotate()`. A quarter turn also SWAPS the frame axes, which is
         why `rotated_dims()` exists: every consumer that normalizes a bbox
         (position_from_bbox, area_ratio, the ground-contact hint) must divide
         by the dimensions of the frame it actually got, not the configured
         capture size.

Everything except `rotate_image`/`set_hw_flip` is pure, so the geometry is
unit-testable without MaixPy or a camera.
"""

VALID_ROTATIONS = (0, 90, 180, 270)


def normalize_rotation(value) -> int:
    """Coerce anything into one of 0/90/180/270 (clockwise degrees).

    Snaps to the nearest quarter turn and wraps, so -90 → 270 and 450 → 90.
    Junk (None, "", "kiri", NaN) → 0: an unreadable orientation must leave the
    camera alone, never guess a turn the user did not ask for.
    """
    try:
        deg = float(value)
    except (TypeError, ValueError):
        return 0
    if deg != deg or deg in (float("inf"), float("-inf")):   # NaN / inf
        return 0
    return int(round(deg / 90.0)) * 90 % 360


def swaps_axes(rotation) -> bool:
    """True when this rotation turns a landscape frame into a portrait one."""
    return normalize_rotation(rotation) in (90, 270)


def rotated_dims(width: int, height: int, rotation) -> tuple:
    """(width, height) of the frame AFTER `rotation` is applied."""
    return (height, width) if swaps_axes(rotation) else (width, height)


def rotation_label(rotation) -> str:
    """Short human label for logs and the web UI."""
    rot = normalize_rotation(rotation)
    return "normal" if rot == 0 else f"{rot}°"


# ─── Hardware path (ISP mirror/flip) ──────────────────────────────────────────

def set_hw_flip(cam, hmirror: bool, vflip: bool) -> bool:
    """Best-effort ISP mirror/flip. True only when BOTH settings read back.

    MaixPy exposes these as get/set-in-one accessors (`cam.hmirror(1)` sets,
    `cam.hmirror()` reads) but not every build ships them, and a build can
    accept the call and ignore it. Verifying the read-back is what lets the
    caller fall back to a software rotate instead of silently serving an
    upside-down frame while the UI claims it fixed the orientation.
    """
    try:
        cam.hmirror(1 if hmirror else 0)
        cam.vflip(1 if vflip else 0)
        return bool(cam.hmirror()) == hmirror and bool(cam.vflip()) == vflip
    except Exception:
        return False


# ─── Software path ────────────────────────────────────────────────────────────

def rotate_image(img, rotation):
    """Return `img` turned `rotation` degrees clockwise (same object when 0).

    The target canvas is passed explicitly for quarter turns so the result is
    the full swapped-axis frame rather than a centre crop of it — MaixPy's
    default (w=-1, h=-1) is build-dependent. Older builds without the w/h
    keywords raise TypeError; those get the positional-only call. Any failure
    returns the original frame: a correctly-oriented pipeline stalling on a
    rotate error would be a far worse outcome than a rotated frame.
    """
    rot = normalize_rotation(rotation)
    if rot == 0 or img is None:
        return img
    try:
        if swaps_axes(rot):
            w = int(img.height())
            h = int(img.width())
            try:
                return img.rotate(rot, w=w, h=h)
            except TypeError:
                return img.rotate(rot, w, h)
        return img.rotate(rot)
    except Exception:
        return img
