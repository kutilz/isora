package id.isora.dengar

/**
 * A 16-bit PCM WAV clip as the glasses send it (core/phone_audio.wav_bytes:
 * mono, 24 kHz). Points into the downloaded bytes instead of copying them.
 */
class Wav private constructor(
    val bytes: ByteArray,
    val offset: Int,
    val length: Int,
    val sampleRate: Int,
    val channels: Int,
) {
    val frameBytes: Int get() = 2 * channels
    val frames: Int get() = length / frameBytes

    companion object {
        /** @throws IllegalArgumentException when this is not a WAV that can be played. */
        fun parse(b: ByteArray): Wav {
            require(b.size >= 12 && tag(b, 0) == "RIFF" && tag(b, 8) == "WAVE") { "not a WAV file" }
            var format = 0
            var channels = 0
            var rate = 0
            var bits = 0
            // Long: a chunk size is unsigned 32-bit, and a corrupt one must not wrap around.
            var pos = 12L
            while (pos + 8 <= b.size) {
                val at = pos.toInt()
                val size = le32(b, at + 4)
                val body = pos + 8
                when (tag(b, at)) {
                    "fmt " -> {
                        require(size >= 16 && body + 16 <= b.size) { "short fmt chunk" }
                        val f = body.toInt()
                        format = le16(b, f)
                        channels = le16(b, f + 2)
                        rate = le32(b, f + 4).toInt()
                        bits = le16(b, f + 14)
                    }
                    "data" -> {
                        require(format == 1 && bits == 16 && channels in 1..2 && rate in 4000..192000) {
                            "unsupported WAV (format $format, $bits bit, $channels ch, $rate Hz)"
                        }
                        // A download cut short plays what arrived, in whole frames.
                        var len = minOf(size, b.size - body).toInt()
                        len -= len % (2 * channels)
                        return Wav(b, body.toInt(), len, rate, channels)
                    }
                }
                pos = body + size + (size and 1L)   // chunks are padded to even sizes
            }
            throw IllegalArgumentException("no data chunk")
        }

        private fun tag(b: ByteArray, at: Int) = String(b, at, 4, Charsets.US_ASCII)

        private fun le16(b: ByteArray, at: Int) =
            (b[at].toInt() and 0xff) or ((b[at + 1].toInt() and 0xff) shl 8)

        private fun le32(b: ByteArray, at: Int): Long =
            le16(b, at).toLong() or (le16(b, at + 2).toLong() shl 16)
    }
}
