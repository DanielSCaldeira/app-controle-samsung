package com.factory.samsungremote.network.pairing

import okhttp3.OkHttpClient
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Dedicated [X509TrustManager] that accepts the TV's TLS certificate for the
 * LAN control session (ADR-0003 risk mitigation).
 *
 * Newer Samsung Tizen sets serve the remote-control WebSocket over `wss://` on
 * port `8002` using a **self-signed** certificate whose CN does not match the
 * device IP. Such a certificate can never chain to a public CA, so the platform
 * default trust manager rejects it and the handshake fails. Because the traffic
 * never leaves the local network and the user has physically authorized the
 * device on the TV screen, we deliberately trust the presented certificate for
 * this purpose only.
 *
 * This trust manager is intentionally scoped to the pairing/remote WebSocket
 * client built by [trustingClient]; it must **not** be installed on any client
 * used for general internet traffic.
 */
class LanTrustManager : X509TrustManager {

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    companion object {

        /**
         * Returns an [OkHttpClient] derived from [base] that trusts the TV's
         * self-signed certificate via a [LanTrustManager].
         *
         * The hostname verifier is also relaxed because the certificate CN of a
         * Samsung TV does not match the LAN IP it is reached on. Both relaxations
         * apply only to the returned client; [base]'s configuration (timeouts,
         * interceptors) is otherwise preserved.
         */
        fun trustingClient(base: OkHttpClient = OkHttpClient()): OkHttpClient {
            val trustManager = LanTrustManager()
            val sslContext = SSLContext.getInstance("TLS").apply {
                init(null, arrayOf<TrustManager>(trustManager), null)
            }
            return base.newBuilder()
                .sslSocketFactory(sslContext.socketFactory, trustManager)
                .hostnameVerifier { _, _ -> true }
                .build()
        }
    }
}
