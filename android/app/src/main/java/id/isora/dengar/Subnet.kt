package id.isora.dengar

/** IPv4 arithmetic for finding the glasses on the phone's own networks. */
object Subnet {
    fun toInt(b: ByteArray): Int =
        ((b[0].toInt() and 0xff) shl 24) or ((b[1].toInt() and 0xff) shl 16) or
            ((b[2].toInt() and 0xff) shl 8) or (b[3].toInt() and 0xff)

    /** WifiManager's DhcpInfo keeps its addresses with the first octet in the low byte. */
    fun fromLittleEndian(ip: Int): Int = Integer.reverseBytes(ip)

    fun format(ip: Int) ="${ip ushr 24 and 0xff}.${ip ushr 16 and 0xff}.${ip ushr 8 and 0xff}.${ip and 0xff}"

    /** "192.168.1.37" → its 32 bits; anything else (a host name too) → null. */
    fun parse(s: String): Int? {
        val parts = s.split('.')
        if (parts.size != 4) return null
        var v = 0
        for (p in parts) {
            val n = p.toIntOrNull() ?: return null
            if (n !in 0..255 || p.length > 3) return null
            v = (v shl 8) or n
        }
        return v
    }

    fun contains(network: Int, prefix: Int, ip: Int): Boolean {
        if (prefix <= 0) return true
        val mask = if (prefix >= 32) -1 else -1 shl (32 - prefix)
        return (network and mask) == (ip and mask)
    }

    /**
     * RFC 1918 only. A sweep must never reach past the phone's own WiFi or
     * hotspot — not into a carrier's range, not onto the internet.
     */
    fun isPrivate(ip: Int): Boolean =
        contains(0x0A000000, 8, ip) ||
            contains(0xAC100000.toInt(), 12, ip) ||
            contains(0xC0A80000.toInt(), 16, ip)

    /** The other hosts of ip's /24. The sweep stops there whatever the real prefix is. */
    fun neighbours24(ip: Int): List<Int> {
        val base = ip and 0xFFFFFF00.toInt()
        return (1..254).map { base or it }.filter { it != ip }
    }
}

/** "host:port" addresses of the glasses as the app stores them. */
object Address {
    const val PORT = 8080

    /** "192.168.1.37", "http://192.168.1.37:8080/dengar" → "192.168.1.37:8080"; junk → null. */
    fun normalize(raw: String): String? {
        val s = raw.trim().removePrefix("http://").removePrefix("https://").substringBefore('/')
        if (s.isEmpty() || s.any { it.isWhitespace() }) return null
        val host = s.substringBefore(':')
        val port = if (':' in s) s.substringAfter(':').toIntOrNull() ?: return null else PORT
        if (host.isEmpty() || port !in 1..65535) return null
        return "$host:$port"
    }

    /** What to show: the bare IP when the port is the usual one. */
    fun display(address: String): String = address.removeSuffix(":$PORT")
}
