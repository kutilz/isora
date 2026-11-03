package id.isora.dengar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class WavTest {

    /** The exact layout core/phone_audio.wav_bytes writes. */
    private fun deviceWav(pcm: ByteArray, rate: Int = 24000, format: Int = 1, extra: ByteArray = ByteArray(0)): ByteArray {
        val b = ByteBuffer.allocate(44 + extra.size + pcm.size).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(36 + extra.size + pcm.size).put("WAVE".toByteArray())
        b.put("fmt ".toByteArray()).putInt(16).putShort(format.toShort()).putShort(1)
            .putInt(rate).putInt(rate * 2).putShort(2).putShort(16)
        b.put(extra)
        b.put("data".toByteArray()).putInt(pcm.size).put(pcm)
        return b.array()
    }

    @Test
    fun readsWhatTheGlassesSend() {
        val w = Wav.parse(deviceWav(ByteArray(4800) { it.toByte() }))
        assertEquals(24000, w.sampleRate)
        assertEquals(1, w.channels)
        assertEquals(44, w.offset)
        assertEquals(4800, w.length)
        assertEquals(2400, w.frames)
    }

    @Test
    fun skipsChunksItDoesNotKnowIncludingPadding() {
        // An odd-sized LIST chunk is followed by one pad byte.
        val list = ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN)
            .put("LIST".toByteArray()).putInt(3).put(byteArrayOf(1, 2, 3, 0)).array()
        val w = Wav.parse(deviceWav(ByteArray(100), extra = list))
        assertEquals(44 + 12, w.offset)
        assertEquals(100, w.length)
    }

    @Test
    fun aDownloadCutShortPlaysWhatArrivedInWholeFrames() {
        val full = deviceWav(ByteArray(4000))
        val w = Wav.parse(full.copyOf(44 + 1001))
        assertEquals(1000, w.length)
    }

    @Test
    fun anHtmlErrorPageIsNotAClip() {
        assertThrows(IllegalArgumentException::class.java) { Wav.parse("<html>clip expired</html>".toByteArray()) }
    }

    @Test
    fun floatAudioIsRejectedNotPlayedAsNoise() {
        assertThrows(IllegalArgumentException::class.java) { Wav.parse(deviceWav(ByteArray(100), format = 3)) }
    }

    @Test
    fun anAbsurdChunkSizeEndsTheSearchInsteadOfCrashing() {
        val bogus = ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
            .put("JUNK".toByteArray()).putInt(-16).array() // 0xFFFFFFF0 unsigned
        assertThrows(IllegalArgumentException::class.java) { Wav.parse(deviceWav(ByteArray(100), extra = bogus)) }
    }
}
