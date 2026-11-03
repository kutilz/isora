package id.isora.dengar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SubnetTest {

    private fun ip(s: String) = Subnet.parse(s)!!

    @Test
    fun parseAndFormatRoundTrip() {
        assertEquals("192.168.1.37", Subnet.format(ip("192.168.1.37")))
        assertEquals("10.96.246.254", Subnet.format(ip("10.96.246.254")))
        assertNull(Subnet.parse("192.168.1"))
        assertNull(Subnet.parse("1.2.3.256"))
        assertNull(Subnet.parse("isora-88dd.local"))
        assertEquals(ip("192.168.1.37"), Subnet.toInt(byteArrayOf(192.toByte(), 168.toByte(), 1, 37)))
    }

    @Test
    fun containment() {
        assertTrue(Subnet.contains(ip("10.96.246.1"), 24, ip("10.96.246.200")))
        assertFalse(Subnet.contains(ip("10.96.246.1"), 24, ip("10.96.247.1")))
        assertTrue(Subnet.contains(ip("192.168.0.1"), 16, ip("192.168.200.9")))
        assertTrue(Subnet.contains(ip("8.8.8.8"), 0, ip("1.1.1.1")))
    }

    @Test
    fun onlyPrivateRangesAreEverSwept() {
        for (s in listOf("10.0.0.1", "10.96.246.7", "172.16.0.1", "172.31.255.1", "192.168.1.51")) {
            assertTrue(s, Subnet.isPrivate(ip(s)))
        }
        // 100.64/10 is carrier NAT (and Tailscale): not the phone's own LAN.
        for (s in listOf("172.32.0.1", "100.64.0.1", "100.79.217.125", "8.8.8.8", "192.169.0.1")) {
            assertFalse(s, Subnet.isPrivate(ip(s)))
        }
    }

    @Test
    fun theSweepIsTheRestOfTheSlash24() {
        val n = Subnet.neighbours24(ip("192.168.1.51"))
        assertEquals(253, n.size)
        assertFalse(ip("192.168.1.51") in n)
        assertEquals("192.168.1.1", Subnet.format(n.first()))
        assertEquals("192.168.1.254", Subnet.format(n.last()))
    }

    @Test
    fun typedAddresses() {
        assertEquals("192.168.1.37:8080", Address.normalize("192.168.1.37"))
        assertEquals("192.168.1.37:8080", Address.normalize("http://192.168.1.37:8080/dengar"))
        assertEquals("10.0.0.5:9000", Address.normalize("  10.0.0.5:9000 "))
        assertEquals("isora-88dd.local:8080", Address.normalize("isora-88dd.local"))
        assertNull(Address.normalize(""))
        assertNull(Address.normalize("192.168.1.37 8080"))
        assertNull(Address.normalize("1.2.3.4:x"))
        assertNull(Address.normalize("1.2.3.4:70000"))
        assertEquals("192.168.1.37", Address.display("192.168.1.37:8080"))
        assertEquals("10.0.0.5:9000", Address.display("10.0.0.5:9000"))
    }

    @Test
    fun dhcpInfoAddressesAreLittleEndian() {
        // 192.168.43.1 as DhcpInfo stores it.
        assertEquals("192.168.43.1", Subnet.format(Subnet.fromLittleEndian(0x012BA8C0)))
    }

    @Test
    fun hotspotInterfacesAreLocalWhateverTheVendorCallsThem() {
        for (name in listOf("wlan0", "wlan1", "swlan0", "ap0", "softap0", "ap_br_wlan2", "wifi_ap", "rndis0", "eth0", "bridge0", "wigig0")) {
            assertFalse(name, Failure.isNotLocal(name))
        }
    }

    @Test
    fun mobileDataAndTunnelsAreNotLocal() {
        for (name in listOf("rmnet_data0", "rmnet0", "r_rmnet_data1", "ccmni1", "v4-rmnet_data0", "tun0", "ppp0", "lo", "dummy0", "ipsec1", "epdg2", "clat4")) {
            assertTrue(name, Failure.isNotLocal(name))
        }
    }

    @Test
    fun onlyARefusedSocketCountsAsTheBlockingKind() {
        assertEquals("EPERM", Failure.blocking("failed to connect to /10.0.0.1 (port 8080): socket failed: EPERM (Operation not permitted)"))
        assertEquals("ENETUNREACH", Failure.blocking("connect failed: ENETUNREACH (Network is unreachable)"))
        assertNull(Failure.blocking("failed to connect to /10.0.0.1 (port 8080) after 800ms"))
        assertNull(Failure.blocking("failed to connect: ECONNREFUSED (Connection refused)"))
        assertNull(Failure.blocking(null))
    }
}
