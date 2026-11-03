package id.isora.dengar

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack

/**
 * Plays clips one after another on the media stream — the stream Android
 * sends to whatever earphones or speaker are connected. Used from one
 * thread only (the session's player thread), so the AudioTrack is never
 * touched concurrently; cutting a clip short goes through keepGoing().
 *
 * Between clips the track keeps running on silence (see silence()). Two delays
 * come from letting it stop: Bluetooth audio goes to sleep and takes a moment
 * to wake, and a stopped track does not start again until its buffer is full,
 * which a 156 ms chime alone never does.
 */
class ClipPlayer(context: Context) {
    private val audio = context.getSystemService(AudioManager::class.java)
    private val attributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()

    // Lowers music for a sentence instead of pausing it.
    private val focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(attributes)
        .build()

    private val zeros = ByteArray(SILENCE_BYTES)
    private var track: AudioTrack? = null
    private var rate = 0
    private var channels = 0
    private var written = 0L // frames handed to the track since its last flush
    private var focused = false

    /** Blocks until the clip has been heard, or cuts it off as soon as keepGoing() turns false. */
    fun play(w: Wav, keepGoing: () -> Boolean) {
        val t = trackFor(w.sampleRate, w.channels)
        if (!focused) {
            audio.requestAudioFocus(focus)
            focused = true
        }
        if (t.playState != AudioTrack.PLAYSTATE_PLAYING) t.play()
        val end = w.offset + w.length
        var off = w.offset
        while (off < end) {
            if (!keepGoing()) return cut(t)
            val n = t.write(w.bytes, off, minOf(CHUNK, end - off), AudioTrack.WRITE_NON_BLOCKING)
            if (n < 0) return cut(t)
            if (n == 0) {
                Thread.sleep(10)
            } else {
                off += n
                written += n / w.frameBytes
            }
        }
        // write() only queues. Wait until the last frame has actually played,
        // so the next clip and the "stop" that may follow line up with the ear.
        val last = written
        val deadline = System.nanoTime() + (w.frames * 1000L / w.sampleRate + 2000) * 1_000_000
        while (framesAhead(last, t.playbackHeadPosition) > 0 && System.nanoTime() < deadline) {
            if (!keepGoing()) return cut(t)
            writeSilence(t)
        }
    }

    /**
     * Nothing to play right now: keep the track and the Bluetooth link awake.
     * Call in a loop; it tops the track up and returns within about [IDLE_SLEEP_MS].
     *
     * @throws IllegalStateException when the track died; release() and carry on.
     */
    fun silence() {
        val t = track ?: trackFor(IDLE_RATE, 1)
        if (t.playState != AudioTrack.PLAYSTATE_PLAYING) t.play()
        writeSilence(t)
    }

    /** Nothing more to say for now: give the audio focus back. The track keeps running. */
    fun idle() {
        if (focused) {
            audio.abandonAudioFocusRequest(focus)
            focused = false
        }
    }

    fun release() {
        idle()
        track?.release()
        track = null
        written = 0
    }

    private fun writeSilence(t: AudioTrack) {
        val n = t.write(zeros, 0, zeros.size, AudioTrack.WRITE_NON_BLOCKING)
        when {
            n < 0 -> throw IllegalStateException("AudioTrack write failed: $n")
            n == 0 -> Thread.sleep(IDLE_SLEEP_MS)
            else -> written += n / (2 * channels)
        }
    }

    private fun cut(t: AudioTrack) {
        t.pause()
        t.flush()
        written = 0
    }

    private fun trackFor(r: Int, ch: Int): AudioTrack {
        track?.let { if (r == rate && ch == channels) return it }
        track?.release()
        val mask = if (ch == 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
        val min = AudioTrack.getMinBufferSize(r, mask, AudioFormat.ENCODING_PCM_16BIT)
        val t = AudioTrack.Builder()
            .setAudioAttributes(attributes)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(r)
                    .setChannelMask(mask)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build(),
            )
            .setBufferSizeInBytes(maxOf(min * 2, r * 2 * ch / 4)) // at least 250 ms
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        // Silence queued ahead of a clip delays it, so only a little is queued.
        t.setBufferSizeInFrames(maxOf(min / (2 * ch), r * QUEUED_MS / 1000))
        track = t
        rate = r
        channels = ch
        written = 0
        return t
    }

    companion object {
        private const val CHUNK = 8192
        private const val IDLE_RATE = 24000 // what the glasses send (core/phone_audio._OUT_RATE)
        private const val QUEUED_MS = 100
        private const val IDLE_SLEEP_MS = 20L
        private const val SILENCE_BYTES = 2048

        /**
         * Frames between [target] and the play head, where the head is a 32-bit
         * counter that wraps. Compared the same way so a track running for two
         * days does not read as forever behind.
         */
        fun framesAhead(target: Long, head: Int): Int = target.toInt() - head
    }
}
