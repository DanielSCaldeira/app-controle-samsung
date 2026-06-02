package com.factory.samsungremote.network.discovery

/**
 * A Samsung Smart TV found on the local network by the [DiscoveryService].
 *
 * This is the discovery-layer view of a TV: just enough to show it in the
 * "choose a TV" list and to connect to it. It is intentionally decoupled from
 * the persisted [com.factory.samsungremote.data.db.KnownTv] record — discovery
 * produces transient candidates, while the stored record additionally carries
 * pairing tokens and connection history. Turning a discovered TV into a stored
 * record is the job of the layer that wires discovery to the
 * [com.factory.samsungremote.data.registry.TvRegistry].
 *
 * @property id        Stable identifier of the TV (the device UUID reported by
 *                     the `/api/v2/` endpoint, e.g. `uuid:...`). Used to
 *                     de-duplicate the same TV seen via both SSDP and mDNS.
 * @property name      Human-readable name for the UI (e.g. `[TV] Living Room`).
 * @property ipAddress IPv4/IPv6 address the TV answered from on the LAN.
 * @property modelName Marketing/model name (e.g. `UN50MU6300`) when reported by
 *                     the TV, otherwise `null`.
 */
data class DiscoveredTv(
    val id: String,
    val name: String,
    val ipAddress: String,
    val modelName: String? = null,
)
