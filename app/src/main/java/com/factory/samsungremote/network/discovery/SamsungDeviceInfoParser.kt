package com.factory.samsungremote.network.discovery

import org.json.JSONObject

/**
 * Parses the JSON returned by a Samsung TV's `GET /api/v2/` endpoint into a
 * [DiscoveredTv].
 *
 * This object is the single point that understands the shape of the `/api/v2/`
 * device-info document, mirroring the protocol-isolation choice made for the
 * WebSocket layer (ADR-0003): network code stays free of JSON details and the
 * mapping lives — and is unit-tested — in one place. It is intentionally pure
 * (no I/O), so it can be exercised directly against captured fixtures.
 *
 * A representative response looks like:
 * ```json
 * {
 *   "device": {
 *     "id": "uuid:0000...",
 *     "name": "[TV] Living Room",
 *     "modelName": "UN50MU6300",
 *     "type": "Samsung SmartTV",
 *     "OS": "Tizen",
 *     "ip": "192.168.1.50",
 *     "wifiMac": "aa:bb:cc:dd:ee:ff"
 *   },
 *   "id": "uuid:0000...",
 *   "name": "[TV] Living Room",
 *   "type": "Samsung SmartTV",
 *   "version": "2.0.25"
 * }
 * ```
 */
object SamsungDeviceInfoParser {

    /**
     * Parses [json] into a [DiscoveredTv], or returns `null` when the payload is
     * not valid JSON or does not describe a Samsung TV.
     *
     * A candidate is accepted only when it identifies itself as a Samsung device
     * (its `type` mentions "Samsung" or it runs the "Tizen" OS) — this is what
     * lets discovery validate candidates and discard unrelated SSDP/mDNS
     * responders on the network.
     *
     * @param json       Raw response body from `GET /api/v2/`.
     * @param fallbackIp IP the request was sent to; used as the TV address when
     *                   the document does not echo back its own `device.ip`.
     * @return the parsed [DiscoveredTv], or `null` if not a Samsung TV.
     */
    fun parse(json: String, fallbackIp: String): DiscoveredTv? {
        val root = json.toJsonObjectOrNull() ?: return null
        val device = root.optJSONObject("device")

        if (!isSamsung(root, device)) return null

        val id = firstNonBlank(
            device?.optString("id"),
            device?.optString("duid"),
            root.optString("id"),
            device?.optString("wifiMac"),
        ) ?: return null

        val ip = firstNonBlank(device?.optString("ip"), fallbackIp) ?: return null

        val modelName = firstNonBlank(device?.optString("modelName"))
        val name = firstNonBlank(
            device?.optString("name"),
            root.optString("name"),
            modelName,
        ) ?: id

        return DiscoveredTv(
            id = id,
            name = name,
            ipAddress = ip,
            modelName = modelName,
        )
    }

    private fun isSamsung(root: JSONObject, device: JSONObject?): Boolean {
        val type = firstNonBlank(device?.optString("type"), root.optString("type")).orEmpty()
        val os = device?.optString("OS").orEmpty()
        return type.contains("samsung", ignoreCase = true) ||
            os.equals("Tizen", ignoreCase = true)
    }

    /** Returns the first argument that is non-`null` and not blank, else `null`. */
    private fun firstNonBlank(vararg values: String?): String? =
        values.firstOrNull { !it.isNullOrBlank() }?.trim()

    private fun String.toJsonObjectOrNull(): JSONObject? =
        try {
            JSONObject(this)
        } catch (_: Exception) {
            null
        }
}
