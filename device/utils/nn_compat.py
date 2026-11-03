"""maix.nn build compatibility — pick the detector class this image actually has.

MaixPy 4.5.x ships `YOLOv5`/`YOLOv8` only; `nn.YOLO11` was added in a later
build. Hardcoding one class breaks on whichever image the unit happens to run —
the benchmark suite did exactly that and could not start on a 4.5.1 unit while
the app itself ran fine, because only `AIEngine` carried the fallback.

The `.mud`'s `model_type` is the source of truth for what the weights are; the
fallback order then degrades to whatever the build exposes. `maix` is imported
lazily so this module also imports on a PC (tests, tooling) with no MaixPy.
"""

PREFERRED = {
    "yolo11": ("YOLO11", "YOLOv8", "YOLOv5"),
    "yolov8": ("YOLOv8", "YOLO11", "YOLOv5"),
    "yolov5": ("YOLOv5", "YOLOv8", "YOLO11"),
}
DEFAULT_ORDER = ("YOLO11", "YOLOv8", "YOLOv5")


def model_type(model_path) -> str:
    """Read `model_type` out of a .mud file. Empty string when unreadable."""
    try:
        with open(model_path) as f:
            for line in f:
                if line.strip().startswith("model_type"):
                    return line.split("=", 1)[1].strip().lower()
    except Exception:
        pass
    return ""


def detector_class(model_path):
    """Return `(cls, name)` — the maix.nn class matching the .mud that exists here."""
    from maix import nn

    order = PREFERRED.get(model_type(model_path), DEFAULT_ORDER)
    for name in order:
        cls = getattr(nn, name, None)
        if cls is not None:
            return cls, name
    raise RuntimeError("maix.nn exposes no usable YOLO class")


def load_detector(model_path):
    """Construct the detector for `model_path`. Returns `(detector, class_name)`."""
    cls, name = detector_class(model_path)
    return cls(model=model_path), name
