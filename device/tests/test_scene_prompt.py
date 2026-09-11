"""Guards for the scene-description prompt pack.

The prompt IS the product here: it is the only thing standing between a blind
user and a describe button that re-words the world on every press, narrates the
wall behind the banknote they are holding, and says "ada meja dan kursi" in a
chemistry lab. These tests pin the three clauses that fix each of those, and
the migration that actually gets them onto a device already in the field.
"""

import json

import pytest

from config import migrate_prompt_pack, select_scene_prompt
from utils import scene_prompt as sp


# ── The three contracts the prompt has to carry ──────────────────────────────

ALL_PROMPTS = [
    sp.SCENE_PROMPT_DETAIL,
    sp.SCENE_PROMPT_SEDANG,
    sp.SCENE_PROMPT_BACA,
    sp.SCENE_PROMPT_NAVIGASI,
]
# Without ids pytest names each case after the whole 4 KB prompt.
ALL_IDS = ["detail", "sedang", "baca", "navigasi"]


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=ALL_IDS)
def test_every_prompt_pins_a_consistency_rule(prompt):
    # Same frame, same answer. Without this the model paraphrases itself, which
    # reads as a changed world AND misses the per-word TTS cache every time.
    low = prompt.lower()
    assert "gambar yang sama" in low
    assert "persis sama" in low


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=ALL_IDS)
def test_every_prompt_forbids_guessing_from_an_unclear_shape(prompt):
    # A pile of cloth was twice announced as "seekor kucing belang putih-cokelat"
    # on isora-bfe2. At 320x224 an ambiguous blob is the normal case, not the
    # edge case, and a confident wrong noun is worse than a vague right one.
    low = prompt.lower()
    assert "sebut hanya yang benar-benar" in low
    assert "menebak hewan" in low


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=ALL_IDS)
def test_every_prompt_has_a_deterministic_tie_break(prompt):
    """The ladder alone does not pin an order.

    Measured on isora-bfe2: four calls on the SAME jpeg bytes returned the same
    four objects in four different orders, because with no held object and no
    hazard everything lands on one rung and the rung had no internal ordering
    rule. Nearest-first, then leftmost, is what makes repeat answers line up.
    """
    low = prompt.lower()
    assert "paling banyak dua benda" in low
    assert "paling dekat" in low and "kiri" in low


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=ALL_IDS)
def test_every_prompt_bans_photo_talk(prompt):
    low = prompt.lower()
    assert "sepertinya" in low and "mungkin" in low


@pytest.mark.parametrize("prompt", [sp.SCENE_PROMPT_DETAIL,
                                    sp.SCENE_PROMPT_SEDANG,
                                    sp.SCENE_PROMPT_BACA],
                         ids=["detail", "sedang", "baca"])
def test_held_object_outranks_the_background(prompt):
    """The pegang-uang bug: the answer must be about the held object, and the
    background must be explicitly off-limits — not merely unmentioned."""
    low = prompt.lower()
    assert "dipegang" in low
    assert "belakangnya" in low            # "jangan sebut apa pun di belakangnya"
    assert "hanya benda itu" in low


def test_detail_ladder_is_ordered_held_then_hazard_then_people_then_room():
    p = sp.SCENE_PROMPT_DETAIL
    order = [p.index(m) for m in ("1. BENDA YANG DIPEGANG",
                                  "2. BAHAYA",
                                  "3. ORANG",
                                  "4. ISI TEMPAT")]
    assert order == sorted(order)


def test_hazard_can_still_interrupt_a_held_object_answer():
    # A ladder that stops at level 1 must not swallow "there is a step down in
    # front of you" just because the user happens to be holding something.
    assert "PENGECUALIAN" in sp.SCENE_PROMPT_DETAIL


def test_navigasi_puts_hazards_first_and_drops_the_held_object():
    p = sp.SCENE_PROMPT_NAVIGASI
    assert p.index("1. BAHAYA") < p.index("2. JALUR")
    assert "BENDA YANG DIPEGANG" not in p


def test_baca_never_falls_back_to_describing_the_room():
    p = sp.SCENE_PROMPT_BACA.lower()
    assert "jangan mendeskripsikan ruangan" in p
    assert "4. isi tempat" not in p


@pytest.mark.parametrize("setting", [
    "papan tulis",        # kelas / ruang kuliah
    "laboratorium",       # lab / bengkel
    "tangga",             # koridor & tangga
    "kasir",              # kantin / warung
    "trotoar",            # pinggir jalan
])
def test_environment_checklist_covers_the_daily_settings(setting):
    # The point of the checklist is relevance, not location guessing.
    assert setting in sp.SCENE_PROMPT_DETAIL.lower()


def test_environment_checklist_forbids_naming_the_place():
    low = sp.SCENE_PROMPT_DETAIL.lower()
    assert "jangan menebak atau menyebut nama" in low


def test_closed_lexicon_is_declared():
    # A fixed direction/distance vocabulary is what makes repeat answers cache
    # hits instead of fresh gTTS synths.
    low = sp.SCENE_PROMPT_DETAIL.lower()
    assert "arah hanya boleh memakai kata" in low
    assert "jarak hanya boleh memakai kata" in low


def test_sedang_stays_short_enough_to_be_the_fast_path():
    # It exists to be cheap. If it grows to detail-prompt size it has no reason
    # to exist at all.
    assert len(sp.SCENE_PROMPT_SEDANG) < len(sp.SCENE_PROMPT_DETAIL) / 3


# ── Verbosity selection (unchanged behavior, re-pinned against the pack) ─────

def test_verbosity_selects_from_the_pack():
    assert select_scene_prompt(
        "sedang", sp.SCENE_PROMPT_SEDANG, sp.SCENE_PROMPT_DETAIL
    ) is sp.SCENE_PROMPT_SEDANG
    assert select_scene_prompt(
        "detail", sp.SCENE_PROMPT_SEDANG, sp.SCENE_PROMPT_DETAIL
    ) is sp.SCENE_PROMPT_DETAIL


# ── Migration: getting the new pack onto a unit already in the field ────────

def test_stale_default_is_upgraded():
    # Config._load merges the saved file OVER _DEFAULTS, so without this a
    # pilot unit keeps its old prompt forever and the fix never ships.
    stored = {
        "prompt_scene": "Deskripsikan scene ini secara singkat dalam Bahasa "
                        "Indonesia, fokus pada objek yang relevan untuk "
                        "pengguna tunanetra. Maksimal 2 kalimat.",
    }
    changes = migrate_prompt_pack(stored)
    assert changes["prompt_scene"] == sp.SCENE_PROMPT_DETAIL
    assert changes["prompt_pack_version"] == sp.PROMPT_PACK_VERSION


def test_live_tuned_default_on_the_pilot_units_is_upgraded():
    # This exact string was pushed to the pilot units over POST /config; it is
    # a default we shipped, not something the operator wrote.
    stored = {
        "prompt_scene": "Kamu adalah mata bagi pengguna tunanetra. Langsung "
                        "sebutkan objek, orang, dan situasi penting di depan "
                        "dalam 1 sampai 2 kalimat Bahasa Indonesia yang "
                        "ringkas dan jelas. Jangan menyebut bahwa ini foto "
                        "atau gambar, dan jangan mengomentari kualitas, "
                        "pencahayaan, atau keburaman gambar.",
    }
    assert migrate_prompt_pack(stored)["prompt_scene"] == sp.SCENE_PROMPT_DETAIL


def test_operator_written_prompt_is_never_overwritten():
    # Their edit outranks our default. Silently reverting it looks exactly like
    # the dashboard field not saving.
    stored = {
        "prompt_scene":        "Sebut warna baju orang di depan saja.",
        "prompt_scene_sedang": "Satu kata saja.",
    }
    changes = migrate_prompt_pack(stored)
    assert "prompt_scene" not in changes
    assert "prompt_scene_sedang" not in changes
    assert changes == {"prompt_pack_version": sp.PROMPT_PACK_VERSION}


def test_empty_prompt_is_treated_as_no_prompt():
    changes = migrate_prompt_pack({"prompt_scene": "", "prompt_scene_sedang": ""})
    assert changes["prompt_scene"] == sp.SCENE_PROMPT_DETAIL
    assert changes["prompt_scene_sedang"] == sp.SCENE_PROMPT_SEDANG


def test_current_pack_is_a_no_op():
    # Nothing to write means no disk write on every boot.
    assert migrate_prompt_pack({
        "prompt_pack_version": sp.PROMPT_PACK_VERSION,
        "prompt_scene": "anything at all",
    }) == {}


def test_junk_version_is_treated_as_ancient():
    changes = migrate_prompt_pack({"prompt_pack_version": "v2", "prompt_scene": ""})
    assert changes["prompt_scene"] == sp.SCENE_PROMPT_DETAIL


def test_whitespace_and_case_differences_still_match_a_shipped_default():
    # A prompt round-tripped through the dashboard textarea comes back
    # re-wrapped; that must not disguise it as a user edit.
    stored = {"prompt_scene": "  deskripsikan   scene ini secara singkat dalam\n"
                              "bahasa indonesia, fokus pada objek yang relevan "
                              "untuk pengguna tunanetra.   maksimal 2 kalimat. "}
    assert migrate_prompt_pack(stored)["prompt_scene"] == sp.SCENE_PROMPT_DETAIL


# ── The migration has to see the FILE, not the merged config ────────────────

def test_stale_unit_is_migrated_on_load(tmp_path, monkeypatch):
    """Regression: migrating off the merged dict is a silent no-op.

    _DEFAULTS already carries the current prompt_pack_version, so a merge of
    file-over-defaults always looks up to date. Reading the version from there
    meant every unit in the field kept its old prompt and the fix shipped to
    nobody — confirmed on isora-bfe2 before this was corrected.
    """
    import config as config_mod
    from config import Config

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "device_token": "keep-me",
        "prompt_scene": "Deskripsikan scene ini secara singkat dalam Bahasa "
                        "Indonesia, fokus pada objek yang relevan untuk "
                        "pengguna tunanetra. Maksimal 2 kalimat.",
    }))
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", p)

    c = Config()

    assert c.PROMPT_SCENE == sp.SCENE_PROMPT_DETAIL
    assert c.get("device_token") == "keep-me"      # nothing else disturbed
    # And it is persisted, so the next boot is a no-op rather than a re-write.
    on_disk = json.loads(p.read_text())
    assert on_disk["prompt_pack_version"] == sp.PROMPT_PACK_VERSION
    assert on_disk["prompt_scene"] == sp.SCENE_PROMPT_DETAIL


def test_up_to_date_unit_is_not_rewritten_on_load(tmp_path, monkeypatch):
    import config as config_mod
    from config import Config

    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "prompt_pack_version": sp.PROMPT_PACK_VERSION,
        "prompt_scene": "prompt bikinan operator",
    }))
    monkeypatch.setattr(config_mod, "_CONFIG_PATH", p)
    before = p.stat().st_mtime_ns

    c = Config()

    assert c.PROMPT_SCENE == "prompt bikinan operator"
    assert p.stat().st_mtime_ns == before
