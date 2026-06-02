package com.factory.samsungremote.network.session

import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.protocol.TizenCommand
import com.factory.samsungremote.network.protocol.TizenEvent
import com.factory.samsungremote.network.protocol.TizenProtocol
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.nio.charset.StandardCharsets
import java.util.Base64
import java.util.concurrent.atomic.AtomicReference
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Single source of truth for the live connection to a Samsung TV (ADR-0003,
 * architecture §3.1).
 *
 * The session keeps **exactly one** control WebSocket open at a time, sends
 * [RemoteKey]/protocol messages through it, surfaces incoming [TizenEvent]s, and
 * exposes its lifecycle as a [StateFlow] of [ConnectionState]
 * (Connecting/Connected/Reconnecting/Error). When the link drops it reconnects
 * automatically with exponential backoff, so the UI never gets stuck in an
 * invalid state.
 *
 * **One socket, ever.** All connection lifecycle changes are serialized through
 * a single management coroutine guarded by a [Mutex]; a new [connect] cancels and
 * joins the previous attempt before opening anything, and reconnection happens
 * sequentially inside one loop. No parallel sockets are opened.
 *
 * The OkHttp [WebSocket.Factory] is injected so tests can drive the session with
 * a `MockWebServer` (or a fake) standing in for a real TV — the same seam
 * [com.factory.samsungremote.network.pairing.PairingManager] uses.
 *
 * @param socketFactory          Factory for the control WebSocket. In production
 *                               an OkHttp client trusting the TV's self-signed
 *                               LAN certificate; in tests a `MockWebServer` client.
 * @param scope                  Long-lived scope the connection loop runs in
 *                               (application-scoped in production; the test scope
 *                               under unit tests so virtual time drives backoff).
 * @param appName                Controller name, Base64-encoded into the `name`
 *                               query parameter.
 * @param port                   Control WebSocket port; Samsung's secure default
 *                               is 8002.
 * @param scheme                 URL scheme; `wss` for the TLS control endpoint.
 * @param initialBackoffMillis   Delay before the first reconnection attempt.
 * @param maxBackoffMillis       Upper bound for the exponential backoff.
 * @param maxReconnectAttempts   Consecutive failed reconnections before giving up
 *                               with [ConnectionState.Error]. Reset to zero once a
 *                               connection succeeds.
 */
@Singleton
class RemoteSession @Inject constructor(
    private val socketFactory: WebSocket.Factory,
    private val scope: CoroutineScope,
    private val appName: String = DEFAULT_APP_NAME,
    private val port: Int = DEFAULT_CONTROL_PORT,
    private val scheme: String = DEFAULT_SCHEME,
    private val initialBackoffMillis: Long = DEFAULT_INITIAL_BACKOFF_MILLIS,
    private val maxBackoffMillis: Long = DEFAULT_MAX_BACKOFF_MILLIS,
    private val maxReconnectAttempts: Int = DEFAULT_MAX_RECONNECT_ATTEMPTS,
) {

    private val _state = MutableStateFlow<ConnectionState>(ConnectionState.Disconnected)

    /** Observable connection lifecycle; the UI's single source of truth. */
    val state: StateFlow<ConnectionState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<TizenEvent>(extraBufferCapacity = EVENT_BUFFER)

    /** Stream of protocol events received from the TV over the open socket. */
    val events: SharedFlow<TizenEvent> = _events.asSharedFlow()

    /** Serializes [connect]/[disconnect] so only one connection loop runs. */
    private val controlMutex = Mutex()

    /** The currently open socket, if any; used by [send] and for teardown. */
    private val currentSocket = AtomicReference<WebSocket?>(null)

    /** The running connection-maintenance coroutine, if any. */
    private var connectionJob: kotlinx.coroutines.Job? = null

    /**
     * Connects to [tv], replaying [token] (the pairing token) so an authorized
     * device is not re-prompted. Idempotent with respect to parallelism: any
     * in-flight connection to a previous target is cancelled first, guaranteeing a
     * single live socket.
     *
     * Returns immediately; observe [state] for progress.
     */
    fun connect(tv: DiscoveredTv, token: String?) {
        val target = Target(host = tv.ipAddress, token = token)
        scope.launch {
            controlMutex.withLock {
                connectionJob?.cancelAndJoin()
                currentSocket.getAndSet(null)?.cancel()
                connectionJob = scope.launch { maintainConnection(target) }
            }
        }
    }

    /**
     * Tears down the connection and stops reconnecting. Transitions [state] to
     * [ConnectionState.Disconnected]. Safe to call when already disconnected.
     */
    fun disconnect() {
        scope.launch {
            controlMutex.withLock {
                connectionJob?.cancelAndJoin()
                connectionJob = null
                currentSocket.getAndSet(null)?.cancel()
                _state.value = ConnectionState.Disconnected
            }
        }
    }

    /** Sends a remote key (single click). */
    fun sendKey(key: RemoteKey): Boolean = sendKey(key.code)

    /** Sends a remote key by protocol code (e.g. `KEY_VOLUP`). */
    fun sendKey(keyCode: String, command: TizenCommand = TizenCommand.CLICK): Boolean =
        send(TizenProtocol.sendKey(keyCode, command))

    /** Launches a Tizen app by id (e.g. Netflix `11101200001`). */
    fun launchApp(appId: String): Boolean = send(TizenProtocol.launchApp(appId))

    /** Types [text] into the focused field on the TV. */
    fun sendText(text: String): Boolean = send(TizenProtocol.sendText(text))

    /**
     * Writes [frame] to the open socket. Returns `false` when no socket is
     * currently connected (the caller can react to [state] instead of throwing).
     */
    private fun send(frame: String): Boolean = currentSocket.get()?.send(frame) ?: false

    /**
     * Runs the connection loop for [target]: open the socket, stay connected, and
     * on any drop reconnect with exponential backoff until either it recovers,
     * the retry budget is exhausted ([ConnectionState.Error]), or the coroutine is
     * cancelled by [disconnect]/[connect].
     */
    private suspend fun maintainConnection(target: Target) {
        var attempt = 0
        while (true) {
            _state.value = if (attempt == 0) ConnectionState.Connecting
            else ConnectionState.Reconnecting(attempt)

            // Suspends until the socket dies (close or failure). A local
            // disconnect()/connect() cancels this coroutine instead, so we never
            // reconnect after an intentional teardown.
            val outcome = connectOnce(target)

            // A live connection that later dropped resets the backoff budget.
            if (outcome.wasConnected) attempt = 0

            if (attempt >= maxReconnectAttempts) {
                _state.value = ConnectionState.Error(
                    message = "Could not reconnect to ${target.host} after " +
                        "$maxReconnectAttempts attempts",
                    cause = outcome.error,
                )
                return
            }

            attempt++
            _state.value = ConnectionState.Reconnecting(attempt)
            delay(backoffMillis(attempt))
        }
    }

    /**
     * Opens a single socket and suspends until it dies (server close or transport
     * failure) or the coroutine is cancelled. Forwards events while connected and
     * publishes [ConnectionState.Connected] on open.
     */
    private suspend fun connectOnce(target: Target): Outcome {
        val signals = Channel<Signal>(Channel.UNLIMITED)
        val request = Request.Builder().url(buildUrl(target)).build()
        val webSocket = socketFactory.newWebSocket(request, SignalListener(signals))
        currentSocket.set(webSocket)

        var connected = false
        try {
            for (signal in signals) {
                when (signal) {
                    Signal.Open -> {
                        connected = true
                        _state.value = ConnectionState.Connected
                    }

                    is Signal.Text ->
                        TizenProtocol.parseEvent(signal.text)?.let(_events::tryEmit)

                    is Signal.Closing ->
                        webSocket.close(NORMAL_CLOSURE, null)

                    is Signal.Closed ->
                        return Outcome(wasConnected = connected, error = null)

                    is Signal.Failure ->
                        return Outcome(wasConnected = connected, error = signal.error)
                }
            }
            return Outcome(wasConnected = connected, error = null)
        } finally {
            webSocket.cancel()
            currentSocket.compareAndSet(webSocket, null)
        }
    }

    /**
     * Builds the control-channel URL:
     * `wss://<host>:8002/api/v2/channels/samsung.remote.control?name=<base64>`,
     * appending `&token=<token>` when a token is replayed.
     */
    private fun buildUrl(target: Target): String {
        val name = Base64.getEncoder()
            .encodeToString(appName.toByteArray(StandardCharsets.UTF_8))
        val base = "$scheme://${target.host}:$port$CONTROL_PATH?name=$name"
        return if (target.token.isNullOrEmpty()) base else "$base&token=${target.token}"
    }

    /** Exponential backoff, capped at [maxBackoffMillis]. [attempt] is 1-based. */
    private fun backoffMillis(attempt: Int): Long {
        val shift = (attempt - 1).coerceIn(0, MAX_BACKOFF_SHIFT)
        val scaled = initialBackoffMillis shl shift
        return scaled.coerceAtMost(maxBackoffMillis)
    }

    /** Connection target: where to connect and which token to replay. */
    private data class Target(val host: String, val token: String?)

    /**
     * Result of a single socket lifetime.
     *
     * @property wasConnected Whether the socket ever reached the open state; used
     *                        to reset the backoff budget after a stable link drops.
     * @property error        Transport failure that ended the lifetime, if any.
     */
    private data class Outcome(
        val wasConnected: Boolean,
        val error: Throwable?,
    )

    /** Internal lifecycle signals bridged from the OkHttp listener thread. */
    private sealed interface Signal {
        data object Open : Signal
        data class Text(val text: String) : Signal
        data class Closing(val code: Int, val reason: String) : Signal
        data class Closed(val code: Int, val reason: String) : Signal
        data class Failure(val error: Throwable) : Signal
    }

    /**
     * Adapts OkHttp's callback-based [WebSocketListener] onto a [Channel] the
     * suspending connection loop consumes. [Channel.trySend] is non-blocking and
     * safe to call from OkHttp's I/O threads.
     */
    private class SignalListener(
        private val signals: Channel<Signal>,
    ) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            signals.trySend(Signal.Open)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            signals.trySend(Signal.Text(text))
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            signals.trySend(Signal.Closing(code, reason))
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            signals.trySend(Signal.Closed(code, reason))
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            signals.trySend(Signal.Failure(t))
        }
    }

    private companion object {
        const val DEFAULT_APP_NAME = "SamsungRemote"
        const val DEFAULT_CONTROL_PORT = 8002
        const val DEFAULT_SCHEME = "wss"

        const val DEFAULT_INITIAL_BACKOFF_MILLIS = 500L
        const val DEFAULT_MAX_BACKOFF_MILLIS = 5_000L
        const val DEFAULT_MAX_RECONNECT_ATTEMPTS = Int.MAX_VALUE

        /** Cap the bit-shift so the backoff computation never overflows. */
        const val MAX_BACKOFF_SHIFT = 16

        const val CONTROL_PATH = "/api/v2/channels/samsung.remote.control"
        const val NORMAL_CLOSURE = 1000

        const val EVENT_BUFFER = 64
    }
}
