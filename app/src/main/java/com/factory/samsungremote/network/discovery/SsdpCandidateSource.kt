package com.factory.samsungremote.network.discovery

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import java.net.DatagramPacket
import java.net.InetAddress
import java.net.MulticastSocket
import java.net.SocketTimeoutException

/**
 * [TvCandidateSource] that finds TVs via **SSDP** — an `M-SEARCH` query sent to
 * the SSDP multicast group (`239.255.255.250:1900`) over UDP.
 *
 * For each `HTTP/1.1 200 OK` response it extracts a candidate host (the `LOCATION`
 * header's URL host, falling back to the packet's source address) and emits it.
 * Validation of whether the responder is actually a Samsung TV is left to the
 * [DiscoveryService] / [TvCandidateValidator]; this source only widens the net.
 *
 * The flow is finite: it sends the search requests, then reads responses until
 * the socket read times out ([responseTimeoutMs]), keeping the whole sweep well
 * within the discovery budget. All blocking socket I/O runs on [ioDispatcher].
 *
 * @param multicastGroup   SSDP multicast address.
 * @param multicastPort    SSDP port.
 * @param responseTimeoutMs Per-receive socket timeout; also bounds total sweep.
 * @param searchTargets    `ST` values to query; covers Samsung's UPnP device
 *                         type plus the generic `ssdp:all`.
 * @param ioDispatcher     Dispatcher the socket work runs on.
 */
class SsdpCandidateSource(
    private val multicastGroup: String = SSDP_MULTICAST_ADDRESS,
    private val multicastPort: Int = SSDP_PORT,
    private val responseTimeoutMs: Int = DEFAULT_RESPONSE_TIMEOUT_MS,
    private val searchTargets: List<String> = DEFAULT_SEARCH_TARGETS,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : TvCandidateSource {

    override fun candidates(): Flow<String> = flow {
        val group = InetAddress.getByName(multicastGroup)
        val socket = MulticastSocket()
        socket.reuseAddress = true
        socket.soTimeout = responseTimeoutMs
        try {
            searchTargets.forEach { target ->
                val payload = buildMSearch(target).toByteArray(Charsets.US_ASCII)
                socket.send(DatagramPacket(payload, payload.size, group, multicastPort))
            }

            val buffer = ByteArray(RECEIVE_BUFFER_BYTES)
            while (currentCoroutineContext().isActive) {
                val packet = DatagramPacket(buffer, buffer.size)
                try {
                    socket.receive(packet)
                } catch (_: SocketTimeoutException) {
                    break
                }
                val response = String(packet.data, 0, packet.length, Charsets.US_ASCII)
                val host = extractLocationHost(response) ?: packet.address?.hostAddress
                if (!host.isNullOrBlank()) emit(host)
            }
        } finally {
            socket.close()
        }
    }.flowOn(ioDispatcher)

    private fun buildMSearch(searchTarget: String): String =
        buildString {
            append("M-SEARCH * HTTP/1.1\r\n")
            append("HOST: ").append(multicastGroup).append(':').append(multicastPort).append("\r\n")
            append("MAN: \"ssdp:discover\"\r\n")
            append("MX: ").append(MX_SECONDS).append("\r\n")
            append("ST: ").append(searchTarget).append("\r\n")
            append("\r\n")
        }

    /** Extracts the host from the `LOCATION` header URL, or `null` if absent/unparseable. */
    private fun extractLocationHost(response: String): String? {
        val match = LOCATION_REGEX.find(response) ?: return null
        val location = match.groupValues[1].trim()
        return try {
            java.net.URI(location).host
        } catch (_: Exception) {
            null
        }
    }

    companion object {
        /** Standard SSDP multicast address (RFC / UPnP). */
        const val SSDP_MULTICAST_ADDRESS: String = "239.255.255.250"

        /** Standard SSDP port. */
        const val SSDP_PORT: Int = 1900

        /** Default per-receive timeout that also bounds the whole sweep. */
        const val DEFAULT_RESPONSE_TIMEOUT_MS: Int = 3000

        /** Maximum wait (`MX`) advertised to responders, in seconds. */
        private const val MX_SECONDS: Int = 2

        private const val RECEIVE_BUFFER_BYTES: Int = 2048

        /** Search targets: Samsung's remote-control UPnP type, plus a wildcard. */
        val DEFAULT_SEARCH_TARGETS: List<String> = listOf(
            "urn:samsung.com:device:RemoteControlReceiver:1",
            "urn:dial-multiscreen-org:service:dial:1",
            "ssdp:all",
        )

        private val LOCATION_REGEX = Regex("(?im)^LOCATION:\\s*(\\S+)\\s*$")
    }
}
