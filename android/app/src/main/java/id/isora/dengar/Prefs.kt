package id.isora.dengar

import android.content.Context
import java.util.UUID

/** What the app remembers between uses. */
class Prefs(context: Context) {
    private val sp = context.applicationContext.getSharedPreferences("isora_dengar", Context.MODE_PRIVATE)

    /**
     * One id per install. The glasses count listeners by it, so the app
     * coming back after a restart is the same listener, not a second phone.
     * Letters, digits and "-" only, at most 40 chars: what the device accepts.
     */
    val clientId: String
        get() {
            sp.getString(KEY_CLIENT, null)?.let { return it }
            val id = "hp-" + UUID.randomUUID().toString().replace("-", "").take(16)
            sp.edit().putString(KEY_CLIENT, id).apply()
            return id
        }

    /** "host:port" of the glasses that answered last. */
    var deviceAddress: String?
        get() = sp.getString(KEY_ADDRESS, null)
        set(v) = sp.edit().putString(KEY_ADDRESS, v).apply()

    var deviceName: String?
        get() = sp.getString(KEY_NAME, null)
        set(v) = sp.edit().putString(KEY_NAME, v).apply()

    /** Silence the glasses' own speaker while this phone listens — the default, as on /dengar. */
    var muteDevice: Boolean
        get() = sp.getBoolean(KEY_MUTE, true)
        set(v) = sp.edit().putBoolean(KEY_MUTE, v).apply()

    var askedNotifications: Boolean
        get() = sp.getBoolean(KEY_ASKED_NOTIFICATIONS, false)
        set(v) = sp.edit().putBoolean(KEY_ASKED_NOTIFICATIONS, v).apply()

    private companion object {
        const val KEY_CLIENT = "client"
        const val KEY_ADDRESS = "device_address"
        const val KEY_NAME = "device_name"
        const val KEY_MUTE = "mute_device"
        const val KEY_ASKED_NOTIFICATIONS = "asked_notifications"
    }
}
