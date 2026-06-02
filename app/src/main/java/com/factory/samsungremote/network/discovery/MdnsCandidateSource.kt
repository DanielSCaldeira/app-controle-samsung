package com.factory.samsungremote.network.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/**
 * [TvCandidateSource] that finds TVs via **mDNS / DNS-SD**, using Android's
 * [NsdManager]. This is the fallback the [DiscoveryService] uses when SSDP
 * multicast is blocked on the network (ADR-0004).
 *
 * It browses for the Samsung Multiscreen service type, resolves each found
 * service to its host address, and emits that address as a candidate. As with
 * SSDP, whether the host is genuinely a Samsung TV is decided later by the
 * `/api/v2/` [TvCandidateValidator]; this source only surfaces hosts.
 *
 * mDNS browsing is continuous: the returned flow stays active until its
 * collector is cancelled, at which point discovery is stopped via
 * [NsdManager.stopServiceDiscovery].
 *
 * This class is deliberately the only piece of the discovery package that
 * depends on the Android framework, so the rest of the pipeline stays
 * unit-testable on a plain JVM.
 *
 * @param context     Application context used to obtain the NSD system service.
 * @param serviceType DNS-SD service type to browse; defaults to Samsung's
 *                    Multiscreen Framework type.
 */
class MdnsCandidateSource(
    private val context: Context,
    private val serviceType: String = SAMSUNG_SERVICE_TYPE,
) : TvCandidateSource {

    override fun candidates(): Flow<String> = callbackFlow {
        val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager

        fun resolve(serviceInfo: NsdServiceInfo) {
            nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                override fun onServiceResolved(resolved: NsdServiceInfo) {
                    resolved.host?.hostAddress?.let { trySend(it) }
                }

                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) = Unit
            })
        }

        val discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(serviceInfo: NsdServiceInfo) = resolve(serviceInfo)
            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
            override fun onDiscoveryStarted(serviceType: String) = Unit
            override fun onDiscoveryStopped(serviceType: String) = Unit

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                close(IllegalStateException("mDNS discovery failed to start: $errorCode"))
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) = Unit
        }

        nsdManager.discoverServices(serviceType, NsdManager.PROTOCOL_DNS_SD, discoveryListener)

        awaitClose {
            try {
                nsdManager.stopServiceDiscovery(discoveryListener)
            } catch (_: IllegalArgumentException) {
                // Listener already unregistered (e.g. discovery never started).
            }
        }
    }

    companion object {
        /** DNS-SD service type advertised by Samsung's Multiscreen Framework. */
        const val SAMSUNG_SERVICE_TYPE: String = "_samsungmsf._tcp."
    }
}
