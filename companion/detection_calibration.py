"""
Logika kalibrasi deteksi (dipakai companion webserver).
Memfilter objek + menyesuaikan peringatan «terlalu dekat» agar tidak spam untuk barang meja.
"""

from __future__ import annotations

# Default: tidak peringatkan «terlalu dekat» untuk barang statis umum (COCO English)
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

# Label umum untuk UI checklist (subset COCO + urut)
COCO_CALIBRATION_LABELS: list[str] = sorted(
    set(
        DEFAULT_PROXIMITY_EXEMPT_LABELS
        + [
            "person",
            "bicycle",
            "car",
            "motorcycle",
            "airplane",
            "bus",
            "train",
            "truck",
            "boat",
            "traffic light",
            "fire hydrant",
            "stop sign",
            "parking meter",
            "bench",
            "bird",
            "cat",
            "dog",
            "horse",
            "sheep",
            "cow",
            "elephant",
            "bear",
            "zebra",
            "giraffe",
            "backpack",
            "umbrella",
            "handbag",
            "tie",
            "suitcase",
            "frisbee",
            "skis",
            "snowboard",
            "sports ball",
            "kite",
            "baseball bat",
            "baseball glove",
            "skateboard",
            "surfboard",
            "tennis racket",
            "fork",
            "knife",
            "spoon",
            "bowl",
            "banana",
            "apple",
            "sandwich",
            "orange",
            "broccoli",
            "carrot",
            "hot dog",
            "pizza",
            "donut",
            "cake",
        ]
    )
)


def default_settings_dict() -> dict:
    return {
        "conf_threshold": 0.45,
        "iou_threshold": 0.45,
        "blur_threshold": 50.0,
        "show_bbox": True,
        "proximity_alerts": True,
        "proximity_area_ratio": 0.82,
        "ignored_labels": [],
        "detection_allowlist": [],
        "use_detection_allowlist": False,
        "proximity_exempt_labels": list(DEFAULT_PROXIMITY_EXEMPT_LABELS),
    }


def normalize_label_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Pisah koma / baris baru agar label multi-kata (mis. "cell phone") tetap utuh
        raw = value.replace("\n", ",").split(",")
        return [p.strip().lower() for p in raw if p.strip()]
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    return []


def merge_settings_post(current: dict, data: dict) -> dict:
    """Gabungkan POST /api/settings ke salinan current."""
    out = dict(current)
    floats = ("conf_threshold", "iou_threshold", "blur_threshold", "proximity_area_ratio")
    for k in floats:
        if k in data and data[k] is not None:
            out[k] = round(float(data[k]), 4)
    bools = ("show_bbox", "proximity_alerts", "use_detection_allowlist")
    for k in bools:
        if k in data:
            out[k] = bool(data[k])
    lists = ("ignored_labels", "detection_allowlist", "proximity_exempt_labels")
    for k in lists:
        if k in data:
            out[k] = normalize_label_list(data[k])
    return out


def _lab(o: dict) -> str:
    return (o.get("label") or "").strip().lower()


def prepare_objects(objects: list | None, settings: dict) -> list[dict]:
    """
    1) Buang ignored_labels
    2) Optional allowlist (jika use_detection_allowlist True dan detection_allowlist tidak kosong)
    3) Sesuaikan warning: exempt / proximity mati / ratio area
    """
    if not objects:
        return []
    ignored = set(normalize_label_list(settings.get("ignored_labels")))
    allow = normalize_label_list(settings.get("detection_allowlist"))
    use_allow = bool(settings.get("use_detection_allowlist")) and len(allow) > 0
    allow_set = set(allow) if use_allow else None

    proximity_on = bool(settings.get("proximity_alerts", True))
    ratio_th = float(settings.get("proximity_area_ratio", 0.82))
    exempt = set(normalize_label_list(settings.get("proximity_exempt_labels")))

    out: list[dict] = []
    for o in objects:
        if not isinstance(o, dict):
            continue
        lab = _lab(o)
        if not lab or lab in ignored:
            continue
        if allow_set is not None and lab not in allow_set:
            continue
        oc = dict(o)
        if not proximity_on or lab in exempt:
            oc["warning"] = "aman"
        else:
            ar = oc.get("area_ratio")
            try:
                arf = float(ar) if ar is not None else None
            except (TypeError, ValueError):
                arf = None
            if arf is not None:
                oc["warning"] = "terlalu dekat" if arf > ratio_th else "aman"
            # tanpa area_ratio: pertahankan warning dari perangkat (sudah tak exempt)
        out.append(oc)
    return out


def parse_remote_settings(d: dict | None) -> dict:
    """Parse settings (sama bentuk dengan device/detection_calibration.py untuk runner desktop)."""
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
