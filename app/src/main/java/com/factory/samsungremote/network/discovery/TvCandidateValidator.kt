package com.factory.samsungremote.network.discovery

/**
 * Validates a candidate host discovered on the LAN by querying its Samsung
 * `GET /api/v2/` device-info endpoint.
 *
 * SSDP/mDNS surface *any* responder on the network; this contract is what turns
 * a bare IP into a confirmed [DiscoveredTv] (or rejects it). Keeping it an
 * interface lets the [DiscoveryService] stay transport-agnostic and lets tests
 * inject a fake or point a real validator at a stub HTTP server.
 */
fun interface TvCandidateValidator {

    /**
     * Probes [host] and returns the [DiscoveredTv] it describes, or `null` when
     * the host is unreachable, errors, or is not a Samsung TV. Must never throw
     * for ordinary network failures — an unreachable candidate is simply not a
     * TV.
     */
    suspend fun validate(host: String): DiscoveredTv?
}
