package id.isora.dengar

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files

class ClipCacheTest {
    private lateinit var dir: File

    @Before
    fun setUp() {
        dir = Files.createTempDirectory("clips").toFile()
    }

    /** What core/phone_audio.wav_bytes sends: mono, 24 kHz. */
    private fun wav(ms: Int, fill: Byte = 7): ByteArray {
        val n = 24 * ms * 2
        val b = ByteBuffer.allocate(44 + n).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()).putInt(36 + n).put("WAVE".toByteArray())
        b.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
            .putInt(24000).putInt(48000).putShort(2).putShort(16)
        b.put("data".toByteArray()).putInt(n)
        repeat(n) { b.put(fill) }
        return b.array()
    }

    @Test
    fun aStoredClipComesBack() {
        val c = ClipCache(dir)
        val w = wav(156)
        c.put("chime_press.wav", 156, w)
        assertArrayEquals(w, c.get("chime_press.wav", 156))
    }

    @Test
    fun theSameLineAtAnotherLengthIsAnotherClip() {
        val c = ClipCache(dir)
        c.put("mode explorer", 2352, wav(2352))
        assertNull(c.get("mode explorer", 2000))
    }

    @Test
    fun aCutOffDownloadIsNotKept() {
        val c = ClipCache(dir)
        c.put("mode explorer", 2352, wav(2352).copyOf(4000))
        assertNull(c.get("mode explorer", 2352))
    }

    @Test
    fun aDamagedFileIsDroppedInsteadOfPlayed() {
        val c = ClipCache(dir)
        c.put("atur volume", 1344, wav(1344))
        val f = dir.listFiles()!!.single()
        f.writeBytes(ByteArray(100))
        assertNull(c.get("atur volume", 1344))
        assertEquals(0, dir.listFiles()!!.size)
    }

    @Test
    fun descriptionsAndNamelessClipsAreNotStored() {
        val c = ClipCache(dir)
        c.put("sebuah deskripsi panjang", 9000, wav(9000))
        c.put("", 156, wav(156))
        assertEquals(0, dir.listFiles()!!.size)
    }

    @Test
    fun theOldestGoFirstWhenFull() {
        val w = wav(1000) // 48 KB
        val c = ClipCache(dir, maxBytes = w.size * 2L + 10)
        c.put("satu", 1000, wav(1000, 1))
        File(dir, ClipCache.keyOf("satu", 1000) + ".wav").setLastModified(1_000_000L)
        c.put("dua", 1000, wav(1000, 2))
        File(dir, ClipCache.keyOf("dua", 1000) + ".wav").setLastModified(2_000_000L)
        c.put("tiga", 1000, wav(1000, 3))
        assertNull(c.get("satu", 1000))
        assertNotNull(c.get("dua", 1000))
        assertNotNull(c.get("tiga", 1000))
    }
}
