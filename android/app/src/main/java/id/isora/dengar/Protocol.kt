package id.isora.dengar

import org.json.JSONException
import org.json.JSONObject

/** Who answered at an address: enough to show it, and to tell it from anything else on :8080. */
data class DeviceIdentity(val id: String, val name: String)

data class PollEvent(val type: String, val id: Int, val text: String, val ms: Int = 0)

data class PollResult(val seq: Int, val events: List<PollEvent>, val deviceMuted: Boolean)

/**
 * The glasses' "listen on the phone" API (device/server/web_server.py over
 * core/phone_audio.py). The same calls /dengar makes, so the device cannot
 * tell this app from that page and needs no change for it.
 */
object Protocol {
    const val STATUS_PATH = "/status"
    const val LEAVE_PATH = "/listen/leave"

    fun pollPath(client: String, since: Int, muteDevice: Boolean) =
        "/listen/poll?client=$client&since=$since&mute=${if (muteDevice) 1 else 0}"

    fun clipPath(id: Int) = "/listen/clip/$id.wav"

    fun leaveBody(client: String): String = JSONObject().put("client", client).toString()

    /** @throws JSONException on anything that is not a poll answer. */
    fun parsePoll(body: String): PollResult {
        val j = JSONObject(body)
        val events = ArrayList<PollEvent>()
        val arr = j.optJSONArray("events")
        if (arr != null) {
            for (i in 0 until arr.length()) {
                val e = arr.optJSONObject(i) ?: continue
                events += PollEvent(e.optString("type"), e.optInt("id", -1), e.optString("text"), e.optInt("ms", 0))
            }
        }
        return PollResult(j.getInt("seq"), events, j.optBoolean("device_muted", false))
    }

    /** GET /status → who this is, or null when it is not I-Sora (or AuralAI) glasses. */
    fun parseIdentity(body: String): DeviceIdentity? {
        val j = try {
            JSONObject(body)
        } catch (e: JSONException) {
            return null
        }
        val id = j.optString("device_id")
        if (id.isEmpty() || !j.has("mode")) return null
        val name = j.optString("device_name")
            .ifEmpty { j.optString("mdns_host").removeSuffix(".local") }
            .ifEmpty { "isora-$id" }
        return DeviceIdentity(id, name)
    }
}
