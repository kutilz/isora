package id.isora.dengar

import android.os.Handler
import android.os.Looper
import java.util.concurrent.CopyOnWriteArrayList

/** What the listening service is doing, for the screen to show. One per process. */
object ListenState {

    enum class Phase { OFF, CONNECTING, LISTENING, RETRYING }

    data class Snapshot(
        val phase: Phase = Phase.OFF,
        val deviceMuted: Boolean = false,
        val caption: String = "",
        /** Shown while OFF: why it stopped, or that it could not start. */
        val note: String = "",
    )

    @Volatile
    var current = Snapshot()
        private set

    private val observers = CopyOnWriteArrayList<(Snapshot) -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    /**
     * Apply [change] under one lock, so a session can test its own "still
     * running" flag inside it and never overwrite the OFF that stopped it.
     * Observers hear only real changes: every poll ends in an update, and a
     * screen reader must not be told the same thing every 2.5 s.
     */
    fun update(change: (Snapshot) -> Snapshot) {
        val next: Snapshot
        synchronized(this) {
            val prev = current
            next = change(prev)
            if (next == prev) return
            current = next
        }
        main.post { observers.forEach { it(next) } }
    }

    fun observe(o: (Snapshot) -> Unit) {
        observers += o
    }

    fun remove(o: (Snapshot) -> Unit) {
        observers -= o
    }
}
