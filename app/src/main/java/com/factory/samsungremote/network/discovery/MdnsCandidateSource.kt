package com.factory.samsungremote.network.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.Collections
import kotlin.coroutines.resume

/**
 * [TvCandidateSource] that finds TVs via **mDNS / DNS-SD**, using Android's
 * [NsdManager]. This is the fallback the [DiscoveryService] uses when SSDP
 * multicast is unavailable (ADR-0004) — and on modern Samsung TVs it is in
 * practice the *primary* path, since they often drop the UPnP/SSDP responder.
 *
 * It browses every type in [serviceTypes], resolves each found service to its
 * host address, and emits that address as a candidate. Whether the host is
 * genuinely a Samsung TV is decided later by the `/api/v2/`
 * [TvCandidateValidator]; this source only surfaces hosts, so advertising a
 * broad type like AirPlay is safe — non-Samsung responders fail validation.
 *
 * Why more than one type: recent Samsung TVs (e.g. 2024 Q60D-class) no longer
 * advertise `_samsungmsf._tcp` but *do* advertise `_airplay._tcp` (TXT
 * `manufacturer=Samsung`). Browsing both is what makes those sets discoverable.
 *
 * **Resolution is serialized.** On Android ≤13 [NsdManager.resolveService]
 * handles a single resolve at a time; firing one while another is in flight
 * fails with `FAILURE_ALREADY_ACTIVE`. With two browses running, concurrent
 * resolves would silently drop the TV. Found services are therefore queued and
 * resolved one-by-one (with a timeout and a short retry on contention).
 *
 * mDNS browsing is continuous: the returned flow stays active until its
 * collector is cancelled, at which point every browse is stopped via
 * [NsdManager.stopServiceDiscovery].
 *
 * This class is deliberately the only piece of the discovery package that
 * depends on the Android framework, so the rest of the pipeline stays
 * unit-testable on a plain JVM.
 *
 * @param context      Application context used to obtain the NSD/Wi-Fi services.
 * @param serviceTypes DNS-SD service types to browse; defaults to Samsung's
 *                     Multiscreen Framework type plus AirPlay.
 */
class MdnsCandidateSource(
    private val context: Context,
    private val serviceTypes: List<String> = DEFAULT_SERVICE_TYPES,
) : TvCandidateSource {

    override fun candidates(): Flow<String> = callbackFlow {
        // Android drops inbound multicast (incl. mDNS at 224.0.0.251) at the
        // Wi-Fi driver unless a MulticastLock is held. Without this, NsdManager
        // browses but never sees the TV's mDNS announcement.
        val wifiManager = context.applicationContext
            .getSystemService(Context.WIFI_SERVICE) as WifiManager
        val multicastLock = wifiManager.createMulticastLock(MULTICAST_LOCK_TAG).apply {
            setReferenceCounted(false)
            acquire()
        }

        val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager

        // Queue of found services awaiting resolution, drained sequentially.
        val toResolve = Channel<NsdServiceInfo>(Channel.UNLIMITED)
        val seen = Collections.synchronizedSet(HashSet<String>())

        // Single consumer: one resolve at a time, so we never trip ALREADY_ACTIVE.
        launch {
            for (info in toResolve) {
                resolveHost(nsdManager, info)?.let { trySend(it) }
            }
        }

        // One DiscoveryListener per service type, all enqueuing to the resolver.
        // A type that fails to start is skipped (not fatal) so others keep going.
        val listeners = serviceTypes.map { type ->
            val listener = object : NsdManager.DiscoveryListener {
                override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                    val key = "${serviceInfo.serviceType}/${serviceInfo.serviceName}"
                    if (seen.add(key)) toResolve.trySend(serviceInfo)
                }

                override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
                override fun onDiscoveryStarted(serviceType: String) = Unit
                override fun onDiscoveryStopped(serviceType: String) = Unit
                override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
                override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
            }
            nsdManager.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, listener)
            listener
        }

        awaitClose {
            toResolve.close()
            listeners.forEach { listener ->
                try {
                    nsdManager.stopServiceDiscovery(listener)
                } catch (_: IllegalArgumentException) {
                    // Listener already unregistered (e.g. discovery never started).
                }
            }
            if (multicastLock.isHeld) multicastLock.release()
        }
    }

    /**
     * Resolves one service to its host address, retrying briefly while
     * [NsdManager] is busy with another resolve. Returns `null` on hard failure
     * or timeout rather than throwing, so a single bad service never stalls the
     * queue.
     */
    private suspend fun resolveHost(nsdManager: NsdManager, info: NsdServiceInfo): String? {
        repeat(MAX_RESOLVE_ATTEMPTS) { attempt ->
            val result = withTimeoutOrNull(RESOLVE_TIMEOUT_MS) {
                suspendCancellableCoroutine { cont ->
                    nsdManager.resolveService(info, object : NsdManager.ResolveListener {
                        override fun onServiceResolved(resolved: NsdServiceInfo) {
                            if (cont.isActive) cont.resume(Result.success(resolved.host?.hostAddress))
                        }

                        override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                            if (cont.isActive) cont.resume(Result.failure(ResolveError(errorCode)))
                        }
                    })
                }
            }
            when {
                result == null -> return null // timed out
                result.isSuccess -> return result.getOrNull()
                // Only ALREADY_ACTIVE is worth retrying; other failures are terminal.
                (result.exceptionOrNull() as? ResolveError)?.code != NsdManager.FAILURE_ALREADY_ACTIVE ->
                    return null
                else -> if (attempt < MAX_RESOLVE_ATTEMPTS - 1) delay(RESOLVE_RETRY_DELAY_MS)
            }
        }
        return null
    }

    private class ResolveError(val code: Int) : Exception()

    companion object {
        /** DNS-SD service type advertised by Samsung's Multiscreen Framework. */
        const val SAMSUNG_SERVICE_TYPE: String = "_samsungmsf._tcp."

        /** AirPlay type; newer Samsung TVs advertise this instead of MSF. */
        const val AIRPLAY_SERVICE_TYPE: String = "_airplay._tcp."

        /** Service types browsed by default, broadest-useful net for Samsung TVs. */
        val DEFAULT_SERVICE_TYPES: List<String> = listOf(
            SAMSUNG_SERVICE_TYPE,
            AIRPLAY_SERVICE_TYPE,
        )

        /** Tag for the Wi-Fi [WifiManager.MulticastLock] held during mDNS browsing. */
        private const val MULTICAST_LOCK_TAG: String = "samsung-remote-mdns"

        private const val MAX_RESOLVE_ATTEMPTS: Int = 3
        private const val RESOLVE_TIMEOUT_MS: Long = 4000L
        private const val RESOLVE_RETRY_DELAY_MS: Long = 250L
    }
}
