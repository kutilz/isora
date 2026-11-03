package id.isora.dengar

import org.junit.Assert.assertEquals
import org.junit.Test

class ClipPlayerTest {

    @Test
    fun framesStillToPlay() {
        assertEquals(100, ClipPlayer.framesAhead(1100L, 1000))
        assertEquals(0, ClipPlayer.framesAhead(1000L, 1000))
        assertEquals(-5, ClipPlayer.framesAhead(1000L, 1005))
    }

    @Test
    fun aTrackRunningPastThe32BitCounterIsNotForeverBehind() {
        // 2^32 frames at 24 kHz is just under two days of keeping the track awake.
        val wrapped = (1L shl 32) + 50
        assertEquals(50, ClipPlayer.framesAhead(wrapped, 0))
        assertEquals(0, ClipPlayer.framesAhead(wrapped, 50))
        assertEquals(10, ClipPlayer.framesAhead(1L shl 32, -10))
    }
}
