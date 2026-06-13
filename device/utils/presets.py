"""
Mode presets — quick-tuning bundles for Explorer / Scene / QRIS modes.

A preset is a small dict of config-key → value pairs that get merged
into cfg via cfg.update() when applied. Names are stable identifiers;
labels are shown in the dashboard dropdown.

Adding a new preset: edit PRESETS below — no code changes required
elsewhere. The dashboard discovers presets via GET /presets.
"""

from typing import Dict, List


PRESETS: Dict[str, Dict[str, dict]] = {
    # ── Explorer (YOLO live detection) ──────────────────────────────────────
    "explorer": {
        "default": {
            "label":  "Default",
            "desc":   "Threshold standar, FPS penuh, jangkauan deteksi seimbang.",
            "values": {
                "conf_threshold":        0.50,
                "iou_threshold":         0.45,
                "danger_area_threshold": 0.15,
                "camera_fps":            30,
                "snapshot_interval_ms":  500,
                "audio_cooldown_s":      2.0,
            },
        },
        "high_sensitivity": {
            "label":  "Sensitivitas Tinggi",
            "desc":   "Threshold lebih rendah, lebih banyak deteksi (lebih noisy, baik untuk ruangan ramai).",
            "values": {
                "conf_threshold":        0.35,
                "iou_threshold":         0.40,
                "danger_area_threshold": 0.10,
                "camera_fps":            30,
                "snapshot_interval_ms":  400,
                "audio_cooldown_s":      1.5,
            },
        },
        "battery_saver": {
            "label":  "Hemat Baterai",
            "desc":   "FPS lebih rendah + cooldown audio panjang. Untuk pemakaian outdoor lama.",
            "values": {
                "conf_threshold":        0.55,
                "iou_threshold":         0.50,
                "danger_area_threshold": 0.18,
                "camera_fps":            15,
                "snapshot_interval_ms":  1000,
                "audio_cooldown_s":      3.5,
            },
        },
        "indoor_quiet": {
            "label":  "Indoor Tenang",
            "desc":   "Audio cooldown panjang + threshold tinggi — minim notifikasi, untuk rumah.",
            "values": {
                "conf_threshold":        0.60,
                "iou_threshold":         0.50,
                "danger_area_threshold": 0.20,
                "camera_fps":            20,
                "snapshot_interval_ms":  700,
                "audio_cooldown_s":      4.0,
            },
        },
    },

    # ── Scene description ──────────────────────────────────────────────────
    "scene": {
        "default": {
            "label":  "Default",
            "desc":   "Deskripsi singkat 2 kalimat, timeout 15s.",
            "values": {
                "ai_timeout_s":  15,
                "prompt_scene": (
                    "Deskripsikan scene ini secara singkat dalam Bahasa Indonesia, "
                    "fokus pada objek yang relevan untuk pengguna tunanetra. "
                    "Maksimal 2 kalimat."
                ),
            },
        },
        "detailed": {
            "label":  "Detail",
            "desc":   "Deskripsi lebih panjang, posisi objek dieja, timeout 20s.",
            "values": {
                "ai_timeout_s":  20,
                "prompt_scene": (
                    "Deskripsikan adegan ini dalam Bahasa Indonesia untuk pengguna tunanetra. "
                    "Sebutkan posisi setiap objek penting (kiri/tengah/kanan, dekat/jauh) "
                    "dan aktivitas yang sedang terjadi. Maksimal 4 kalimat."
                ),
            },
        },
        "brief": {
            "label":  "Ringkas",
            "desc":   "Satu kalimat ultra-pendek. Timeout 8s — cocok untuk jaringan tidak stabil.",
            "values": {
                "ai_timeout_s":  8,
                "prompt_scene": (
                    "Sebut objek paling penting di scene dalam satu kalimat Bahasa Indonesia. "
                    "Maksimal 12 kata."
                ),
            },
        },
        "navigation": {
            "label":  "Navigasi",
            "desc":   "Fokus pada hambatan, jalur, dan arah. Timeout 15s.",
            "values": {
                "ai_timeout_s":  15,
                "prompt_scene": (
                    "Saya pengguna tunanetra. Sebut hambatan dan jalur yang aman dalam "
                    "Bahasa Indonesia: arah, jarak relatif, dan bahaya. Maksimal 3 kalimat."
                ),
            },
        },
    },

    # ── QRIS ───────────────────────────────────────────────────────────────
    "qris": {
        "hybrid_verified": {
            "label":  "Hybrid (default, aman)",
            "desc":   "Decode lokal + AI cross-check. Dianjurkan untuk pilot.",
            "values": {
                "qris_mode":             "hybrid",
                "ai_timeout_s":          12,
                "qris_nominal_warn_cap": 1_000_000,
            },
        },
        "offline_only": {
            "label":  "Offline (tanpa AI)",
            "desc":   "Decode lokal pakai pyzbar saja — tanpa internet. Nominal apa adanya.",
            "values": {
                "qris_mode":             "offline",
                "qris_nominal_warn_cap": 1_000_000,
            },
        },
        "online_only": {
            "label":  "Online (AI Vision)",
            "desc":   "Pakai AI vision penuh — info merchant lebih kaya, butuh internet.",
            "values": {
                "qris_mode":             "online",
                "ai_timeout_s":          15,
                "qris_nominal_warn_cap": 1_000_000,
            },
        },
        "small_tx": {
            "label":  "Transaksi Kecil",
            "desc":   "Hybrid + cap nominal 100rb (waspadai jika di atas).",
            "values": {
                "qris_mode":             "hybrid",
                "ai_timeout_s":          10,
                "qris_nominal_warn_cap": 100_000,
            },
        },
    },
}


def list_presets() -> dict:
    """Return {mode: [{name, label, desc, values}, ...]} for the dashboard."""
    out: Dict[str, List[dict]] = {}
    for mode, mp in PRESETS.items():
        out[mode] = []
        for name, body in mp.items():
            out[mode].append({
                "name":   name,
                "label":  body["label"],
                "desc":   body["desc"],
                "values": body["values"],
            })
    return out


def get_preset(mode: str, name: str) -> dict:
    """Return the values dict for one preset, or {} if unknown."""
    return PRESETS.get(mode, {}).get(name, {}).get("values", {})


def apply_preset(mode: str, name: str) -> dict:
    """
    Apply preset to live config. Returns the values that were merged
    (empty dict if preset unknown).
    """
    from config import cfg
    values = get_preset(mode, name)
    if not values:
        return {}
    cfg.update(values)
    return values
