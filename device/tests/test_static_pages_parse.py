"""Every inline <script> in the served pages must actually parse.

Why this exists
---------------
buttons.html shipped with one lost backslash:

    'onclick="testVoice('' + v + '')">'      instead of
    'onclick="testVoice(\\'' + v + '\\')">'

The string literal closed early, the file stopped being valid JavaScript, and a
JS parse error takes the ENTIRE <script> block — not just the broken statement.
So nothing on the page ran: poll() never started, the header sat on
"menghubungkan…" forever, and every button was a dead ReferenceError.

Nothing caught it. The page still returned HTTP 200, the device was healthy, and
the browser console showed no error to anyone who attached after load. From the
outside it looked exactly like a network problem, and it was diagnosed twice as
one. The page is the only interface a sighted helper has for a device whose
physical buttons a blind user cannot see, so "it loads but nothing works" is not
a cosmetic failure.

A parser is the only thing that catches this class of bug, so use a real one.
"""

import pathlib
import re
import shutil
import subprocess

import pytest

_STATIC = pathlib.Path(__file__).resolve().parent.parent / "server" / "static"
_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)

_PAGES = sorted(p for p in _STATIC.rglob("*.html") if "assets" not in p.parts)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not installed; JS syntax cannot be checked here",
)


def _inline_scripts(path):
    html = path.read_text(encoding="utf-8", errors="replace")
    return _SCRIPT_RE.findall(html)


def test_there_are_pages_to_check():
    """Guard the guard: a glob that silently matches nothing proves nothing."""
    assert _PAGES, "no static HTML pages found — has the layout moved?"


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.name)
def test_inline_scripts_parse(page, tmp_path):
    blocks = _inline_scripts(page)
    for i, src in enumerate(blocks):
        js = tmp_path / ("%s.%d.js" % (page.stem, i))
        js.write_text(src, encoding="utf-8")
        proc = subprocess.run(
            ["node", "--check", str(js)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, (
            "%s: inline <script> block %d does not parse — the WHOLE block is "
            "dead, not just this line:\n%s" % (page.name, i, proc.stderr.strip())
        )


def test_buttons_page_defines_the_polling_entry_points():
    """The specific symptom: these names must survive to runtime.

    A parse failure anywhere in the block leaves every one of them undefined,
    which is what "menghubungkan…" forever actually means.
    """
    src = "\n".join(_inline_scripts(_STATIC / "buttons.html"))
    for name in ("function poll(", "function tfetch(", "function applyState(",
                 "function press("):
        assert name in src, "buttons.html no longer defines %s" % name
