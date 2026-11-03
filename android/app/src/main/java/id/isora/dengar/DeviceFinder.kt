package id.isora.dengar

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.util.Log
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.Collections
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Where the glasses are: the address that answered last time, else a sweep
 * of the phone's own WiFi and hotspot.
 *
 * A sweep rather than mDNS because the usual setup is the glasses on the
 * phone's OWN hotspot, and Android's service discovery does not look there;
 * and because a blind user cannot read an IP address off anything to type
 * it in. Every candidate must answer /status as I-Sora glasses, so nothing
 * else that happens to listen on :8080 is mistaken for them.
 *
 * A failed search says why ([Report]). One phone in the field failed instantly
 * and silently for a while, then worked: every error was swallowed, so nothing
 * on screen told a missing address from a refused socket.
 */
class DeviceFinder(private val context: Context) {

    data class Found(val address: String, val identity: DeviceIdentity)

    /** One address tried. [error] is set only for a failure worth showing. */
    data class Probe(val found: Found?, val error: String?)

    /** What a search saw: the raw material of the message on a failure. */
    data class Report(
        val found: List<Found>,
        val ownAddresses: List<String>,
        val tried: Int,
        val error: String?,
    )

    fun probeDetail(address: String, connectMs: Int = 1500): Probe = try {
        val body = Net.get(context, "http://$address${Protocol.STATUS_PATH}", connectMs, 3000, 256 * 1024)
        val found = Protocol.parseIdentity(String(body, Charsets.UTF_8))?.let { Found(address, it) }
        Probe(found, null)
    } catch (e: Exception) {
        Probe(null, Failure.blocking(e.message))
    }

    fun probe(address: String, connectMs: Int = 1500): Found? = probeDetail(address, connectMs).found

    /**
     * Keep looking for up to [patienceMs]. The phone that failed in the field
     * recovered on its own after a while, so a single instant failure is not an
     * answer: a sweep that dies in milliseconds is simply tried again.
     */
    fun search(saved: String?, everyDevice: Boolean, patienceMs: Long, onRetry: (Int) -> Unit): Report {
        val hit = saved?.let { probe(it) }
        if (hit != null && !everyDevice) return Report(listOf(hit), emptyList(), 1, null)
        val deadline = System.nanoTime() + patienceMs * 1_000_000
        var attempt = 1
        while (true) {
            val started = System.nanoTime()
            val report = sweep()
            val all = (listOfNotNull(hit) + report.found).distinctBy { it.identity.id }
            if (all.isNotEmpty()) return report.copy(found = all)
            if (System.nanoTime() >= deadline) {
                Log.w(TAG, "not found: own=${report.ownAddresses} tried=${report.tried} error=${report.error}")
                return report
            }
            val spentMs = (System.nanoTime() - started) / 1_000_000
            try {
                Thread.sleep((RETRY_EVERY_MS - spentMs).coerceAtLeast(0))
            } catch (e: InterruptedException) {
                return report
            }
            attempt += 1
            onRetry(attempt)
        }
    }

    /** Glasses on any /24 the phone has a WiFi, hotspot or USB address in. */
    fun sweep(): Report {
        val own = localAddresses()
        val ownText = own.map { Subnet.format(it) }
        val hosts = own.flatMap { Subnet.neighbours24(it) }.distinct().filter { it !in own }
        if (hosts.isEmpty()) return Report(emptyList(), ownText, 0, null)
        val error = AtomicReference<String?>(null)
        val pool = Executors.newFixedThreadPool(SWEEP_THREADS)
        try {
            val jobs = hosts.map { h ->
                pool.submit(Callable {
                    val p = probeDetail("${Subnet.format(h)}:${Address.PORT}", SWEEP_CONNECT_MS)
                    p.error?.let { error.compareAndSet(null, it) }
                    p.found
                })
            }
            val found = jobs.mapNotNull {
                try {
                    it.get(10, TimeUnit.SECONDS)
                } catch (e: Exception) {
                    null
                }
            }.distinctBy { it.identity.id }
            return Report(found, ownText, hosts.size, error.get())
        } finally {
            pool.shutdownNow()
        }
    }

    /**
     * The phone's private IPv4 addresses on anything but mobile data, from every
     * place Android tells them. Vendors name the hotspot interface as they like,
     * so one source (a list of names) is not enough: a name it does not know
     * would make the search end instantly with nothing to sweep.
     */
    private fun localAddresses(): List<Int> {
        val out = LinkedHashSet<Int>()
        val mobile = HashSet<Int>()
        val cm = context.getSystemService(ConnectivityManager::class.java)
        try {
            @Suppress("DEPRECATION")
            for (n in cm?.allNetworks.orEmpty()) {
                val caps = cm?.getNetworkCapabilities(n) ?: continue
                val lp = cm.getLinkProperties(n) ?: continue
                val ips = lp.linkAddresses.mapNotNull { (it.address as? Inet4Address)?.let { a -> Subnet.toInt(a.address) } }
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
                ) {
                    mobile += ips
                } else {
                    out += ips
                }
            }
        } catch (e: RuntimeException) {
            Log.w(TAG, "network list: $e")
        }
        try {
            for (ni in Collections.list(NetworkInterface.getNetworkInterfaces() ?: return out.finish(mobile))) {
                if (!ni.isUp || ni.isLoopback || Failure.isNotLocal(ni.name)) continue
                for (a in Collections.list(ni.inetAddresses)) {
                    if (a is Inet4Address) out += Subnet.toInt(a.address)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "interface list: $e")
        }
        try {
            @Suppress("DEPRECATION") // the only API that still answers without a location permission
            val dhcp = context.applicationContext.getSystemService(WifiManager::class.java)?.dhcpInfo
            if (dhcp != null && dhcp.ipAddress != 0) out += Subnet.fromLittleEndian(dhcp.ipAddress)
        } catch (e: RuntimeException) {
            Log.w(TAG, "wifi info: $e")
        }
        return out.finish(mobile)
    }

    private fun Set<Int>.finish(mobile: Set<Int>) = filter { Subnet.isPrivate(it) && it !in mobile }

    private companion object {
        const val TAG = "IsoraFinder"
        const val SWEEP_THREADS = 48
        const val SWEEP_CONNECT_MS = 800
        const val RETRY_EVERY_MS = 3000L
    }
}

/** The text-only judgments of the search, separate so they can be unit-tested. */
object Failure {
    // Mobile data and tunnels: carriers hand out 10.x too, and a sweep must never
    // walk a carrier's range. Everything else (wlan, swlan, ap, softap, eth, rndis,
    // or whatever a vendor calls its hotspot this year) is worth looking at.
    private val NOT_LOCAL = Regex("^(lo|dummy|rmnet|r_rmnet|v4-|ccmni|cc\\d|pdp|seth|wwan|sit|ip6|ip_vti|tun|ppp|ipsec|epdg|clat|qmi)")

    fun isNotLocal(name: String): Boolean = NOT_LOCAL.containsMatchIn(name)

    // Android refused the socket outright. Unlike a timeout or a refused port,
    // which only mean "nobody here", these mean no address could have worked.
    private val BLOCKING = listOf("EPERM", "EACCES", "ENETUNREACH", "ENONET", "Network is unreachable", "Permission denied", "not permitted")

    /** The message, when it says the phone itself blocked the connection. */
    fun blocking(message: String?): String? {
        val m = message ?: return null
        val sign = BLOCKING.firstOrNull { m.contains(it, ignoreCase = true) } ?: return null
        return sign
    }
}
