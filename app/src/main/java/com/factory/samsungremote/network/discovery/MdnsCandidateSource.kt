package com.factory.samsungremote.network.discovery

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

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

        fun resolve(serviceInfo: NsdServiceInfo) {
            // A fresh ResolveListener per call: NsdManager rejects a listener
            // that is already in use by an in-flight resolve.
            nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                override fun onServiceResolved(resolved: NsdServiceInfo) {
                    resolved.host?.hostAddress?.let { trySend(it) }
                }

                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) = Unit
            })
        }

        // One DiscoveryListener per service type, all feeding this flow. A type
        // that fails to start is skipped (not fatal) so the others keep running.
        val listeners = serviceTypes.map { type ->
            val listener = object : NsdManager.DiscoveryListener {
                override fun onServiceFound(serviceInfo: NsdServiceInfo) = resolve(serviceInfo)
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
    }
}
