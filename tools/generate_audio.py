"""
Audio Generator — PC-side script untuk pre-generate semua file WAV.
Jalankan sekali di laptop sebelum deploy ke MaixCAM.

Requires: pip install gtts
Output:   ../audio/*.wav

Usage:
    python tools/generate_audio.py --from-wordlist
    python tools/generate_audio.py --legacy
    python tools/generate_audio.py --lang id --output ../audio
    python tools/generate_audio.py --dry-run --from-wordlist
"""

import os
import re
import sys
import time
import shutil
import argparse
import subprocess

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "audio")
WORDLIST_DEFAULT = os.path.join(OUTPUT_DIR, "Isora_Audio_Wordlist.md")

# Default time-compression for nav speech — fast screen-reader cadence (T5a / D1).
# atempo is applied at GENERATION time only; the 1-core device never re-tempos.
NAV_SPEECH_RATE = 1.6

# Baris: namafile.wav … → "teks untuk TTS"
_WORDLIST_LINE = re.compile(r"^(\S+\.wav)\s+→\s*\"(.*)\"\s*$")

# ─── Label & Posisi ───────────────────────────────────────────────────────────

# Single source of truth lives in device/config.py (T6). Import it so the
# generator's object set can never drift from the device's RELEVANT_LABELS.
_DEVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "device"))
if _DEVICE_DIR not in sys.path:
    sys.path.insert(0, _DEVICE_DIR)
from config import NAV_OBJECTS as OBJECTS  # noqa: E402  (canonical COCO→id map)

POSITIONS = {
    "left":         "di sebelah kiri",
    "right":        "di sebelah kanan",
    "center":       "di depan",
    "top_left":     "di kiri atas",
    "top_right":    "di kanan atas",
    "top":          "di atas",
    "bottom":       "di bawah",
    "bottom_left":  "di kiri bawah",
    "bottom_right": "di kanan bawah",
}

SYSTEM_EVENTS = {
    # Onboarding / status cues for the screen-less device. Keys match the
    # AudioManager._find_wav safe-name of the spoken text, so these play
    # offline (no gTTS call) at boot and on button-acknowledge.
    "isora_siap_digunakan":       "Isora siap digunakan.",
    "baik_sudah_paham":             "Baik, sudah paham.",
    # Keys must match orchestrator.switch_mode's queue_system(f"mode_{new_mode}"),
    # i.e. mode_explorer / mode_context / mode_qris (NOT *_aktif) so _find_wav
    # resolves system_mode_<x>.wav instead of TTS-speaking the literal key.
    # "idle" is the config/API name for the neutral mode; spoken, "mode diam"
    # is what actually lands in Indonesian — an English word here would be one
    # more thing to decode for someone navigating by ear alone.
    "mode_idle":                    "mode diam",
    "mode_explorer":                "mode penjelajah aktif",
    "mode_context":                 "mode konteks aktif",
    "mode_qris":                    "mode scan bayar aktif",
    # ACTION in explorer: online navigation on/off (orchestrator.toggle_scan).
    # "navigasi", not "mode": it is a switch inside the explorer mode, and a
    # second "mode ..." phrase would sound like the MODE button had cycled.
    "navigasi_daring_aktif":        "navigasi daring aktif",
    "navigasi_daring_mati":         "navigasi daring mati",
    "sedang_menganalisis":          "sedang menganalisis",
    "masih_memproses":              "masih memproses",
    # Cause-aware wait/failure cues. "koneksi_lambat" replaces "masih_memproses"
    # once a call drags past ai_slow_warn_s (likely a slow network). These MUST
    # be pre-generated so the "no internet" message itself never needs internet.
    "koneksi_lambat":               "koneksi internet lambat",
    "tidak_ada_koneksi":            "tidak ada koneksi internet",
    "memindai_kode_pembayaran":     "memindai kode pembayaran",
    # Mode scan bayar (modes/pay_mode.py): one fixed phrase per banknote, keyed
    # by utils/money.cue_key, so naming a note never waits on the network.
    "seribu_rupiah":                "seribu rupiah",
    "dua_ribu_rupiah":              "dua ribu rupiah",
    "lima_ribu_rupiah":             "lima ribu rupiah",
    "sepuluh_ribu_rupiah":          "sepuluh ribu rupiah",
    "dua_puluh_ribu_rupiah":        "dua puluh ribu rupiah",
    "lima_puluh_ribu_rupiah":       "lima puluh ribu rupiah",
    "seratus_ribu_rupiah":          "seratus ribu rupiah",
    # A QR that is not QRIS (a URL, a menu link) held up in scan bayar.
    "bukan_kode_pembayaran":        "bukan kode pembayaran",
    # Panduan arah ke kode QR (utils/qr_guide.py): where the code is, so the head
    # can be turned towards it, all offline. Same keys as qr_guide.ALL_CUES.
    "kode_di_kiri_atas":            "kode di kiri atas",
    "kode_di_atas":                 "kode di atas",
    "kode_di_kanan_atas":           "kode di kanan atas",
    "kode_di_kiri":                 "kode di kiri",
    "kode_di_kanan":                "kode di kanan",
    "kode_di_kiri_bawah":           "kode di kiri bawah",
    "kode_di_bawah":                "kode di bawah",
    "kode_di_kanan_bawah":          "kode di kanan bawah",
    "dekati_kode":                  "dekati kode",
    "kode_pas_pindai_sekarang":     "kode pas, pindai sekarang",
    "kode_hilang":                  "kode hilang",
    "belum_ada_kode_terlihat":      "belum ada kode terlihat",
    "selesai":                      "selesai",
    "koneksi_gagal":                "koneksi gagal",
    "baterai_lemah":                "baterai lemah",
    "tidak_ada_deteksi":            "tidak ada objek terdeteksi",
    "api_tidak_tersedia":           "API tidak tersedia",
    "gagal_menganalisis":           "gagal menganalisis",
    "gagal_memindai":               "gagal memindai, coba lagi",
    # Answers to an ACTION press while the device is still unpaired (see
    # core/onboarding.OnboardingAnnouncer.PAIR_REPLIES). Pre-generated for the
    # same reason as the connection cues above: "belum ada internet" is exactly
    # the moment gTTS cannot be reached, and the rest need to land instantly so
    # the press feels answered rather than ignored.
    "belum_ada_internet_sambungkan_perangkat_ke_wifi_dulu":
        "Belum ada internet. Sambungkan perangkat ke WiFi dulu.",
    "belum_ada_ponsel_yang_menunggu_buka_halaman_tambah_perangkat_dulu_lalu_tekan_lagi":
        "Belum ada ponsel yang menunggu. Buka halaman tambah perangkat dulu, lalu tekan lagi.",
    "ada_lebih_dari_satu_ponsel_yang_menunggu_tutup_salah_satunya_lalu_tekan_lagi":
        "Ada lebih dari satu ponsel yang menunggu. Tutup salah satunya, lalu tekan lagi.",
    "perangkat_ini_sudah_terhubung":
        "Perangkat ini sudah terhubung.",
    "gagal_menghubungkan_coba_tekan_lagi":
        "Gagal menghubungkan. Coba tekan lagi.",
    # onboarding.announce_paired — the moment a pairing demo is judged on.
    "perangkat_sudah_terhubung":    "Perangkat sudah terhubung.",
    # orchestrator: ACTION pressed while the camera is closed (idle mode).
    "kamera_belum_aktif_tekan_mode_dulu":
        "Kamera belum aktif. Tekan tombol mode dulu.",
}


# ─── Non-speech chimes (synthesized offline, no network/gTTS) ─────────────
# These are the device's only non-verbal voice, and the first version made it
# sound broken rather than responsive: constant-amplitude sine bursts, butt-
# joined, each note ramping down to silence before the next ramped up. A flat
# sine held at full level for 90 ms is exactly the waveform cheap electronics
# use to say "fault", and the seam between segments read as a stutter — the
# device sounded like it was glitching, not acknowledging.
#
# What makes a tone read as a CHIME instead of a BEEP:
#   1. Percussive envelope. A struck object is loud for a few ms and then decays
#      — a high crest factor. A flat envelope has none, and the ear files it
#      under "alarm". Every note here is fast attack + exponential ring-out.
#   2. Overlap, not concatenation. Notes sit on a timeline and are MIXED, so a
#      note is still ringing when the next is struck. That is what turns three
#      pitches into a chord instead of three separate bleeps.
#   3. Partials. A pure sine is a test tone. A few decaying overtones above the
#      fundamental (each dying faster than the one below it, as in a real bar or
#      bell) give the warmth that makes it sound like an object, not a circuit.
#   4. Register. The device speaker is a tiny driver with nothing below ~500 Hz;
#      the old error cue's 440->330 Hz fell straight into that hole and came out
#      as a buzz. Everything now sits in 780-1900 Hz, where it is both efficient
#      and easy to hear over street noise.
#
# Synthesized with numpy + stdlib wave — no downloads, no licensing.
_CHIME_RATE      = 48000     # Hz, mono s16 (matches AudioManager PCM target)
_CHIME_PEAK      = 0.55      # peak after normalize; the decay keeps RMS gentle
_CHIME_ATTACK_MS = 4.0       # strike time — longer sounds soft, shorter clicks
_CHIME_LEAD_MS   = 6         # silence before the first strike (ALSA start pop)
_CHIME_TAIL_MS   = 30        # room for the last note to die out naturally

# Partial sets: (frequency_ratio, gain, decay_multiplier). Higher partials must
# decay FASTER (multiplier < 1) — that downward-settling brightness is what the
# ear hears as a struck physical object.
_VOICES = {
    # Soft glass/tube bell: octave plus a slightly stretched twelfth.
    "bell": [(1.0, 1.00, 1.00), (2.0, 0.28, 0.55),
             (3.01, 0.12, 0.34), (4.21, 0.05, 0.20)],
    # Marimba-ish bar: strong 4th partial, everything gone quickly. Used where
    # the cue must be felt as a tap rather than heard as a tone.
    "wood": [(1.0, 1.00, 1.00), (4.0, 0.22, 0.30), (9.2, 0.05, 0.16)],
}

# name -> (voice, [(freq_hz, onset_ms, ring_ms, gain), ...])
# onset_ms is when the note is STRUCK; ring_ms is how long it takes to fade out.
# Overlapping onsets (onset < previous onset + ring) are the point.
CHIMES = {
    # Press ack: one short wooden tap. Must feel instant, so it is the shortest
    # cue here — a long ring on every button press would smear into the speech
    # that follows it.
    "chime_press":    ("wood", [(1568.0, 0, 120, 1.00)]),
    # Mode switch: single neutral bell, no direction implied.
    "chime_mode":     ("bell", [(1174.7, 0, 220, 1.00)]),
    # Capture started: rising fifth, the second note struck while the first rings.
    "chime_capture":  ("bell", [(880.0, 0, 260, 0.85),
                                (1318.5, 70, 340, 1.00)]),
    # Done: C-E-G major triad, arpeggiated fast enough to land as one chord.
    "chime_success":  ("bell", [(1046.5, 0, 300, 0.80),
                                (1318.5, 80, 360, 0.90),
                                (1568.0, 160, 520, 1.00)]),
    # Boot ready: wider, warmer, slower — this one is allowed to sound like an
    # arrival rather than an acknowledgement.
    "chime_ready":    ("bell", [(784.0, 0, 380, 0.75),
                                (1046.5, 110, 420, 0.85),
                                (1568.0, 220, 760, 1.00)]),
    # Failure: descending major third. Falling = something did not work, but at
    # a pitch the speaker reproduces cleanly and with a bell's soft decay, so it
    # informs instead of alarming a user who cannot see what went wrong.
    "chime_error":    ("bell", [(987.8, 0, 320, 0.90),
                                (784.0, 130, 560, 1.00)]),
    # Last-resort obstacle earcon: played when even the generic per-direction
    # phrase is unavailable offline, so a detection is NEVER silent (Decision
    # 4A). Two identical wooden taps — repetition reads as "attention" without
    # borrowing the falling shape that means "error".
    "chime_obstacle": ("wood", [(1174.7, 0, 200, 1.00),
                                (1174.7, 150, 260, 1.00)]),

    # ── Volume mode (both buttons held together) ──────────────────────────────
    # The whole set below is WOOD on purpose. Every bell cue in this file means
    # something happened to the world (a mode changed, a capture ran, an error);
    # volume mode is the one state where the user is adjusting the DEVICE, and a
    # different timbre is what tells them — without a screen — which of the two
    # they are in. Direction is carried by the interval, so up and down stay
    # distinguishable even at the lowest level the buttons can reach.
    #
    # The level itself is not encoded in these cues at all: the step chime is
    # played AT the new volume, so the user hears the setting rather than a
    # number they would have to imagine.
    "chime_vol_enter": ("wood", [(1046.5, 0, 140, 0.85),
                                 (1318.5, 60, 140, 0.92),
                                 (1568.0, 120, 260, 1.00)]),
    "chime_vol_exit":  ("wood", [(1568.0, 0, 140, 1.00),
                                 (1318.5, 60, 140, 0.92),
                                 (1046.5, 120, 300, 0.85)]),
    # One step louder / quieter: two taps, rising or falling. Short — these fire
    # on every tap and a long ring would smear one step into the next.
    "chime_vol_up":    ("wood", [(1318.5, 0, 110, 0.85),
                                 (1760.0, 55, 170, 1.00)]),
    "chime_vol_down":  ("wood", [(1568.0, 0, 110, 0.90),
                                 (1046.5, 55, 190, 1.00)]),
    # Already at the ceiling or the floor: two fast taps on ONE low pitch. No
    # interval = no direction = "that press moved nothing", which is a different
    # message from the error bell (something you asked for failed).
    "chime_vol_limit": ("wood", [(880.0, 0, 130, 1.00),
                                 (880.0, 75, 190, 0.85)]),
    # "I heard you, but I am too busy to take it." A press dropped because the
    # button queue was full used to be completely silent on the device — the
    # only sign was a line of text on a web page, which is exactly what the
    # person holding this cannot read. Measured on hardware: 14% of presses
    # during a mash were dropped this way. Deliberately dull and low, clearly
    # not the bright confirmation tick, so "busy" never reads as "done".
    #
    # Distinguished by RHYTHM, not pitch. Everything below ~700 Hz is under the
    # speaker's rolloff and comes out as a buzz, so "low and dull" is not
    # available on this hardware; and the pitch space is already crowded — a
    # single tap is the press tick, a rising or falling pair is a volume step,
    # a same-pitch pair is the volume limit. Three fast taps is the one rhythm
    # nothing else uses, at the bottom of the audible register so it still
    # reads as a refusal rather than a confirmation.
    "chime_busy":     ("wood", [(740.0, 0, 80, 0.85),
                                (740.0, 90, 80, 0.70),
                                (740.0, 180, 140, 0.55)]),
}


def _note_envelope(n, attack_n, tau_n):
    """Raised-cosine attack into an exponential ring-out, over `n` samples."""
    import numpy as np
    env = np.exp(-np.arange(n) / max(tau_n, 1.0))
    a = min(attack_n, n)
    if a > 1:
        # 0->1 over the attack, smooth at both ends: a linear ramp corners at
        # the top, and that corner is audible as a faint tick at this speed.
        env[:a] *= 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, a))
    return env


def _render_chime(spec):
    """Render a (voice, notes) chime spec into int16 numpy samples.

    Notes are mixed onto one timeline at their onsets so they ring into each
    other, then the whole mix is peak-normalized. Normalizing the SUM (rather
    than scaling each note) is what keeps a three-note chord from clipping while
    a one-note tap still comes out at full level.
    """
    import numpy as np
    voice, notes = spec
    partials = _VOICES[voice]

    lead_n = int(_CHIME_RATE * _CHIME_LEAD_MS / 1000.0)
    tail_n = int(_CHIME_RATE * _CHIME_TAIL_MS / 1000.0)
    span_ms = max((onset + ring) for _f, onset, ring, _g in notes)
    total_n = lead_n + int(_CHIME_RATE * span_ms / 1000.0) + tail_n
    mix = np.zeros(total_n)

    attack_n = int(_CHIME_RATE * _CHIME_ATTACK_MS / 1000.0)
    for freq, onset_ms, ring_ms, gain in notes:
        start = lead_n + int(_CHIME_RATE * onset_ms / 1000.0)
        n = min(int(_CHIME_RATE * ring_ms / 1000.0), total_n - start)
        if n <= 0:
            continue
        t = np.arange(n) / _CHIME_RATE
        # tau = ring/4 leaves the note at ~1.8% of its strike level by ring_ms,
        # i.e. inaudible, so it dies on its own and never needs a hard cut.
        base_tau_n = (_CHIME_RATE * ring_ms / 1000.0) / 4.0
        note = np.zeros(n)
        for ratio, p_gain, p_decay in partials:
            f = freq * ratio
            if f >= _CHIME_RATE / 2:      # never synthesize above Nyquist
                continue
            note += p_gain * np.sin(2 * np.pi * f * t) * _note_envelope(
                n, attack_n, base_tau_n * p_decay
            )
        mix[start:start + n] += gain * note

    peak = np.max(np.abs(mix)) if mix.size else 0.0
    if peak > 0:
        mix *= _CHIME_PEAK / peak
    # Hard-guarantee the tail sits at zero: the ring-out is already inaudible by
    # here, but a non-zero final sample is a click on every single playback.
    fade_n = min(int(_CHIME_RATE * 0.008), mix.size // 2)
    if fade_n > 1:
        mix[-fade_n:] *= np.linspace(1.0, 0.0, fade_n)
    return (mix * 32767.0).astype("<i2")


def synth_chimes(output_dir, dry_run=False):
    """Generate all CHIMES as 48 kHz mono 16-bit WAV in output_dir."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("ERROR: numpy tidak terinstall. Jalankan: pip install numpy")
        sys.exit(1)
    import wave

    os.makedirs(output_dir, exist_ok=True)
    print(f"Akan generate {len(CHIMES)} chime ke: {output_dir}\n")

    generated = 0
    for name, segments in CHIMES.items():
        out_path = os.path.join(output_dir, f"{name}.wav")
        if dry_run:
            voice, notes = segments
            total_ms = max(o + r for _f, o, r, _g in notes)
            print(f"  DRY   {name}.wav -> {voice}, {len(notes)} note(s) "
                  f"({total_ms} ms)")
            continue
        samples = _render_chime(segments)
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_CHIME_RATE)
            w.writeframes(samples.tobytes())
        print(f"  OK    {name}.wav")
        generated += 1

    if not dry_run:
        print(f"\nSelesai! Generated {generated} chime di: {os.path.abspath(output_dir)}")
        print("Selanjutnya: upload folder audio/ ke MaixCAM di /root/audio/")


# ─── atempo speed-up (T5a) ────────────────────────────────────────────────────

def atempo_chain(rate):
    """Return ffmpeg `-filter:a` atempo args for `rate`x time-compression.

    ffmpeg's `atempo` filter only accepts 0.5..2.0 per instance, so rates above
    2.0 are chained (the product of the factors equals `rate`). A rate of 1.0 is
    a no-op → empty list (skip atempo entirely). Pure: no ffmpeg call here.

        atempo_chain(1.0) -> []
        atempo_chain(1.6) -> ["atempo=1.6"]
        atempo_chain(2.5) -> ["atempo=2.0", "atempo=1.25"]
        atempo_chain(4.0) -> ["atempo=2.0", "atempo=2.0"]
    """
    if rate <= 0:
        raise ValueError(f"atempo rate must be > 0, got {rate}")
    if abs(rate - 1.0) < 1e-9:
        return []
    factors = []
    remaining = float(rate)
    while remaining > 2.0 + 1e-9:
        factors.append(2.0)
        remaining /= 2.0
    factors.append(remaining)
    return [f"atempo={_fmt_rate(f)}" for f in factors]


def _fmt_rate(f):
    """Format an atempo factor: trims float noise, always keeps >=1 decimal.

    2.0 -> "2.0", 1.25 -> "1.25", 1.5999999 -> "1.6".
    """
    s = f"{round(f, 6):.6f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def nav_tier_filenames(tiers, objects=None, positions=None):
    """Planned WAV filenames for distance-tier nav variants (offline coverage).

    The policy lane (Decision 5) qualifies a phrase with a coarse distance tier
    (near/far). Those need their own pre-rendered WAVs, named
    `obj_<label>_<pos>_<tier>.wav`. Returns the full enumerated set so the
    coverage invariant (device/tests/test_phrase_coverage.py) can gate on it.
    """
    objects = objects if objects is not None else OBJECTS
    positions = positions if positions is not None else POSITIONS
    names = []
    for obj_key in objects:
        for pos_key in positions:
            for tier in tiers:
                names.append(f"obj_{obj_key}_{pos_key}_{tier}.wav")
    return names


def build_audio_list():
    """Buat list semua (filename, text) yang perlu di-generate."""
    items = []

    # Object detection audio. The plain `obj_<label>_<pos>.wav` doubles as the
    # FAR-tier phrase (runtime falls back to it when no `_far` file exists), so
    # we only render an extra NEAR variant that appends "dekat" for the urgency
    # cue the assessment asked for ("orang di depan dekat").
    for obj_key, obj_id in OBJECTS.items():
        for pos_key, pos_id in POSITIONS.items():
            items.append((f"obj_{obj_key}_{pos_key}.wav", f"{obj_id} {pos_id}"))
            items.append((f"obj_{obj_key}_{pos_key}_near.wav",
                          f"{obj_id} {pos_id} dekat"))

    # Generic per-direction fallback ("ada objek di depan"): spoken when a
    # specific label's WAV is missing while OFFLINE, so a blind user never gets
    # silence on a real detection (Decision 4A). One per position, label-agnostic.
    for pos_key, pos_id in POSITIONS.items():
        items.append((f"objek_{pos_key}.wav", f"ada objek {pos_id}"))

    # System events
    for event_key, event_text in SYSTEM_EVENTS.items():
        filename = f"system_{event_key}.wav"
        items.append((filename, event_text))

    return items


def _is_nav_phrase(filename):
    """Object/nav phrases get time-compressed; system cues stay normal speed."""
    return filename.startswith("obj_")


def _apply_atempo(path, rate):
    """Time-compress the WAV at `path` in place by `rate` via ffmpeg atempo.

    On ANY failure (no ffmpeg, atempo error, empty output) the original
    normal-speed WAV is left untouched — never silence (Decision: atempo failure
    → fall back to normal-speed PCM). Returns True if sped up, False if fell back.
    """
    chain = atempo_chain(rate)
    if not chain:
        return False  # rate == 1.0 → nothing to do

    if shutil.which("ffmpeg") is None:
        print(f"        atempo SKIP (ffmpeg not found) — kept normal speed: {os.path.basename(path)}")
        return False

    tmp_path = path + ".atempo.wav"
    cmd = ["ffmpeg", "-y", "-i", path, "-filter:a", ",".join(chain), tmp_path]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0 or not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            print(f"        atempo FAIL — kept normal speed: {os.path.basename(path)}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False
        os.replace(tmp_path, path)
        return True
    except Exception as e:  # noqa: BLE001 — never let a render error become silence
        print(f"        atempo FAIL ({e}) — kept normal speed: {os.path.basename(path)}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def parse_wordlist_markdown(md_path):
    """
    Baca audio/Isora_Audio_Wordlist.md — baris pola:
    system_ready.wav                → "Isora siap digunakan"
    """
    items = []
    seen = set()
    with open(md_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            m = _WORDLIST_LINE.match(line)
            if not m:
                continue
            filename, text = m.group(1), m.group(2)
            if filename in seen:
                continue
            seen.add(filename)
            items.append((filename, text))
    return items


def generate_all(items, output_dir, lang="id", dry_run=False, delay=0.5,
                 nav_speech_rate=NAV_SPEECH_RATE):
    try:
        from gtts import gTTS
    except ImportError:
        print("ERROR: gTTS tidak terinstall. Jalankan: pip install gtts")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Akan generate {len(items)} file WAV ke: {output_dir}")
    print(f"Lang: {lang} | Dry run: {dry_run} | Nav speed: {nav_speech_rate}x\n")

    existing = 0
    generated = 0
    failed = 0

    for i, (filename, text) in enumerate(items):
        out_path = os.path.join(output_dir, filename)

        if os.path.exists(out_path):
            print(f"  [{i+1:3d}/{len(items)}] SKIP  {filename}")
            existing += 1
            continue

        if dry_run:
            print(f"  [{i+1:3d}/{len(items)}] DRY   {filename} -> \"{text}\"")
            continue

        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(out_path)
            # Nav phrases get screen-reader cadence at generation time. atempo
            # failure falls back to the normal-speed WAV — never silence.
            if _is_nav_phrase(filename) and nav_speech_rate and nav_speech_rate != 1.0:
                _apply_atempo(out_path, nav_speech_rate)
            print(f"  [{i+1:3d}/{len(items)}] OK    {filename} -> \"{text}\"")
            generated += 1
            time.sleep(delay)  # Jeda untuk hindari rate limit
        except Exception as e:
            print(f"  [{i+1:3d}/{len(items)}] FAIL  {filename} -> {e}")
            failed += 1

    print(f"\nSelesai!")
    print(f"  Generated : {generated}")
    print(f"  Skipped   : {existing}")
    print(f"  Failed    : {failed}")
    print(f"  Total     : {len(items)}")

    if not dry_run and generated > 0:
        print(f"\nFile tersimpan di: {os.path.abspath(output_dir)}")
        print("Selanjutnya: upload folder audio/ ke MaixCAM di /root/audio/")
        print("  Gunakan: python tools/deploy.py --audio-only")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="I-Sora Audio Generator (gTTS)")
    parser.add_argument("--output", default=OUTPUT_DIR, help="Output directory")
    parser.add_argument("--lang", default="id", help="Language code (default: id)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay antar request (default: 0.5s)")
    parser.add_argument(
        "--speed",
        type=float,
        default=NAV_SPEECH_RATE,
        metavar="RATE",
        help=f"Nav-speech atempo rate at generation time (default: {NAV_SPEECH_RATE}x; 1.0 = normal)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List saja tanpa generate")
    parser.add_argument(
        "--from-wordlist",
        nargs="?",
        const=WORDLIST_DEFAULT,
        default=None,
        metavar="PATH",
        help=f"Generate dari Markdown wordlist (default: {WORDLIST_DEFAULT})",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Pola lama: kombinasi objek×posisi + system_* pendek",
    )
    parser.add_argument(
        "--chimes",
        action="store_true",
        help="Synthesize non-speech chimes (numpy, offline) — no gTTS",
    )
    args = parser.parse_args()

    if sum(bool(x) for x in (args.legacy, args.from_wordlist, args.chimes)) > 1:
        print("ERROR: pilih salah satu --legacy / --from-wordlist / --chimes")
        sys.exit(1)

    if args.chimes:
        synth_chimes(args.output, dry_run=args.dry_run)
        sys.exit(0)

    if args.from_wordlist:
        wl_path = args.from_wordlist
        if not os.path.isfile(wl_path):
            print(f"ERROR: Wordlist tidak ditemukan: {wl_path}")
            sys.exit(1)
        audio_items = parse_wordlist_markdown(wl_path)
        print(f"Sumber wordlist: {wl_path} ({len(audio_items)} entri)\n")
    else:
        audio_items = build_audio_list()

    generate_all(
        items=audio_items,
        output_dir=args.output,
        lang=args.lang,
        dry_run=args.dry_run,
        delay=args.delay,
        nav_speech_rate=args.speed,
    )
