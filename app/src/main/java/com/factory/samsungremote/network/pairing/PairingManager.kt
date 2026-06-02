package com.factory.samsungremote.network.pairing

import com.factory.samsungremote.data.db.KnownTv
import com.factory.samsungremote.data.registry.TvRegistry
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.protocol.TizenProtocol
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.nio.charset.StandardCharsets
import java.util.Base64
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Performs the Samsung Tizen pairing handshake and obtains the authorization
 * token a [com.factory.samsungremote.network.session.RemoteSession] later needs.
 *
 * Flow (ADR-0003, architecture §5):
 *  1. Open a WebSocket to `wss://<ip>:8002/api/v2/channels/samsung.remote.control`
 *     carrying the controller name Base64-encoded in the `name` query parameter.
 *     The connection goes through a [LanTrustManager]-backed client so the TV's
 *     self-signed certificate is accepted for this LAN session only.
 *  2. The TV shows an on-screen authorization prompt. When the user accepts, the
 *     TV's `ms.channel.connect` event carries `data.token`.
 *  3. The token is extracted (via [TizenProtocol]) and persisted — encrypted —
 *     through [TvRegistry], keyed on the TV's id.
 *
 * **Renewal.** When the registry already holds a token for the TV, it is sent
 * back in the `token` query parameter so an already-authorized device skips the
 * prompt; whatever token the TV returns (a refreshed one, or the same one) is
 * re-persisted. If the TV re-confirms the connection without re-issuing a token,
 * the existing token is kept.
 *
 * **Errors.** Authorization denial, connection failure and a token-less
 * handshake all surface as a treatable [PairingException] carrying a
 * [PairingFailureReason]; the underlying transport [Throwable] is preserved as
 * the cause.
 *
 * @param registry      Where the obtained token is persisted (encrypted).
 * @param socketFactory Factory for the control WebSocket. In production this is
 *                      an OkHttp client built with [LanTrustManager]; tests pass
 *                      a factory pointing at a fake/`MockWebServer`.
 * @param appName       Human-readable controller name shown on the TV; sent
 *                      Base64-encoded as the `name` query parameter.
 * @param port          Control WebSocket port; Samsung's secure default is 8002.
 * @param scheme        URL scheme; `wss` for the TLS control endpoint.
 */
@Singleton
class PairingManager @Inject constructor(
    private val registry: TvRegistry,
    private val socketFactory: WebSocket.Factory,
    private val appName: String = DEFAULT_APP_NAME,
    private val port: Int = DEFAULT_PAIRING_PORT,
    private val scheme: String = DEFAULT_SCHEME,
) {

    /**
     * Pairs with (or renews the token of) [tv] and returns the authorization
     * token, having already persisted it via [TvRegistry].
     *
     * Honours an existing stored token for renewal: if one is present it is
     * replayed in the handshake so the TV need not re-prompt.
     *
     * @throws PairingException if the user denies access, the connection fails,
     *         or the TV never returns a token.
     */
    suspend fun pair(tv: DiscoveredTv): String {
        val existingToken = registry.getToken(tv.id)
        val token = handshake(tv, existingToken)
        registry.saveTv(tv.toKnownTv(), token)
        return token
    }

    /**
     * Opens the control WebSocket and suspends until the TV delivers a token,
     * rejects the device, or the connection fails.
     *
     * [existingToken], when non-`null`, is replayed in the URL (renewal) and used
     * as the fallback result when the TV re-confirms without issuing a new token.
     */
    private suspend fun handshake(
        tv: DiscoveredTv,
        existingToken: String?,
    ): String = suspendCancellableCoroutine { continuation ->
        val request = Request.Builder().url(buildUrl(tv.ipAddress, existingToken)).build()
        val settled = AtomicBoolean(false)

        val listener = object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                val event = TizenProtocol.parseEvent(text) ?: return
                when {
                    // The TV explicitly refused the device.
                    event.event == EVENT_UNAUTHORIZED -> {
                        webSocket.close(NORMAL_CLOSURE, "unauthorized")
                        failOnce(
                            settled,
                            continuation,
                            PairingException(
                                PairingFailureReason.UNAUTHORIZED,
                                "TV denied authorization for this device",
                            ),
                        )
                    }
                    // Authorized: a fresh token, or a renewal that reuses ours.
                    event.token != null -> {
                        webSocket.close(NORMAL_CLOSURE, "paired")
                        resumeOnce(settled, continuation, event.token)
                    }
                    event.event == EVENT_CONNECT && existingToken != null -> {
                        webSocket.close(NORMAL_CLOSURE, "renewed")
                        resumeOnce(settled, continuation, existingToken)
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                failOnce(
                    settled,
                    continuation,
                    PairingException(
                        PairingFailureReason.CONNECTION_FAILED,
                        "Pairing WebSocket failed: ${t.message}",
                        t,
                    ),
                )
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                // Closed before any token/authorization decision arrived.
                failOnce(
                    settled,
                    continuation,
                    PairingException(
                        PairingFailureReason.NO_TOKEN,
                        "Pairing connection closed before a token was received",
                    ),
                )
            }
        }

        val webSocket = socketFactory.newWebSocket(request, listener)
        continuation.invokeOnCancellation { webSocket.cancel() }
    }

    /**
     * Builds the control-channel URL:
     * `wss://<ip>:8002/api/v2/channels/samsung.remote.control?name=<base64>`,
     * appending `&token=<token>` when a token is replayed for renewal.
     */
    private fun buildUrl(ip: String, token: String?): String {
        val name = Base64.getEncoder()
            .encodeToString(appName.toByteArray(StandardCharsets.UTF_8))
        val base = "$scheme://$ip:$port$CONTROL_PATH?name=$name"
        return if (token.isNullOrEmpty()) base else "$base&token=$token"
    }

    private companion object {
        const val DEFAULT_APP_NAME = "SamsungRemote"
        const val DEFAULT_PAIRING_PORT = 8002
        const val DEFAULT_SCHEME = "wss"

        const val CONTROL_PATH = "/api/v2/channels/samsung.remote.control"

        const val EVENT_CONNECT = "ms.channel.connect"
        const val EVENT_UNAUTHORIZED = "ms.channel.unauthorized"

        const val NORMAL_CLOSURE = 1000

        fun resumeOnce(
            settled: AtomicBoolean,
            continuation: kotlin.coroutines.Continuation<String>,
            token: String,
        ) {
            if (settled.compareAndSet(false, true)) continuation.resume(token)
        }

        fun failOnce(
            settled: AtomicBoolean,
            continuation: kotlin.coroutines.Continuation<String>,
            error: PairingException,
        ) {
            if (settled.compareAndSet(false, true)) continuation.resumeWithException(error)
        }
    }
}

/** Maps a discovery-layer [DiscoveredTv] onto the persisted [KnownTv] record. */
private fun DiscoveredTv.toKnownTv(): KnownTv = KnownTv(
    id = id,
    name = name,
    ipAddress = ipAddress,
)
