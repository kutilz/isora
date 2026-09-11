"""A slow connection and a missing one must not say the same thing.

The device used to announce "tidak ada koneksi" for any adapter failure whose
message contained "timed out" — which on a phone hotspot is the COMMON case,
and is false: the link is up, it just didn't finish in ai_timeout_s. A blind
user acting on that goes looking for WiFi that was never down.
"""

import pytest

from core.ai_engine import _net_failure_cue, _net_failure_kind


@pytest.mark.parametrize("msg", [
    "<urlopen error [Errno -2] Name or service not known>",
    "<urlopen error [Errno -3] Temporary failure in name resolution>",
    "<urlopen error [Errno 111] Connection refused>",
    "<urlopen error [Errno 101] Network is unreachable>",
    "<urlopen error [Errno 113] No route to host>",
])
def test_unreachable_says_there_is_no_connection(msg):
    assert _net_failure_kind(Exception(msg)) == "down"
    assert _net_failure_cue(Exception(msg), "gagal_menganalisis") == "tidak_ada_koneksi"


@pytest.mark.parametrize("msg", [
    "<urlopen error timed out>",
    "The read operation timed out",
    "<urlopen error _ssl.c:1112: The handshake operation timed out>",
    "[Errno 104] Connection reset by peer",
    "Connection aborted",
])
def test_a_link_that_is_merely_slow_says_so(msg):
    assert _net_failure_kind(Exception(msg)) == "slow"
    assert _net_failure_cue(Exception(msg), "gagal_menganalisis") == "koneksi_lambat"


@pytest.mark.parametrize("msg", [
    "OpenAI HTTP 429: rate limit exceeded",
    "OpenAI HTTP 401: invalid api key",
    "No output_text in OpenAI response",
    "openai_api_key not configured",
])
def test_a_far_end_failure_is_not_blamed_on_the_network(msg):
    """The network carried the request fine; saying otherwise sends the user
    to fix the wrong thing."""
    assert _net_failure_kind(Exception(msg)) is None
    assert _net_failure_cue(Exception(msg), "gagal_menganalisis") == "gagal_menganalisis"
    assert _net_failure_cue(Exception(msg), "gagal_memindai") == "gagal_memindai"
