package id.isora.dengar

import android.Manifest
import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.app.Activity
import android.app.AlertDialog
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.RadioGroup
import android.widget.TextView
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * One screen, three cards, in the order they are used: the big Listen
 * button, the earphones, the glasses. Listen does everything on its own —
 * finds the glasses if needed, then starts — so a blind user who has paired
 * once needs that one button and nothing else.
 */
class MainActivity : Activity() {

    private lateinit var prefs: Prefs
    private lateinit var finder: DeviceFinder
    private lateinit var earphones: Earphones
    private lateinit var work: ExecutorService
    private val main = Handler(Looper.getMainLooper())

    private lateinit var listen: Button
    private lateinit var listenStatus: TextView
    private lateinit var caption: TextView
    private lateinit var outputStatus: TextView
    private lateinit var btEnable: Button
    private lateinit var btScan: Button
    private lateinit var btMessage: TextView
    private lateinit var btFound: LinearLayout
    private lateinit var btSavedLabel: TextView
    private lateinit var btSaved: LinearLayout
    private lateinit var deviceStatus: TextView
    private lateinit var deviceChoices: LinearLayout

    private var finding = false
    private var startAfterFind = false
    private var openAfterFind: String? = null // a control page waiting for the search
    private var findAttempt = 1
    private var deviceReachable: Boolean? = null // null: not checked yet
    private var deviceNote: String? = null
    private var afterBluetoothPermission: (() -> Unit)? = null

    private val onListenState: (ListenState.Snapshot) -> Unit = { renderListen() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)
        finder = DeviceFinder(applicationContext)
        work = Executors.newSingleThreadExecutor()
        earphones = Earphones(this) { renderEarphones() }

        listen = findViewById(R.id.listen)
        listenStatus = findViewById(R.id.listenStatus)
        caption = findViewById(R.id.caption)
        outputStatus = findViewById(R.id.outputStatus)
        btEnable = findViewById(R.id.btEnable)
        btScan = findViewById(R.id.btScan)
        btMessage = findViewById(R.id.btMessage)
        btFound = findViewById(R.id.btFound)
        btSavedLabel = findViewById(R.id.btSavedLabel)
        btSaved = findViewById(R.id.btSaved)
        deviceStatus = findViewById(R.id.deviceStatus)
        deviceChoices = findViewById(R.id.deviceChoices)

        if (Build.VERSION.SDK_INT >= 35) applyInsets()

        listen.setOnClickListener { onListenPressed() }
        val mute = findViewById<RadioGroup>(R.id.muteGroup)
        mute.check(if (prefs.muteDevice) R.id.muteOn else R.id.muteOff)
        mute.setOnCheckedChangeListener { _, id -> prefs.muteDevice = id == R.id.muteOn }
        btEnable.setOnClickListener { withBluetoothPermission { enableBluetooth() } }
        btScan.setOnClickListener {
            withBluetoothPermission { if (earphones.discovering) earphones.cancelScan() else earphones.scan() }
        }
        findViewById<Button>(R.id.btSettings).setOnClickListener {
            startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS))
        }
        findViewById<Button>(R.id.findDevice).setOnClickListener { findDevice(startAfter = false, everyDevice = true) }
        findViewById<Button>(R.id.openControl).setOnClickListener { openPage(ControlActivity.PATH_CONTROL) }
        findViewById<Button>(R.id.typeAddress).setOnClickListener { askAddress() }
    }

    override fun onStart() {
        super.onStart()
        ListenState.observe(onListenState)
        earphones.start()
        renderListen()
        renderEarphones()
        checkSavedDevice()
    }

    override fun onStop() {
        ListenState.remove(onListenState)
        earphones.stop()
        super.onStop()
    }

    override fun onDestroy() {
        work.shutdownNow()
        super.onDestroy()
    }

    // ─── listening ──────────────────────────────────────────────────────────

    private fun onListenPressed() {
        if (ListenState.current.phase != ListenState.Phase.OFF) {
            ListenService.stop(this)
            return
        }
        askNotificationsOnce()
        if (prefs.deviceAddress != null && deviceReachable == true) {
            ListenService.start(this)
        } else {
            findDevice(startAfter = true)
        }
    }

    private fun renderListen() {
        val s = ListenState.current
        val on = s.phase != ListenState.Phase.OFF
        listen.setText(if (on) R.string.listen_stop else R.string.listen_start)
        listen.setBackgroundResource(if (on) R.drawable.btn_danger else R.drawable.btn_primary)
        listenStatus.text = when (s.phase) {
            ListenState.Phase.OFF -> when {
                finding && startAfterFind -> getString(R.string.st_finding)
                s.note.isNotEmpty() -> s.note
                else -> getString(R.string.st_off)
            }
            ListenState.Phase.CONNECTING -> getString(R.string.st_connecting)
            ListenState.Phase.LISTENING ->
                getString(if (s.deviceMuted) R.string.st_listening_muted else R.string.st_listening_both)
            ListenState.Phase.RETRYING -> getString(R.string.st_retrying)
        }
        caption.text = s.caption.ifEmpty { getString(R.string.caption_none) }
    }

    private fun askNotificationsOnce() {
        if (Build.VERSION.SDK_INT < 33 || prefs.askedNotifications) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        prefs.askedNotifications = true
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFICATIONS)
    }

    // ─── the glasses ────────────────────────────────────────────────────────

    /**
     * Listen goes straight to the saved glasses when they answer. The Find
     * button looks at [everyDevice] on the network, or a second pair could never
     * be chosen while the first is switched on.
     */
    private fun findDevice(startAfter: Boolean, everyDevice: Boolean = false, patienceMs: Long = FIND_PATIENCE_MS) {
        startAfterFind = startAfterFind || startAfter
        if (finding) return
        finding = true
        findAttempt = 1
        deviceNote = null
        deviceChoices.removeAllViews()
        renderDevice()
        renderListen()
        val saved = prefs.deviceAddress
        work.execute {
            val report = finder.search(saved, everyDevice, patienceMs) { attempt ->
                main.post {
                    findAttempt = attempt
                    renderDevice()
                }
            }
            main.post { onFound(report) }
        }
    }

    private fun onFound(report: DeviceFinder.Report) {
        if (isDestroyed) return
        val all = report.found
        finding = false
        val start = startAfterFind
        val page = openAfterFind
        startAfterFind = false
        openAfterFind = null
        when (all.size) {
            0 -> {
                deviceReachable = false
                deviceNote = whyNotFound(report)
                if (start) ListenState.update { it.copy(note = getString(R.string.dev_not_found_short)) }
            }
            1 -> {
                useDevice(all[0])
                if (start) ListenService.start(this)
                if (page != null) ControlActivity.open(this, all[0].address, page)
            }
            else -> {
                deviceNote = getString(R.string.dev_found_many)
                for (f in all) {
                    val label = getString(R.string.dev_use, f.identity.name, Address.display(f.address))
                    deviceChoices.addView(button(label) {
                        useDevice(f)
                        if (start) ListenService.start(this)
                        if (page != null) ControlActivity.open(this, f.address, page)
                    })
                }
            }
        }
        renderDevice()
        renderListen()
    }

    private fun whyNotFound(r: DeviceFinder.Report): String {
        val own = r.ownAddresses.joinToString(", ")
        return when {
            r.ownAddresses.isEmpty() -> getString(R.string.dev_no_address)
            r.error != null -> getString(R.string.dev_blocked, r.error, own)
            else -> getString(R.string.dev_nobody, own, r.tried)
        }
    }

    /** A control page of the glasses in use; finds them first when they did not answer. */
    private fun openPage(path: String) {
        val address = prefs.deviceAddress
        if (address != null && deviceReachable == true) {
            ControlActivity.open(this, address, path)
        } else {
            openAfterFind = path
            findDevice(startAfter = false)
        }
    }

    private fun useDevice(f: DeviceFinder.Found) {
        val changed = prefs.deviceAddress != f.address
        prefs.deviceAddress = f.address
        prefs.deviceName = f.identity.name
        deviceReachable = true
        deviceNote = null
        deviceChoices.removeAllViews()
        renderDevice()
        if (changed && ListenState.current.phase != ListenState.Phase.OFF) ListenService.switchDevice(this)
    }

    private fun checkSavedDevice() {
        val saved = prefs.deviceAddress
        if (finding) return renderDevice()
        if (saved == null) return findDevice(startAfter = false, patienceMs = 0)
        deviceReachable = null
        renderDevice()
        work.execute {
            val hit = finder.probe(saved)
            main.post {
                if (isDestroyed || prefs.deviceAddress != saved) return@post
                deviceReachable = hit != null
                if (hit != null) prefs.deviceName = hit.identity.name
                renderDevice()
                // A new hotspot hands the glasses a new address: look for them
                // without waiting to be asked.
                if (hit == null) findDevice(startAfter = false, patienceMs = 0)
            }
        }
    }

    private fun renderDevice() {
        val address = prefs.deviceAddress
        val name = prefs.deviceName ?: getString(R.string.dev_default_name)
        deviceStatus.text = when {
            finding && findAttempt > 1 -> getString(R.string.st_finding_retry, findAttempt)
            finding -> getString(R.string.st_finding)
            deviceNote != null -> deviceNote
            address == null -> getString(R.string.dev_none)
            deviceReachable == null -> getString(R.string.dev_checking, name)
            deviceReachable == true -> getString(R.string.dev_ok, name, Address.display(address))
            else -> getString(R.string.dev_unreachable, name, Address.display(address))
        }
    }

    private fun askAddress() {
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            hint = getString(R.string.dev_type_hint)
            setText(prefs.deviceAddress?.let { Address.display(it) } ?: "")
        }
        val box = FrameLayout(this).apply {
            setPadding(dp(20), dp(8), dp(20), 0)
            addView(input)
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.dev_type_title)
            .setView(box)
            .setPositiveButton(R.string.ok) { _, _ -> tryAddress(input.text.toString()) }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun tryAddress(raw: String) {
        val address = Address.normalize(raw) ?: return
        deviceNote = getString(R.string.dev_checking, Address.display(address))
        renderDevice()
        work.execute {
            var probe = finder.probeDetail(address)
            var tries = 1
            // A refused socket can clear by itself (see DeviceFinder); nobody
            // answering at a typed address will not, so that is not retried.
            while (probe.found == null && probe.error != null && tries < TYPED_TRIES) {
                try {
                    Thread.sleep(TYPED_RETRY_MS)
                } catch (e: InterruptedException) {
                    return@execute
                }
                probe = finder.probeDetail(address)
                tries += 1
            }
            main.post {
                if (isDestroyed) return@post
                val hit = probe.found
                if (hit != null) {
                    useDevice(hit)
                } else {
                    val shown = Address.display(address)
                    deviceNote = probe.error?.let { getString(R.string.dev_type_blocked, shown, it) }
                        ?: getString(R.string.dev_type_bad, shown)
                    renderDevice()
                }
            }
        }
    }

    // ─── earphones ──────────────────────────────────────────────────────────

    private fun renderEarphones() {
        outputStatus.text = earphones.bluetoothOutput()?.let { getString(R.string.out_bt, it) }
            ?: getString(if (earphones.wiredOutput()) R.string.out_wired else R.string.out_phone)
        if (!earphones.available) {
            btEnable.visibility = View.GONE
            btScan.visibility = View.GONE
            showMessage(getString(R.string.bt_none))
            return
        }
        val on = earphones.enabled
        btEnable.visibility = if (on) View.GONE else View.VISIBLE
        btScan.visibility = if (on) View.VISIBLE else View.GONE
        btScan.setText(if (earphones.discovering) R.string.bt_scanning else R.string.bt_scan)
        showMessage(earphones.message ?: if (on) "" else getString(R.string.bt_off))
        val visible = on && earphones.granted()
        syncButtons(
            btFound,
            if (visible) earphones.found.values.map { it.address to getString(R.string.bt_pair, earphones.nameOf(it)) } else emptyList(),
        ) { earphones.choose(it) }
        val saved = if (visible) earphones.saved() else emptyList()
        btSavedLabel.visibility = if (saved.isEmpty()) View.GONE else View.VISIBLE
        syncButtons(btSaved, saved.map { it.address to getString(R.string.bt_use, earphones.nameOf(it)) }) {
            earphones.choose(it)
        }
    }

    private fun showMessage(text: String) {
        if (btMessage.text.toString() != text) btMessage.text = text
        btMessage.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
    }

    @SuppressLint("MissingPermission") // only reached through withBluetoothPermission
    private fun enableBluetooth() {
        startActivity(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE))
    }

    private fun withBluetoothPermission(then: () -> Unit) {
        if (earphones.granted()) return then()
        afterBluetoothPermission = then
        requestPermissions(earphones.permissions(), REQ_BLUETOOTH)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_BLUETOOTH) return
        val next = afterBluetoothPermission
        afterBluetoothPermission = null
        if (earphones.granted()) {
            earphones.start()
            next?.invoke()
        } else {
            earphones.message = getString(R.string.bt_permission)
        }
        renderEarphones()
    }

    // ─── views ──────────────────────────────────────────────────────────────

    /**
     * Make [box] show exactly [items] (key → label), keeping the buttons that
     * stay: rebuilding them would throw a screen reader's focus off the list
     * every time one more earphone is found.
     */
    private fun syncButtons(box: LinearLayout, items: List<Pair<String, String>>, onTap: (String) -> Unit) {
        val keys = items.map { it.first }.toSet()
        for (i in box.childCount - 1 downTo 0) {
            if (box.getChildAt(i).tag !in keys) box.removeViewAt(i)
        }
        for ((key, label) in items) {
            val existing = (0 until box.childCount).map { box.getChildAt(it) }.firstOrNull { it.tag == key } as Button?
            if (existing != null) {
                if (existing.text.toString() != label) existing.text = label
            } else {
                box.addView(button(label) { onTap(key) }.apply { tag = key })
            }
        }
    }

    private fun button(label: String, onTap: () -> Unit): Button =
        Button(this, null, 0, R.style.Isora_Button_Secondary).apply {
            text = label
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { topMargin = dp(12) }
            setOnClickListener { onTap() }
        }

    // Android 15 draws apps under the status and navigation bars. (@TargetApi:
    // the @RequiresApi lint prefers is AndroidX, which this app does without.)
    @TargetApi(35)
    private fun applyInsets() {
        findViewById<View>(R.id.root).setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private companion object {
        const val REQ_BLUETOOTH = 1
        const val REQ_NOTIFICATIONS = 2
        const val FIND_PATIENCE_MS = 20_000L
        const val TYPED_TRIES = 4
        const val TYPED_RETRY_MS = 2_000L
    }
}
