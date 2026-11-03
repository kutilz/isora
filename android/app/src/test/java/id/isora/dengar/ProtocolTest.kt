package id.isora.dengar

import org.json.JSONException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolTest {

    @Test
    fun aPollAnswerAsTheGlassesSendIt() {
        // Captured from aural-88dd on 2026-10-21.
        val r = Protocol.parsePoll(
            """{"seq": 1, "events": [{"type": "clip", "id": 1, "ms": 5304, "text": "Di depan ada seorang pria berkacamata berdiri dekat meja komputer.", "seq": 1}], "device_muted": true}""",
        )
        assertEquals(1, r.seq)
        assertTrue(r.deviceMuted)
        assertEquals(listOf(PollEvent("clip", 1, "Di depan ada seorang pria berkacamata berdiri dekat meja komputer.", 5304)), r.events)
    }

    @Test
    fun aQuietPoll() {
        val r = Protocol.parsePoll("""{"seq": 0, "events": [], "device_muted": false}""")
        assertEquals(0, r.seq)
        assertFalse(r.deviceMuted)
        assertTrue(r.events.isEmpty())
    }

    @Test
    fun aStopEvent() {
        val r = Protocol.parsePoll("""{"seq": 5, "events": [{"type": "stop", "seq": 5}], "device_muted": true}""")
        assertEquals(listOf(PollEvent("stop", -1, "")), r.events)
    }

    @Test(expected = JSONException::class)
    fun somethingElseIsNotAPollAnswer() {
        Protocol.parsePoll("<html>busy</html>")
    }

    @Test
    fun theSameCallsTheWebPageMakes() {
        assertEquals("/listen/poll?client=hp-1&since=-1&mute=1", Protocol.pollPath("hp-1", -1, true))
        assertEquals("/listen/poll?client=hp-1&since=7&mute=0", Protocol.pollPath("hp-1", 7, false))
        assertEquals("/listen/clip/12.wav", Protocol.clipPath(12))
        assertEquals("""{"client":"hp-1"}""", Protocol.leaveBody("hp-1"))
    }

    @Test
    fun statusOfTheGlassesNamesThem() {
        val status = """{"mode": "idle", "device_id": "88dd", "device_name": "isora-88dd", "mdns_host": "isora-88dd.local", "brand": "auralai"}"""
        assertEquals(DeviceIdentity("88dd", "isora-88dd"), Protocol.parseIdentity(status))
    }

    @Test
    fun aNamelessUnitFallsBackToItsMdnsName() {
        val status = """{"mode": "idle", "device_id": "88dd", "device_name": "", "mdns_host": "isora-88dd.local"}"""
        assertEquals("isora-88dd", Protocol.parseIdentity(status)?.name)
    }

    @Test
    fun otherServersOnPort8080AreNotGlasses() {
        assertNull(Protocol.parseIdentity("""{"status": "ok"}"""))
        assertNull(Protocol.parseIdentity("""{"device_id": "x"}"""))
        assertNull(Protocol.parseIdentity("<html>router login</html>"))
        assertNull(Protocol.parseIdentity("[]"))
    }
}
