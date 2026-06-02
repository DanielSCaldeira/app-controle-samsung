package com.factory.samsungremote.network.discovery

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Locates Samsung Smart TVs on the local network and emits each confirmed TV as
 * a [DiscoveredTv].
 *
 * Strategy (ADR-0004):
 *  1. **SSDP first** — query the LAN via multicast UDP ([ssdpSource]).
 *  2. **mDNS fallback** — if SSDP yields no candidate within
 *     [ssdpFallbackTimeoutMs] (common when multicast SSDP is blocked by the
 *     router/AP), also start the mDNS [mdnsSource].
 *  3. Every candidate host from either source is confirmed against the TV's
 *     `GET /api/v2/` endpoint by [validator]; only real Samsung TVs are emitted.
 *
 * Results are de-duplicated by [DiscoveredTv.id], so the same TV seen via both
 * SSDP and mDNS is reported once. Candidates are validated concurrently, so a
 * slow/dead host never blocks discovery of a reachable one — on the happy path
 * a responsive TV surfaces well within a few seconds.
 *
 * The returned flow is cold and keeps probing until its collector is cancelled
 * (mDNS is continuous); callers typically collect it for a bounded window or
 * `take` the first N results.
 *
 * @param ssdpSource            Primary candidate source (SSDP multicast).
 * @param mdnsSource            Fallback candidate source (mDNS).
 * @param validator             Confirms a candidate host is a Samsung TV.
 * @param ssdpFallbackTimeoutMs How long to wait for an SSDP candidate before
 *                              also starting mDNS.
 */
class DiscoveryService(
    private val ssdpSource: TvCandidateSource,
    private val mdnsSource: TvCandidateSource,
    private val validator: TvCandidateValidator,
    private val ssdpFallbackTimeoutMs: Long = DEFAULT_SSDP_FALLBACK_TIMEOUT_MS,
) {

    /**
     * Starts discovery and emits each [DiscoveredTv] as soon as it is confirmed.
     */
    fun discover(): Flow<DiscoveredTv> = channelFlow {
        val producer = this
        val seenIds = Collections.synchronizedSet(HashSet<String>())
        val ssdpProducedCandidate = AtomicBoolean(false)

        // Validate a candidate off the collection path so one slow host does not
        // stall the others; emit it only once (by id) across all sources.
        fun validate(host: String) = producer.launch {
            val tv = validator.validate(host) ?: return@launch
            if (seenIds.add(tv.id)) producer.send(tv)
        }

        val ssdpJob = launch {
            ssdpSource.candidates().collect { host ->
                ssdpProducedCandidate.set(true)
                validate(host)
            }
        }

        val mdnsJob = launch {
            delay(ssdpFallbackTimeoutMs)
            if (!ssdpProducedCandidate.get()) {
                mdnsSource.candidates().collect { host -> validate(host) }
            }
        }

        // Keep the flow open until the collector cancels; structured concurrency
        // tears down both probes and their in-flight validations on close.
        awaitClose {
            ssdpJob.cancel()
            mdnsJob.cancel()
        }
    }

    companion object {
        /**
         * Default grace period before falling back to mDNS. Short enough to stay
         * within the overall discovery budget, long enough for a TV to answer
         * an SSDP `M-SEARCH` on a healthy network.
         */
        const val DEFAULT_SSDP_FALLBACK_TIMEOUT_MS: Long = 1500L
    }
}
