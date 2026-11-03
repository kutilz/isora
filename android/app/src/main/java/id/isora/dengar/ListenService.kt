package id.isora.dengar

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager

/**
 * Keeps listening with the screen off: a media-playback foreground service
 * that holds the CPU and WiFi awake while a ListenSession runs.
 *
 * START_NOT_STICKY on purpose. If Android kills the app, the glasses notice
 * within 5 s that nobody polls and their own speaker takes over. A silent
 * restart later could mute that speaker again with nobody at the phone.
 */
class ListenService : Service() {

    private var session: ListenSession? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            ListenState.update { it.copy(note = getString(R.string.st_stopped)) }
            finish()
            return START_NOT_STICKY
        }
        if (intent?.action == ACTION_SWITCH) endSession() // and straight on to the newly chosen glasses
        goForeground()
        if (session == null) {
            val prefs = Prefs(this)
            val address = prefs.deviceAddress
            if (address == null) {
                ListenState.update { it.copy(note = getString(R.string.need_device)) }
                finish()
                return START_NOT_STICKY
            }
            holdLocks()
            ListenState.update { it.copy(phase = ListenState.Phase.CONNECTING, note = "", caption = "") }
            session = ListenSession(applicationContext, address, prefs.clientId) { prefs.muteDevice }
                .also { it.start() }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        endSession()
        super.onDestroy()
    }

    private fun finish() {
        endSession()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun endSession() {
        session?.stop()
        session = null
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        ListenState.update { it.copy(phase = ListenState.Phase.OFF) }
    }

    private fun goForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW),
        )
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this, 1,
            Intent(this, ListenService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_listen)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text))
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(
                Notification.Action.Builder(
                    Icon.createWithResource(this, R.drawable.ic_stat_listen),
                    getString(R.string.listen_stop),
                    stop,
                ).build(),
            )
        if (Build.VERSION.SDK_INT >= 31) {
            builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE)
        }
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, builder.build(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        } else {
            startForeground(NOTIFICATION_ID, builder.build())
        }
    }

    // Held exactly as long as the user listens; released in endSession().
    @SuppressLint("WakelockTimeout")
    private fun holdLocks() {
        val wm = applicationContext.getSystemService(WifiManager::class.java)
        // HIGH_PERF keeps WiFi out of power save with the screen off, but does
        // nothing from Android 14 on; LOW_LATENCY is what is left there.
        @Suppress("DEPRECATION")
        val mode = if (Build.VERSION.SDK_INT >= 34) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
        wifiLock = wm?.createWifiLock(mode, "isora:listen")?.apply {
            setReferenceCounted(false)
            acquire()
        }
        wakeLock = getSystemService(PowerManager::class.java)
            ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "isora:listen")
            ?.apply {
                setReferenceCounted(false)
                acquire()
            }
    }

    companion object {
        private const val ACTION_STOP = "id.isora.dengar.STOP"
        private const val ACTION_SWITCH = "id.isora.dengar.SWITCH"
        private const val CHANNEL = "listen"
        private const val NOTIFICATION_ID = 1

        fun start(context: Context) {
            context.startForegroundService(Intent(context, ListenService::class.java))
        }

        /** Listening already, and other glasses were chosen: follow them. */
        fun switchDevice(context: Context) {
            context.startForegroundService(Intent(context, ListenService::class.java).setAction(ACTION_SWITCH))
        }

        fun stop(context: Context) {
            context.startService(Intent(context, ListenService::class.java).setAction(ACTION_STOP))
        }
    }
}
