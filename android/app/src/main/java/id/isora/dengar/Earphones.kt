package id.isora.dengar

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothA2dp
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothClass
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper

/**
 * The phone's Bluetooth, driven from inside the app: switch it on, find
 * earphones, pair them, and say where the sound is going.
 *
 * Pairing is a public API (createBond; Android still shows its own one-tap
 * "Pair?" confirmation, which no app can skip). Making an already-paired
 * earphone the audio output is not: only the system may do that. In
 * practice it barely matters — earphones connect themselves right after
 * pairing and every time they are switched on — and connectAudio() still
 * tries the hidden call on the Android versions that let an app reach it.
 */
@SuppressLint("MissingPermission") // every call that needs a permission sits behind granted()
class Earphones(private val context: Context, private val onChange: () -> Unit) {

    private val adapter: BluetoothAdapter? = context.getSystemService(BluetoothManager::class.java)?.adapter
    private val audio = context.getSystemService(AudioManager::class.java)
    private val main = Handler(Looper.getMainLooper())
    private var a2dp: BluetoothA2dp? = null
    private var started = false
    private var pairing: String? = null

    /** Unpaired earphones seen by the current search, by address, in the order found. */
    val found = LinkedHashMap<String, BluetoothDevice>()

    var discovering = false
        private set

    /** The latest thing worth telling the user, or null. */
    var message: String? = null

    val available: Boolean get() = adapter != null
    val enabled: Boolean get() = adapter?.isEnabled == true

    fun permissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= 31) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }

    fun granted(): Boolean =
        permissions().all { context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }

    fun start() {
        if (!started) {
            started = true
            val filter = IntentFilter().apply {
                addAction(BluetoothDevice.ACTION_FOUND)
                addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED)
                addAction(BluetoothAdapter.ACTION_DISCOVERY_STARTED)
                addAction(BluetoothAdapter.ACTION_DISCOVERY_FINISHED)
                addAction(BluetoothAdapter.ACTION_STATE_CHANGED)
                addAction(BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED)
            }
            // Sent by the Bluetooth stack, which is not this app.
            if (Build.VERSION.SDK_INT >= 33) {
                context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
            } else {
                context.registerReceiver(receiver, filter)
            }
            audio.registerAudioDeviceCallback(outputs, main)
        }
        bindA2dp()
    }

    fun stop() {
        if (!started) return
        started = false
        if (granted()) adapter?.cancelDiscovery()
        discovering = false
        context.unregisterReceiver(receiver)
        audio.unregisterAudioDeviceCallback(outputs)
        a2dp?.let { adapter?.closeProfileProxy(BluetoothProfile.A2DP, it) }
        a2dp = null
    }

    fun scan() {
        val a = adapter ?: return
        if (!granted() || !a.isEnabled) return
        found.clear()
        a.cancelDiscovery()
        message = if (a.startDiscovery()) null else context.getString(R.string.bt_scan_failed)
        onChange()
    }

    fun cancelScan() {
        if (granted()) adapter?.cancelDiscovery()
    }

    /** Paired earphones, by name. */
    fun saved(): List<BluetoothDevice> {
        val a = adapter ?: return emptyList()
        if (!granted() || !a.isEnabled) return emptyList()
        return a.bondedDevices.orEmpty().filter { isAudio(it) }.sortedBy { nameOf(it).lowercase() }
    }

    /** The user picked an earphone: pair it, or bring a paired one back. */
    fun choose(address: String) {
        val a = adapter ?: return
        if (!granted()) return
        a.cancelDiscovery()
        val d = found[address] ?: a.getRemoteDevice(address)
        val name = nameOf(d)
        if (d.bondState == BluetoothDevice.BOND_BONDED) {
            message = context.getString(if (connectAudio(d)) R.string.bt_connecting else R.string.bt_use_hint, name)
        } else if (d.createBond()) {
            pairing = d.address
            message = context.getString(R.string.bt_pairing, name)
        } else {
            message = context.getString(R.string.bt_pair_failed, name)
        }
        onChange()
    }

    fun nameOf(d: BluetoothDevice): String {
        if (!granted()) return d.address
        val n = if (Build.VERSION.SDK_INT >= 30) d.alias ?: d.name else d.name
        return n?.takeIf { it.isNotBlank() } ?: d.address
    }

    /** Name of the Bluetooth output the phone's sound goes to, or null. */
    fun bluetoothOutput(): String? {
        val d = audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).firstOrNull { it.type in BT_OUTPUTS }
            ?: return null
        return d.productName?.toString()?.takeIf { it.isNotBlank() } ?: context.getString(R.string.bt_generic)
    }

    fun wiredOutput(): Boolean =
        audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { it.type in WIRED_OUTPUTS }

    private fun bindA2dp() {
        val a = adapter ?: return
        if (a2dp != null || !a.isEnabled || !granted()) return
        a.getProfileProxy(context, object : BluetoothProfile.ServiceListener {
            override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
                if (started) a2dp = proxy as BluetoothA2dp else a.closeProfileProxy(profile, proxy)
            }

            override fun onServiceDisconnected(profile: Int) {
                a2dp = null
            }
        }, BluetoothProfile.A2DP)
    }

    /**
     * Ask for media to go to [d]. BluetoothA2dp.connect is hidden: allowed on
     * some Android versions, refused on newer ones. Refused is fine — the
     * earphone connects itself once it is switched on.
     */
    @SuppressLint("DiscouragedPrivateApi", "SoonBlockedPrivateApi", "BlockedPrivateApi")
    private fun connectAudio(d: BluetoothDevice): Boolean {
        val p = a2dp ?: return false
        return try {
            BluetoothA2dp::class.java.getMethod("connect", BluetoothDevice::class.java).invoke(p, d) as? Boolean ?: false
        } catch (t: Throwable) {
            false
        }
    }

    private fun isAudio(d: BluetoothDevice): Boolean {
        val c = d.bluetoothClass ?: return false
        return c.majorDeviceClass == BluetoothClass.Device.Major.AUDIO_VIDEO ||
            c.hasService(BluetoothClass.Service.AUDIO)
    }

    @Suppress("DEPRECATION")
    private fun deviceOf(i: Intent): BluetoothDevice? =
        if (Build.VERSION.SDK_INT >= 33) {
            i.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
        } else {
            i.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
        }

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, intent: Intent) {
            when (intent.action) {
                BluetoothDevice.ACTION_FOUND -> {
                    val d = deviceOf(intent) ?: return
                    if (!granted() || !isAudio(d) || d.name.isNullOrBlank()) return
                    if (d.bondState != BluetoothDevice.BOND_BONDED) found[d.address] = d
                }
                BluetoothAdapter.ACTION_DISCOVERY_STARTED -> discovering = true
                BluetoothAdapter.ACTION_DISCOVERY_FINISHED -> {
                    discovering = false
                    if (found.isEmpty() && pairing == null) message = context.getString(R.string.bt_found_none)
                }
                BluetoothDevice.ACTION_BOND_STATE_CHANGED -> {
                    val d = deviceOf(intent)
                    if (d != null && d.address == pairing) {
                        when (d.bondState) {
                            BluetoothDevice.BOND_BONDED -> {
                                pairing = null
                                found.remove(d.address)
                                message = context.getString(R.string.bt_paired, nameOf(d))
                                connectAudio(d)
                            }
                            BluetoothDevice.BOND_NONE -> {
                                pairing = null
                                message = context.getString(R.string.bt_pair_failed, nameOf(d))
                            }
                        }
                    }
                }
                BluetoothAdapter.ACTION_STATE_CHANGED -> {
                    if (enabled) {
                        bindA2dp()
                    } else {
                        a2dp = null
                        found.clear()
                        discovering = false
                    }
                }
                BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED -> {
                    val d = deviceOf(intent)
                    if (d != null && intent.getIntExtra(BluetoothProfile.EXTRA_STATE, -1) == BluetoothProfile.STATE_CONNECTED) {
                        message = context.getString(R.string.bt_connected_now, nameOf(d))
                    }
                }
            }
            onChange()
        }
    }

    private val outputs = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>) = onChange()
        override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>) = onChange()
    }

    private companion object {
        // Plain ints compared against the outputs present; on an Android too old
        // for a type, that type simply never shows up.
        @SuppressLint("InlinedApi")
        val BT_OUTPUTS = setOf(
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
            AudioDeviceInfo.TYPE_HEARING_AID,
            AudioDeviceInfo.TYPE_BLE_HEADSET,
            AudioDeviceInfo.TYPE_BLE_SPEAKER,
        )
        val WIRED_OUTPUTS = setOf(
            AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_USB_HEADSET,
        )
    }
}
