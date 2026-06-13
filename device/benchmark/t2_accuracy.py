#!/usr/bin/env python3
"""
Test 2 — Detection Accuracy & Recall
=====================================
Mengukur Precision dan Recall YOLO pada dataset gambar berlabel.

Format dataset:
  /root/test_images/
    person_001.jpg
    person_002.jpg
    car_001.jpg
    ...
  Label dari nama file: kata pertama sebelum underscore/titik.
  Alternatif: simpan file /root/test_images/labels.json dengan format:
    {"person_001.jpg": ["person"], "car_001.jpg": ["car", "truck"]}

Standar Kelulusan:
  Recall objek kritis (person/car/motorcycle/bus/truck) >= 95%

Score:
  recall_kritis × 100, capped at 100

Jika tidak ada test images:
  Test dilewati (skipped=True), score = None (tidak dihitung di index)
"""

import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_IMAGES_DIR  = "/root/test_images"
LABELS_JSON      = os.path.join(TEST_IMAGES_DIR, "labels.json")
RESULTS_FILE     = "/root/logs/bench_t2_accuracy.json"
RECALL_THRESHOLD = 0.95

CRITICAL_LABELS = {"person", "car", "motorcycle", "bus", "truck", "bicycle"}

SETUP_INSTRUCTIONS = """
  ── Setup Test Dataset ────────────────────────────────────
  Buat direktori /root/test_images/ dan isi dengan JPEG.
  Opsi 1 — Nama file:
    Nama file = label_id.jpg, misal: person_001.jpg, car_002.jpg
    Label diambil dari kata pertama sebelum '_' atau '.'
  Opsi 2 — labels.json:
    Buat file /root/test_images/labels.json:
    {
      "person_001.jpg": ["person"],
      "car_002.jpg":    ["car"],
      "scene_001.jpg":  ["person", "bicycle"]
    }
  Minimal 20 gambar dianjurkan untuk hasil yang representatif.
  ─────────────────────────────────────────────────────────
"""


def _make_emit(cb=None):
    def emit(text="", tag="plain"):
        if cb:
            cb(text, tag)
        print(text, flush=True)
    return emit


def _load_labels() -> dict:
    """
    Return dict: filename → list[str] expected_labels.
    Prioritizes labels.json if it exists; falls back to filename parsing.
    """
    if os.path.exists(LABELS_JSON):
        with open(LABELS_JSON) as f:
            return json.load(f)

    if not os.path.isdir(TEST_IMAGES_DIR):
        return {}

    labels = {}
    for fname in os.listdir(TEST_IMAGES_DIR):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        base  = os.path.splitext(fname)[0]
        label = base.split("_")[0].split("-")[0].lower()
        labels[fname] = [label]

    return labels


def _load_image_maix(path: str):
    """Load image via maix.image for direct NPU input."""
    from maix import image as mi
    img = mi.Image(path)
    return img


def _load_image_opencv(path: str):
    """Fallback: load via OpenCV and convert to bytes."""
    import cv2
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"Cannot read: {path}")
    return img


def run(emit_cb=None) -> dict:
    emit = _make_emit(emit_cb)

    emit("═" * 64, "div")
    emit("T2  DETECTION ACCURACY & RECALL", "section")
    emit("═" * 64, "div")

    # ── Load dataset ──────────────────────────────────────────────────────────
    ground_truth = _load_labels()

    if not ground_truth:
        emit(SETUP_INSTRUCTIONS, "warn")
        emit("  ⚠ Tidak ada test images — T2 dilewati", "warn")
        result = {
            "test":    "T2_Accuracy",
            "skipped": True,
            "score":   None,
            "passed":  None,
            "reason":  "No test images found in " + TEST_IMAGES_DIR,
            "setup":   SETUP_INSTRUCTIONS.strip(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save(result)
        return result

    emit(f"  Dataset: {len(ground_truth)} gambar di {TEST_IMAGES_DIR}")
    emit(f"  Recall threshold (critical): {RECALL_THRESHOLD:.0%}")

    # ── Import maix ───────────────────────────────────────────────────────────
    try:
        from maix import nn, image as mi
        MAIX = True
    except ImportError:
        MAIX = False

    if not MAIX:
        emit("  ✗ maix not available", "err")
        return {"test": "T2_Accuracy", "passed": False, "score": 0,
                "error": "maix not available"}

    try:
        from config import cfg, COCO_LABEL_MAP, RELEVANT_LABELS
        detector = nn.YOLO11(model=cfg.MODEL_PATH)
        emit(f"  Model: {cfg.MODEL_PATH}", "ok")
    except Exception as e:
        emit(f"  ✗ Model init failed: {e}", "err")
        return {"test": "T2_Accuracy", "passed": False, "score": 0, "error": str(e)}

    # ── Run inference on each image ───────────────────────────────────────────
    per_label_tp: dict = {}   # label → true positives
    per_label_fn: dict = {}   # label → false negatives
    per_label_fp: dict = {}   # label → false positives

    total_images  = 0
    failed_images = 0

    emit()
    for fname, expected_labels in sorted(ground_truth.items()):
        fpath = os.path.join(TEST_IMAGES_DIR, fname)
        if not os.path.exists(fpath):
            emit(f"  ⚠ File tidak ada: {fname}", "warn")
            continue

        try:
            img    = _load_image_maix(fpath)
            result = detector.detect(
                img,
                conf_th=cfg.CONF_THRESHOLD,
                iou_th=cfg.IOU_THRESHOLD,
            )
            detected_labels = set(
                COCO_LABEL_MAP.get(det.class_id, "")
                for det in result
            ) - {""}

            expected_set = set(expected_labels)
            total_images += 1

            for lbl in expected_set:
                per_label_tp.setdefault(lbl, 0)
                per_label_fn.setdefault(lbl, 0)
                if lbl in detected_labels:
                    per_label_tp[lbl] += 1
                else:
                    per_label_fn[lbl] += 1

            for lbl in detected_labels:
                per_label_fp.setdefault(lbl, 0)
                if lbl not in expected_set:
                    per_label_fp[lbl] += 1

        except Exception as e:
            emit(f"  ⚠ {fname}: {e}", "warn")
            failed_images += 1

    if total_images == 0:
        emit("  ✗ Tidak ada gambar yang berhasil diproses", "err")
        return {"test": "T2_Accuracy", "passed": False, "score": 0,
                "error": "All images failed to process"}

    # ── Compute per-label metrics ─────────────────────────────────────────────
    all_labels = set(per_label_tp) | set(per_label_fn)
    per_label  = {}

    emit(f"\n  {'Label':<20} {'Recall':>8} {'Precision':>10} {'TP':>5} {'FN':>5} {'FP':>5}")
    emit(f"  {'─'*20} {'─'*8} {'─'*10} {'─'*5} {'─'*5} {'─'*5}")

    for lbl in sorted(all_labels):
        tp = per_label_tp.get(lbl, 0)
        fn = per_label_fn.get(lbl, 0)
        fp = per_label_fp.get(lbl, 0)
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        per_label[lbl] = {"recall": recall, "precision": precision,
                          "tp": tp, "fn": fn, "fp": fp}
        flag = " *" if lbl in CRITICAL_LABELS else ""
        emit(f"  {lbl+flag:<20} {recall:>7.1%}  {precision:>9.1%}  {tp:>5} {fn:>5} {fp:>5}")

    emit(f"\n  (* = critical label)")

    # ── Critical label recall ─────────────────────────────────────────────────
    critical_in_dataset = {l for l in CRITICAL_LABELS if l in per_label}

    if critical_in_dataset:
        critical_recalls = [per_label[l]["recall"] for l in critical_in_dataset]
        avg_critical_recall = sum(critical_recalls) / len(critical_recalls)
        min_critical_recall = min(critical_recalls)
        emit(f"\n  Critical labels present in dataset: {sorted(critical_in_dataset)}")
        emit(f"  Avg recall (critical): {avg_critical_recall:.1%}")
        emit(f"  Min recall (critical): {min_critical_recall:.1%}")
        passed = min_critical_recall >= RECALL_THRESHOLD
    else:
        emit("\n  ⚠ Tidak ada critical labels dalam dataset — menggunakan recall rata-rata semua label")
        all_recalls = [v["recall"] for v in per_label.values()]
        avg_critical_recall = sum(all_recalls) / len(all_recalls) if all_recalls else 0
        min_critical_recall = avg_critical_recall
        passed = avg_critical_recall >= RECALL_THRESHOLD

    # ── Overall precision ──────────────────────────────────────────────────────
    all_tp = sum(v["tp"] for v in per_label.values())
    all_fp = sum(per_label_fp.get(l, 0) for l in per_label)
    all_fn = sum(v["fn"] for v in per_label.values())
    overall_precision = all_tp / (all_tp + all_fp) if (all_tp + all_fp) > 0 else 0
    overall_recall    = all_tp / (all_tp + all_fn) if (all_tp + all_fn) > 0 else 0

    emit(f"\n  {'Overall precision':<30} {overall_precision:.1%}")
    emit(f"  {'Overall recall':<30} {overall_recall:.1%}")
    emit()

    tag   = "ok" if passed else "err"
    emoji = "✓" if passed else "✗"
    emit(f"  {emoji} Min critical recall {min_critical_recall:.1%} — "
         f"{'PASS' if passed else 'FAIL'} (threshold {RECALL_THRESHOLD:.0%})", tag)

    score = min(100, round(min_critical_recall * 100))
    emit(f"  Score: {score}/100")

    results = {
        "test":               "T2_Accuracy",
        "passed":             passed,
        "score":              score,
        "total_images":       total_images,
        "failed_images":      failed_images,
        "per_label":          per_label,
        "avg_critical_recall": round(avg_critical_recall, 4),
        "min_critical_recall": round(min_critical_recall, 4),
        "overall_recall":     round(overall_recall, 4),
        "overall_precision":  round(overall_precision, 4),
        "recall_threshold":   RECALL_THRESHOLD,
        "critical_labels":    sorted(CRITICAL_LABELS),
        "timestamp":          time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    _save(results)
    return results


def _save(results: dict):
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run()
