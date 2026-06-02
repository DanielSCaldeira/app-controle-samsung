package com.factory.samsungremote.network.wol

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Wake-on-LAN: powers on a TV that is fully off (and therefore unreachable over
 * the control [com.factory.samsungremote.network.session.RemoteSession] socket)
 * by broadcasting a "magic packet" to its hardware [macAddress].
 *
 * A magic packet is a tiny UDP datagram with a fixed shape understood by the
 * network adapter even while the rest of the TV is powered down: **6 bytes of
 * `0xFF` (the synchronization stream) followed by the 6-byte MAC repeated 16
 * times** — 102 bytes total. The adapter scans incoming traffic for this
 * sequence and, on a match for its own MAC, signals the board to power up.
 *
 * The packet format is built by the pure [buildMagicPacket] (no I/O), so it can
 * be unit-tested in isolation; [wake] adds the UDP broadcast around it. The MAC
 * comes from the persisted [com.factory.samsungremote.data.db.KnownTv.macAddress]
 * captured during discovery/pairing.
 */
@Singleton
class WakeOnLan @Inject constructor() {

    /**
     * Broadcasts the [magic packet][buildMagicPacket] for [macAddress] over UDP so
     * a powered-off TV's network adapter wakes the device.
     *
     * Runs on the IO dispatcher (it opens a socket and blocks on send). The send
     * is best-effort: failures (bad MAC, no network, broadcast disallowed) are
     * swallowed and reported as `false` rather than thrown, because this is a
     * fire-and-forget fallback on the control path — the caller reacts to the
     * connection state, not to an exception.
     *
     * @param macAddress       Hardware MAC of the target TV, e.g. `AA:BB:CC:DD:EE:FF`
     *                         (colon- or hyphen-separated).
     * @param broadcastAddress Subnet broadcast address to send to; defaults to the
     *                         limited broadcast `255.255.255.255`.
     * @param port             UDP port; WoL conventionally uses discard port 9.
     * @return `true` if the datagram was sent, `false` if it could not be built or sent.
     */
    suspend fun wake(
        macAddress: String,
        broadcastAddress: String = DEFAULT_BROADCAST_ADDRESS,
        port: Int = DEFAULT_WOL_PORT,
    ): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val packet = buildMagicPacket(macAddress)
            DatagramSocket().use { socket ->
                socket.broadcast = true
                val address = InetAddress.getByName(broadcastAddress)
                socket.send(DatagramPacket(packet, packet.size, address, port))
            }
            true
        }.getOrDefault(false)
    }

    companion object {

        /** Limited-broadcast address used when no subnet broadcast is supplied. */
        const val DEFAULT_BROADCAST_ADDRESS = "255.255.255.255"

        /** Conventional Wake-on-LAN UDP port (the "discard" service port). */
        const val DEFAULT_WOL_PORT = 9

        /** Length of the synchronization stream prefix: six `0xFF` bytes. */
        const val SYNC_STREAM_LENGTH = 6

        /** Number of times the 6-byte MAC is repeated after the sync stream. */
        const val MAC_REPETITIONS = 16

        /** Number of octets in a MAC address. */
        const val MAC_LENGTH = 6

        /** Total magic-packet length: 6 sync bytes + 16 × 6-byte MAC = 102 bytes. */
        const val MAGIC_PACKET_LENGTH = SYNC_STREAM_LENGTH + MAC_REPETITIONS * MAC_LENGTH

        /**
         * Builds the Wake-on-LAN magic packet for [macAddress] (pure, no I/O).
         *
         * The layout is exactly: six `0xFF` bytes, then the parsed 6-byte MAC
         * repeated 16 times, for a total of [MAGIC_PACKET_LENGTH] (102) bytes.
         *
         * @param macAddress Six hex octets separated by `:` or `-`
         *                   (e.g. `AA:BB:CC:DD:EE:FF` or `aa-bb-cc-dd-ee-ff`).
         * @return The 102-byte magic packet.
         * @throws IllegalArgumentException if [macAddress] is not six valid hex octets.
         */
        fun buildMagicPacket(macAddress: String): ByteArray {
            val mac = parseMac(macAddress)
            val packet = ByteArray(MAGIC_PACKET_LENGTH)
            // Synchronization stream: six 0xFF bytes.
            for (i in 0 until SYNC_STREAM_LENGTH) {
                packet[i] = 0xFF.toByte()
            }
            // The MAC repeated 16 times immediately after the sync stream.
            for (repetition in 0 until MAC_REPETITIONS) {
                val offset = SYNC_STREAM_LENGTH + repetition * MAC_LENGTH
                System.arraycopy(mac, 0, packet, offset, MAC_LENGTH)
            }
            return packet
        }

        /**
         * Parses [macAddress] into its six raw bytes, accepting `:` or `-` as the
         * octet separator. Rejects anything that is not exactly six two-digit hex
         * octets.
         */
        private fun parseMac(macAddress: String): ByteArray {
            val octets = macAddress.trim().split(':', '-')
            require(octets.size == MAC_LENGTH) {
                "MAC address must have $MAC_LENGTH octets: '$macAddress'"
            }
            return ByteArray(MAC_LENGTH) { index ->
                val octet = octets[index]
                require(octet.length == 2) {
                    "MAC octet must be two hex digits: '$octet' in '$macAddress'"
                }
                val value = octet.toIntOrNull(radix = 16)
                requireNotNull(value) {
                    "MAC octet is not hexadecimal: '$octet' in '$macAddress'"
                }
                value.toByte()
            }
        }
    }
}
