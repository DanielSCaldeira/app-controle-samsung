package com.factory.samsungremote.network.discovery

import com.factory.samsungremote.data.db.KnownTv
import com.factory.samsungremote.data.registry.TvRegistry
import com.factory.samsungremote.network.session.RemoteSession
import kotlinx.coroutines.flow.firstOrNull
import kotlinx.coroutines.withTimeoutOrNull
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Outcome of a [TvReconciler.reconcileAndReconnect] attempt.
 *
 * Reconciliation is a no-throw operation: a TV that cannot be re-found on the LAN
 * is a routine condition (it may simply be powered off), not an error, so the
 * result is modelled explicitly instead of via exceptions.
 */
sealed interface ReconcileResult {

    /**
     * The TV was re-found by its device id and the session was (re)connected.
     *
     * @property ipAddress The current LAN address the session was pointed at.
     * @property ipChanged `true` when [ipAddress] differed from the stored
     *                     [KnownTv.ipAddress] (i.e. the DHCP lease had moved and
     *                     [TvRegistry.updateIp] was applied), `false` when the
     *                     stored address was still current.
     */
    data class Reconnected(val ipAddress: String, val ipChanged: Boolean) : ReconcileResult

    /**
     * No candidate matching the TV's device id surfaced within the discovery
     * window. The registry is left untouched and no connection is attempted.
     */
    data object NotFound : ReconcileResult
}

/**
 * Reconciles a [KnownTv]'s last-known IP with its *current* LAN address and
 * reconnects the session to it.
 *
 * This closes the DHCP-lease-churn risk (architecture §8): a TV reachable at one
 * IP can silently move to another after a lease renewal or reboot, leaving the
 * persisted [KnownTv.ipAddress] stale — a blind reconnect would then hammer the
 * wrong host. The TV's device id (UUID) is stable, however, so reconciliation:
 *
 *  1. re-runs SSDP/mDNS discovery ([DiscoveryService], ADR-0004) and picks the
 *     candidate whose [DiscoveredTv.id] equals the stored [KnownTv.id];
 *  2. if that candidate's IP differs from the stored one, persists the new
 *     address with [TvRegistry.updateIp] **before** reconnecting, so the registry
 *     and the live session never disagree; and
 *  3. hands the fresh address (replaying the stored pairing token) to
 *     [RemoteSession.connect].
 *
 * Discovery is bounded by [discoveryTimeoutMillis] because the underlying flow is
 * continuous (mDNS keeps probing); if the device id is not seen within that
 * window the attempt resolves to [ReconcileResult.NotFound] without touching the
 * registry or the session.
 *
 * @param discoveryService     LAN discovery pipeline used to re-locate the TV.
 * @param registry             Source of the stored token and sink for the
 *                             updated IP.
 * @param session              The single live connection that gets re-pointed at
 *                             the current address.
 * @param discoveryTimeoutMillis Upper bound on how long to wait for the device id
 *                             to reappear before giving up.
 */
@Singleton
class TvReconciler @Inject constructor(
    private val discoveryService: DiscoveryService,
    private val registry: TvRegistry,
    private val session: RemoteSession,
    private val discoveryTimeoutMillis: Long = DEFAULT_DISCOVERY_TIMEOUT_MILLIS,
) {

    /**
     * Re-finds [tv] by its device id, updates its stored IP if the lease moved,
     * and reconnects the session to the current address.
     *
     * @return [ReconcileResult.Reconnected] (with whether the IP changed) when the
     *         TV was re-found and the session re-pointed; [ReconcileResult.NotFound]
     *         when no candidate with [tv]'s id surfaced within
     *         [discoveryTimeoutMillis].
     */
    suspend fun reconcileAndReconnect(tv: KnownTv): ReconcileResult {
        val rediscovered = rediscoverById(tv.id) ?: return ReconcileResult.NotFound

        val newIp = rediscovered.ipAddress
        val ipChanged = newIp != tv.ipAddress
        // Persist the new address by device id BEFORE reconnecting, so a later
        // reconnect (or another caller reading the registry) uses the live IP.
        if (ipChanged) {
            registry.updateIp(tv.id, newIp)
        }

        val token = registry.getToken(tv.id)
        val target = DiscoveredTv(
            id = tv.id,
            name = rediscovered.name,
            ipAddress = newIp,
            modelName = rediscovered.modelName,
        )
        session.connect(target, token)

        return ReconcileResult.Reconnected(ipAddress = newIp, ipChanged = ipChanged)
    }

    /**
     * Collects discovery until a candidate matching [deviceId] appears, or returns
     * `null` once [discoveryTimeoutMillis] elapses. Matching the first candidate by
     * id cancels the (otherwise continuous) discovery flow.
     */
    private suspend fun rediscoverById(deviceId: String): DiscoveredTv? =
        withTimeoutOrNull(discoveryTimeoutMillis) {
            discoveryService.discover().firstOrNull { it.id == deviceId }
        }

    companion object {
        /**
         * Default discovery window for reconciliation. Aligned with the overall
         * discovery budget (architecture §7: descoberta completa < 5 s).
         */
        const val DEFAULT_DISCOVERY_TIMEOUT_MILLIS: Long = 5_000L
    }
}
