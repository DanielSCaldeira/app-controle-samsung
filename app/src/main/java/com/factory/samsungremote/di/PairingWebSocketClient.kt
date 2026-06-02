package com.factory.samsungremote.di

import javax.inject.Qualifier

/**
 * Qualifies the [okhttp3.OkHttpClient] used for the Samsung control WebSocket
 * (`wss://…:8002`), which trusts the TV's self-signed LAN certificate via
 * [com.factory.samsungremote.network.pairing.LanTrustManager]. Kept distinct
 * from the discovery client (see [DiscoveryHttpClient]) so the relaxed trust
 * settings never leak onto general HTTP traffic.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class PairingWebSocketClient
