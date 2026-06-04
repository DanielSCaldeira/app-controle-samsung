package com.factory.samsungremote.network.discovery

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket

/**
 * [TvCandidateSource] that sweeps the device's local `/24` subnet for hosts with
 * the Samsung device-info port open and emits those as candidates, so the
 * [DiscoveryService]'s `/api/v2/` validator can confirm whichever one is the TV.
 *
 * This is the reliable backstop for discovery: SSDP and mDNS depend on the TV
 * advertising a service the app browses for, but modern Samsung sets are
 * inconsistent about that (some only advertise AirPlay, some nothing resolvable),
 * while port `8001` is always reachable on the LAN.
 *
 * **Why a TCP port probe rather than HTTP-validating every host:** firing 254
 * simultaneous HTTPS validations saturates a phone's Wi-Fi stack (observed: a
 * driver fatal-event that drops *all* connections, including the TV's). Instead
 * this source does cheap, **concurrency-capped** TCP connects ([maxConcurrency])
 * with a short [connectTimeoutMs], emitting only the few hosts that actually
 * listen on [probePort]. The validator then runs on just those.
 *
 * The sweep is bounded to a single `/24` derived from the Wi-Fi interface's own
 * IPv4 address; if no such address is found the flow emits nothing. It is finite
 * — it completes once every host has been probed.
 *
 * @param probePort            Port to test (Samsung device-info port, `8001`).
 * @param maxConcurrency       Cap on simultaneous in-flight probes (Wi-Fi-safe).
 * @param connectTimeoutMs     Per-host TCP connect timeout.
 * @param localAddressProvider Supplies the device's site-local IPv4; overridable
 *                             in tests.
 * @param ioDispatcher         Dispatcher the blocking socket probes run on.
 */
class SubnetScanCandidateSource(
    private val probePort: Int = DEFAULT_PROBE_PORT,
    private val maxConcurrency: Int = DEFAULT_MAX_CONCURRENCY,
    private val connectTimeoutMs: Int = DEFAULT_CONNECT_TIMEOUT_MS,
    private val localAddressProvider: () -> Inet4Address? = ::defaultSiteLocalIpv4,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : TvCandidateSource {

    override fun candidates(): Flow<String> = channelFlow {
        val local = localAddressProvider() ?: return@channelFlow
        val bytes = local.address
        val prefix = "${bytes[0].toInt() and 0xFF}." +
            "${bytes[1].toInt() and 0xFF}." +
            "${bytes[2].toInt() and 0xFF}."
        val self = bytes[3].toInt() and 0xFF
        val gate = Semaphore(maxConcurrency)

        coroutineScope {
            for (host in HOST_MIN..HOST_MAX) {
                if (host == self) continue
                val ip = "$prefix$host"
                launch {
                    gate.withPermit {
                        if (isPortOpen(ip)) trySend(ip)
                    }
                }
            }
        }
    }.flowOn(ioDispatcher)

    private fun isPortOpen(ip: String): Boolean = try {
        Socket().use { socket ->
            socket.connect(InetSocketAddress(ip, probePort), connectTimeoutMs)
            true
        }
    } catch (_: Exception) {
        false
    }

    companion object {
        private const val DEFAULT_PROBE_PORT = 8001
        private const val DEFAULT_MAX_CONCURRENCY = 24
        private const val DEFAULT_CONNECT_TIMEOUT_MS = 600
        private const val HOST_MIN = 1
        private const val HOST_MAX = 254

        /**
         * First up, non-loopback, site-local IPv4 across the device's interfaces
         * (the Wi-Fi/LAN address on a phone), or `null` if none is present.
         */
        fun defaultSiteLocalIpv4(): Inet4Address? = runCatching {
            NetworkInterface.getNetworkInterfaces()
                ?.toList()
                ?.asSequence()
                ?.filter { it.isUp && !it.isLoopback }
                ?.flatMap { it.inetAddresses.toList().asSequence() }
                ?.filterIsInstance<Inet4Address>()
                ?.firstOrNull { it.isSiteLocalAddress }
        }.getOrNull()
    }
}
