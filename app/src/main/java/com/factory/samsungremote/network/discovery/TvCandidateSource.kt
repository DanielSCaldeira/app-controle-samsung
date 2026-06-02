package com.factory.samsungremote.network.discovery

import kotlinx.coroutines.flow.Flow

/**
 * A source of TV *candidate* hosts on the local network.
 *
 * Implementations probe the LAN with a particular technique — multicast SSDP
 * ([SsdpCandidateSource]) or mDNS — and emit the IP addresses of devices that
 * *might* be Samsung TVs. They make no guarantee about what answered: the
 * [DiscoveryService] is responsible for validating each candidate via the
 * `/api/v2/` REST endpoint before reporting it.
 *
 * Modelling SSDP and mDNS behind one interface lets the service treat mDNS as a
 * drop-in fallback when SSDP multicast is blocked (ADR-0004) and lets tests
 * substitute a fake source without touching real sockets.
 */
fun interface TvCandidateSource {

    /**
     * Emits the host/IP of each candidate as it is discovered. The returned
     * [Flow] is cold; collection (re)starts the underlying probe and cancelling
     * the collector releases any sockets/listeners it opened. A finite
     * implementation (e.g. SSDP with a response window) completes on its own;
     * a continuous one (e.g. mDNS) runs until cancelled.
     */
    fun candidates(): Flow<String>
}
