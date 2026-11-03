package id.isora.dengar

import android.content.Context
import java.io.File
import java.util.concurrent.Callable
import java.util.concurrent.CompletableFuture
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicInteger

/**
 * One listening session: long-poll the glasses, fetch each clip as soon as
 * it is announced, play them in the order spoken.
 *
 * Mirrors device/server/static/listen.html, "stop" handling included. Each
 * poll is also the phone's "still here": the glasses give their own speaker
 * back 5 s after the last one, which is what makes losing the phone safe.
 */
class ListenSession(
    private val context: Context,
    address: String,
    private val client: String,
    private val muteDevice: () -> Boolean,
) {
    private val base = "http://$address"
    private val cache = ClipCache(File(context.cacheDir, "clips"))

    @Volatile
    private var running = true

    /** Bumped by every "stop": clips queued before it are dropped, the one playing is cut. */
    private val generation = AtomicInteger()
    private val queue = LinkedBlockingQueue<Pending>()
    private val fetcher = Executors.newFixedThreadPool(2)
    private val pollThread = Thread({ pollLoop() }, "isora-poll")
    private val playThread = Thread({ playLoop() }, "isora-play")

    private class Pending(val generation: Int, val wav: Future<ByteArray?>)

    fun start() {
        pollThread.start()
        playThread.start()
    }

    fun stop() {
        if (!running) return
        running = false
        generation.incrementAndGet()
        queue.clear()
        pollThread.interrupt()
        playThread.interrupt()
        fetcher.shutdownNow()
        // Hand the voice back to the glasses now rather than in 5 s — after
        // the last poll has returned, or that poll would sign the phone in again.
        Thread({
            try {
                pollThread.join(4000)
            } catch (e: InterruptedException) {
                // leave anyway
            }
            try {
                Net.postJson(context, base + Protocol.LEAVE_PATH, Protocol.leaveBody(client), 2000)
            } catch (e: Exception) {
                // the glasses time the phone out by themselves
            }
        }, "isora-leave").start()
    }

    private fun pollLoop() {
        var since = -1
        var failures = 0
        while (running) {
            try {
                val url = base + Protocol.pollPath(client, since, muteDevice())
                val r = Protocol.parsePoll(String(Net.get(context, url, CONNECT_MS, POLL_READ_MS, 256 * 1024), Charsets.UTF_8))
                failures = 0
                ListenState.update {
                    if (running) it.copy(phase = ListenState.Phase.LISTENING, deviceMuted = r.deviceMuted) else it
                }
                if (!running) break
                for (e in r.events) handle(e)
                since = r.seq
            } catch (e: Exception) {
                if (!running) break
                failures++
                ListenState.update { if (running) it.copy(phase = ListenState.Phase.RETRYING) else it }
                try {
                    // Short on purpose: until this poll lands, the glasses speak through their own speaker.
                    Thread.sleep(minOf(RETRY_MAX_MS, RETRY_STEP_MS * failures))
                } catch (ie: InterruptedException) {
                    break
                }
            }
        }
    }

    private fun handle(e: PollEvent) {
        when (e.type) {
            "stop" -> {
                generation.incrementAndGet()
                queue.clear()
            }
            "clip" -> {
                if (e.text.isNotEmpty()) {
                    ListenState.update { if (running) it.copy(caption = e.text) else it }
                }
                val g = generation.get()
                // Read here, not on the fetchers: two slow downloads must not hold up a clip already on the phone.
                val hit = cache.get(e.text, e.ms)
                val wav: Future<ByteArray?> = if (hit != null) {
                    CompletableFuture.completedFuture(hit)
                } else {
                    try {
                        fetcher.submit(Callable { fetchClip(e) })
                    } catch (x: RejectedExecutionException) {
                        return
                    }
                }
                queue.offer(Pending(g, wav))
            }
        }
    }

    // A clip lives on the glasses for a few sentences only; a miss is skipped, not retried.
    private fun fetchClip(e: PollEvent): ByteArray? = try {
        Net.get(context, base + Protocol.clipPath(e.id), CONNECT_MS, 10_000, 8 * 1024 * 1024)
            .also { cache.put(e.text, e.ms, it) }
    } catch (x: Exception) {
        null
    }

    private fun playLoop() {
        val player = ClipPlayer(context)
        var lastSound = System.nanoTime()
        try {
            while (running) {
                try {
                    val next = queue.poll()
                    if (next == null) {
                        // A pause between sentences keeps the audio focus; a longer silence gives it back.
                        if (System.nanoTime() - lastSound > IDLE_NS) player.idle()
                        player.silence()
                        continue
                    }
                    val bytes = awaitClip(next, player)
                    if (bytes == null || next.generation != generation.get() || !running) continue
                    val wav = try {
                        Wav.parse(bytes)
                    } catch (e: IllegalArgumentException) {
                        continue
                    }
                    player.play(wav) { running && next.generation == generation.get() }
                    lastSound = System.nanoTime()
                } catch (e: RuntimeException) {
                    player.release() // a broken AudioTrack: the next clip gets a fresh one
                    Thread.sleep(BROKEN_TRACK_WAIT_MS)
                }
            }
        } catch (e: InterruptedException) {
            // stop()
        } finally {
            player.release()
        }
    }

    /** The clip's bytes once downloaded, the track still running meanwhile; null when there is nothing to play. */
    private fun awaitClip(next: Pending, player: ClipPlayer): ByteArray? {
        val deadline = System.nanoTime() + FETCH_WAIT_NS
        while (!next.wav.isDone) {
            if (!running || next.generation != generation.get() || System.nanoTime() > deadline) return null
            player.silence()
        }
        return try {
            next.wav.get()
        } catch (e: InterruptedException) {
            throw e
        } catch (e: Exception) {
            null
        }
    }

    private companion object {
        const val CONNECT_MS = 3000
        const val POLL_READ_MS = 8000 // the glasses hold a poll for 2.5 s
        const val IDLE_NS = 1_500_000_000L
        const val FETCH_WAIT_NS = 15_000_000_000L
        const val BROKEN_TRACK_WAIT_MS = 200L
        const val RETRY_STEP_MS = 250L
        const val RETRY_MAX_MS = 1000L
    }
}
