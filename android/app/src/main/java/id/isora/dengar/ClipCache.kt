package id.isora.dengar

import java.io.File
import java.io.IOException
import java.security.MessageDigest
import kotlin.math.abs

/**
 * Short clips already heard, kept on the phone so a chime or a "mode explorer"
 * plays the moment it is announced. Without this every press downloads them
 * again, and that download is what stalls: while the glasses load a model
 * their web server takes over a second to hand over a 7 KB chime, even though
 * the announcement itself still arrives within 50 ms.
 *
 * A clip is known by its text and exact length: the glasses scale volume after
 * they publish, so the same line is the same bytes, and a different voice or
 * brand comes out a different length. Anything that does not parse as a clip
 * of the announced length is refused on the way in and deleted on the way out,
 * so a cut-off download cannot keep playing cut off.
 */
class ClipCache(private val dir: File, private val maxBytes: Long = DEFAULT_MAX_BYTES) {

    @Synchronized
    fun get(text: String, ms: Int): ByteArray? {
        if (!cacheable(text, ms)) return null
        val f = fileFor(text, ms)
        val bytes = try {
            f.readBytes()
        } catch (e: IOException) {
            return null
        }
        if (!isWhole(bytes, ms)) {
            f.delete()
            return null
        }
        f.setLastModified(System.currentTimeMillis())
        return bytes
    }

    @Synchronized
    fun put(text: String, ms: Int, bytes: ByteArray) {
        if (!cacheable(text, ms) || !isWhole(bytes, ms)) return
        try {
            dir.mkdirs()
            val tmp = File.createTempFile("clip", ".tmp", dir)
            tmp.writeBytes(bytes)
            if (!tmp.renameTo(fileFor(text, ms))) tmp.delete()
            evict()
        } catch (e: IOException) {
            // Only a speed-up: the clip was still played.
        }
    }

    private fun evict() {
        val files = dir.listFiles { f -> f.name.endsWith(SUFFIX) }?.sortedBy { it.lastModified() } ?: return
        var total = files.sumOf { it.length() }
        for (f in files) {
            if (total <= maxBytes) break
            total -= f.length()
            f.delete()
        }
    }

    private fun fileFor(text: String, ms: Int) = File(dir, keyOf(text, ms) + SUFFIX)

    companion object {
        private const val SUFFIX = ".wav"
        private const val DEFAULT_MAX_BYTES = 16L * 1024 * 1024

        /** Longer than this is a description, not a phrase that comes back. */
        private const val MAX_MS = 6000

        fun cacheable(text: String, ms: Int): Boolean = text.isNotBlank() && ms in 1..MAX_MS

        fun keyOf(text: String, ms: Int): String =
            MessageDigest.getInstance("SHA-256")
                .digest("$ms|$text".toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }

        private fun isWhole(bytes: ByteArray, ms: Int): Boolean = try {
            val w = Wav.parse(bytes)
            abs(w.frames * 1000L / w.sampleRate - ms) <= 1
        } catch (e: IllegalArgumentException) {
            false
        }
    }
}
