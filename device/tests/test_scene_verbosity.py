"""Scene-description verbosity selector: the /buttons toggle flips
scene_verbosity, and PROMPT_SCENE must return the matching prompt. Detail is
the safe default for any unknown value (never accidentally go terse)."""

from config import select_scene_prompt


def test_detail_is_default_for_unknown_or_detail():
    assert select_scene_prompt("detail", "SHORT", "LONG") == "LONG"
    assert select_scene_prompt("", "SHORT", "LONG") == "LONG"
    assert select_scene_prompt("garbage", "SHORT", "LONG") == "LONG"


def test_sedang_selects_the_short_prompt():
    assert select_scene_prompt("sedang", "SHORT", "LONG") == "SHORT"
