"""
Kalibrasi deteksi — dipakai di MaixCAM (aural_maix.py).
Diselaraskan dengan companion/detection_calibration.py (nilai default sama).
"""

from __future__ import annotations

DEFAULT_PROXIMITY_EXEMPT_LABELS: list[str] = [
    "keyboard",
    "mouse",
    "cell phone",
    "laptop",
    "tv",
    "remote",
    "cup",
    "wine glass",
    "bottle",
    "book",
    "clock",
    "vase",
    "chair",
    "couch",
    "bed",
    "dining table",
    "toilet",
    "sink",
    "refrigerator",
    "microwave",
    "oven",
    "toaster",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
    "potted plant",
]


def normalize_label_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace("\n", ",").split(",")
        return [x.strip().lower() for x in raw if x.strip()]
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    return []


def parse_remote_settings(d: dict | None) -> dict:
    """Parse JSON settings dari companion (/api/ping)."""
    d = d or {}
    ex = normalize_label_list(d.get("proximity_exempt_labels"))
    if not ex:
        ex = list(DEFAULT_PROXIMITY_EXEMPT_LABELS)
    return {
        "conf_threshold": float(d.get("conf_threshold", 0.45)),
        "iou_threshold": float(d.get("iou_threshold", 0.45)),
        "blur_threshold": float(d.get("blur_threshold", 50.0)),
        "proximity_alerts": bool(d.get("proximity_alerts", True)),
        "proximity_area_ratio": float(d.get("proximity_area_ratio", 0.82)),
        "ignored_labels": set(normalize_label_list(d.get("ignored_labels"))),
        "detection_allowlist": normalize_label_list(d.get("detection_allowlist")),
        "use_detection_allowlist": bool(d.get("use_detection_allowlist", False)),
        "proximity_exempt_labels": set(ex),
    }
