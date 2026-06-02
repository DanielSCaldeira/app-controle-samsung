package com.factory.samsungremote.di

import javax.inject.Qualifier

/**
 * Qualifies the [okhttp3.OkHttpClient] used for the long-lived
 * [com.factory.samsungremote.network.session.RemoteSession] control WebSocket
 * (`wss://…:8002`).
 *
 * Like [PairingWebSocketClient] it trusts the TV's self-signed LAN certificate
 * via [com.factory.samsungremote.network.pairing.LanTrustManager], but it is a
 * distinct client configured with a ping interval so dropped links are detected
 * promptly and the session can reconnect. Kept separate from the discovery and
 * pairing clients so the relaxed trust never leaks onto other traffic.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class SessionWebSocketClient
