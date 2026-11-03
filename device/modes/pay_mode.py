"""
Pay Mode — mode "qris", spoken "mode scan bayar". Banknotes and QR codes, in turns.

Every tick reads one camera frame and spends it on ONE of two looks:

  money  the banknote YOLO (cfg["money_model_path"]) on the NPU, ~10 ms
  qr     find a QR code in the frame, read it if it is close enough

so each look gets every other frame. That halves how fast either reacts, which
this mode can afford — nobody is walking into anything while they pay — and it
keeps the tick as short as an explorer tick.

What is said:
  - a banknote, once, when it shows up: "lima puluh ribu rupiah" — a
    pre-generated WAV (utils/money.cue_key), so it needs no network;
  - where a QR code is, until the head is turned to it: "kode di kanan bawah",
    "dekati kode", "kode pas, pindai sekarang" (utils/qr_guide). The phone does
    the actual payment; what a blind person cannot do is aim it;
  - a QRIS code close enough to decode: merchant + nominal (utils/qris_verify);
  - any other QR: "bukan kode pembayaran".
ACTION says where the code is right now, or that none is in view.

All of it runs on the device, with no network. There used to be a second, online
QRIS scan behind ACTION; it took ~8 s, stalled the loop, and answered a question
the decoder had already answered exactly.

Nothing is announced over other audio. Arrivals wait in the trackers until the
speaker is quiet, so the mode confirmation and a QRIS sentence are never cut,
and an arrival that lands mid-sentence is said after it instead of dropped.
"""

import time

from config import cfg
from utils.money import PresenceTracker, cue_key, is_qris_payload
from utils.qr_guide import CUE_READY, QrGuide


class PayScanner:
    """Turn-taking and announcement state for scan bayar. Pure state: the
    camera and NPU work stays in run_pay_tick, on the AI loop."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Fresh state; called on every mode switch, which is also when live
        cfg changes to the thresholds below are picked up."""
        self._turn = 0
        self.money = PresenceTracker(
            min_streak=cfg.get("money_min_streak", 3),
            gone_s=cfg.get("money_gone_s", 1.5),
            min_gap_s=cfg.get("money_repeat_gap_s", 4.0),
        )
        # A decoded QR is exact, so one sighting is enough. It is gone only
        # after a longer absence: the decoder misses frames of a code that is
        # still being held up, and every miss must not re-arm the sentence.
        self.qr = PresenceTracker(
            min_streak=1,
            gone_s=cfg.get("qris_gone_s", 4.0),
            min_gap_s=cfg.get("qris_repeat_gap_s", 10.0),
        )
        self.guide = QrGuide()

    def next_turn(self) -> str:
        self._turn += 1
        return "money" if self._turn % 2 else "qr"


def run_pay_tick(orch):
    """One scan-bayar cycle: read a frame, take this tick's look, announce."""
    engine = orch.ai_engine
    if engine is None:
        time.sleep(0.1)
        return

    # Camera read + dashboard preview. The nav pipeline inside stays off: the
    # NPU holds the banknote model in this mode, not the COCO one.
    _, _, latency = engine.capture_and_infer()
    pay = orch.pay
    now = time.monotonic()

    if pay.next_turn() == "money":
        t0 = time.time()
        dets = engine.detect_money()
        if latency:
            latency = dict(latency, inference_ms=round((time.time() - t0) * 1000))
        orch.detections = dets
        pay.money.update({d["nominal"] for d in dets if d.get("nominal")}, now)
    else:
        sighting = engine.locate_qr()
        pay.guide.update(sighting, now)
        pay.qr.update([sighting.payload] if sighting and sighting.payload else [], now)
    if latency:
        orch.latency = latency

    announce(orch, now)


def announce(orch, now: float):
    """Say what has arrived, one thing per quiet moment, QRIS first."""
    am = orch.audio_manager
    if am is None or not am.is_quiet():
        return
    pay = orch.pay

    for payload in pay.qr.take(now):
        if is_qris_payload(payload):
            _say_qris(orch, payload)
            return
        cloud = getattr(orch, "cloud", None)
        if cloud is not None and cloud.wants_qr_scan():
            continue            # the pairing QR the device is waiting for
        am.queue_system("bukan_kode_pembayaran")
        return

    cue = pay.guide.next_cue(now)
    if cue:
        orch.logger.info(f"Panduan QR: {cue}", module="PayMode")
        if cue == CUE_READY:
            am.queue_cue("chime_success.wav")
        am.queue_system(cue)
        orch.ai_engine.save_guide_photo(cue)
        return

    # A code in view means a sticker, a stand or a screen: the banknote model
    # has called a blue QRIS card "lima puluh ribu" (4 Nov, isora-810f).
    if pay.guide.visible:
        return

    # Several notes at once (a payment fanned out in the hand): largest first,
    # each its own short cue, all queued together so they play back to back.
    for value in sorted(pay.money.take(now), reverse=True):
        orch.logger.ok(f"Uang terdeteksi: {value}", module="PayMode")
        am.queue_system(cue_key(value))


def _say_qris(orch, payload: str):
    from utils.qris_verify import (format_audio_message, parse_qris_payload,
                                   verify_against_ai)
    verified = verify_against_ai(parse_qris_payload(payload), ai_text="")
    text, _safe = format_audio_message(verified, cap=cfg.QRIS_NOMINAL_WARN_CAP)
    orch.logger.ok(f"QRIS(scan): {text}", module="PayMode")
    am = orch.audio_manager
    am.queue_cue("chime_success.wav")
    am.queue_info(text)
