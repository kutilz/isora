package id.isora.dengar

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.URL

/** HTTP to the glasses, over whichever of the phone's networks they are on. */
object Net {

    /**
     * A phone on a WiFi without internet (a router with no uplink, a venue
     * access point) keeps mobile data as its default network, and a plain
     * socket to the glasses' LAN address would leave over mobile data and
     * never arrive. So when one of the phone's networks has the address in
     * its own subnet, the connection is made on that network explicitly.
     * Hotspot clients need nothing: their route is shared by every app.
     */
    @Suppress("DEPRECATION") // allNetworks: still the simplest complete list
    fun networkFor(context: Context, host: String): Network? {
        val target = Subnet.parse(host) ?: return null
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return null
        for (n in cm.allNetworks) {
            // The glasses are never on mobile data, and with WiFi up Android
            // refuses a socket bound to it (EPERM) even when a carrier's 10.x
            // range happens to contain their address.
            if (cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true) continue
            val lp = cm.getLinkProperties(n) ?: continue
            val onIt = lp.linkAddresses.any { la ->
                val a = la.address
                a is Inet4Address && Subnet.contains(Subnet.toInt(a.address), la.prefixLength, target)
            }
            if (onIt) return n
        }
        return null
    }

    fun open(context: Context, url: URL, connectMs: Int, readMs: Int, bind: Boolean = true): HttpURLConnection {
        val network = if (bind) networkFor(context, url.host) else null
        val c = (network?.openConnection(url) ?: url.openConnection()) as HttpURLConnection
        c.connectTimeout = connectMs
        c.readTimeout = readMs
        c.useCaches = false
        return c
    }

    /**
     * A socket Android refuses on the chosen network fails at once, and the route
     * every app shares may still work; so a failure that fast gets one more try
     * without the binding. A slow failure is just nobody answering.
     */
    fun get(context: Context, url: String, connectMs: Int, readMs: Int, maxBytes: Int): ByteArray {
        val started = System.nanoTime()
        try {
            return getOnce(context, url, connectMs, readMs, maxBytes, bind = true)
        } catch (e: IOException) {
            val fast = (System.nanoTime() - started) / 1_000_000 < INSTANT_FAILURE_MS
            if (!fast || networkFor(context, URL(url).host) == null) throw e
        }
        return getOnce(context, url, connectMs, readMs, maxBytes, bind = false)
    }

    private fun getOnce(context: Context, url: String, connectMs: Int, readMs: Int, maxBytes: Int, bind: Boolean): ByteArray {
        val c = open(context, URL(url), connectMs, readMs, bind)
        try {
            val code = c.responseCode
            if (code != 200) throw IOException("HTTP $code")
            return c.inputStream.use { readCapped(it, maxBytes) }
        } finally {
            c.disconnect()
        }
    }

    fun postJson(context: Context, url: String, json: String, timeoutMs: Int) {
        val c = open(context, URL(url), timeoutMs, timeoutMs)
        try {
            val data = json.toByteArray(Charsets.UTF_8)
            c.requestMethod = "POST"
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.setFixedLengthStreamingMode(data.size)
            c.outputStream.use { it.write(data) }
            c.responseCode
        } finally {
            c.disconnect()
        }
    }

    private fun readCapped(input: InputStream, max: Int): ByteArray {
        val out = ByteArrayOutputStream()
        val buf = ByteArray(16 * 1024)
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            if (out.size() + n > max) throw IOException("response larger than $max bytes")
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }

    private const val INSTANT_FAILURE_MS = 200L
}
