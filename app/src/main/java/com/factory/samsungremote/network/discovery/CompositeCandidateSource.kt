package com.factory.samsungremote.network.discovery

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.merge

/**
 * [TvCandidateSource] that runs several sources concurrently and emits the union
 * of their candidates on a single [Flow].
 *
 * Used to widen the fallback net: mDNS (for sets that advertise a usable
 * service) merged with a subnet sweep (for sets that don't). De-duplication of
 * the resulting hosts — and validation — remains the [DiscoveryService]'s job,
 * so overlap between sources is harmless.
 *
 * @param sources The delegate sources; their cold flows are merged and started
 *                when this source is collected, and all are cancelled together.
 */
class CompositeCandidateSource(
    private val sources: List<TvCandidateSource>,
) : TvCandidateSource {

    override fun candidates(): Flow<String> =
        merge(*sources.map { it.candidates() }.toTypedArray())
}
