package com.factory.samsungremote.network.session

import com.factory.samsungremote.network.discovery.DiscoveredTv
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * Regression coverage for the "a TV pede permissão toda vez" bug.
 *
 * Two independent causes are pinned here, both on the *session* socket (the
 * pairing handshake was already covered by `PairingManagerTest`):
 *
 *  1. **Token rotation was dropped.** Tizen re-emits `data.token` on
 *     `ms.channel.connect` and may rotate it. Only [PairingManager] used to
 *     persist tokens, so a rotated one was lost: the next launch replayed a value
 *     the TV had invalidated and the set showed its authorization prompt again.
 *     The session must now persist every token it is issued and replay the
 *     freshest one on reconnection.
 *  2. **`ms.channel.unauthorized` fed the reconnect loop.** With an unbounded
 *     retry budget and a 5 s backoff cap, a refused device reconnected forever —
 *     making the TV pop its prompt on every attempt. It must be terminal, and the
 *     dead token must be dropped so the next run re-pairs cleanly.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RemoteSessionTokenRenewalTest {

    private val dispatcher = StandardTestDispatcher()

    private val tv = DiscoveredTv(id = "uuid:1", name = "[TV] Sala", ipAddress = "192.168.0.10")

    /** Records what the session asks to persist/forget. */
    private class RecordingTokenStore : TokenStore {
        val saved = mutableListOf<Pair<String, String>>()
        val cleared = mutableListOf<String>()

        override suspend fun save(tv: DiscoveredTv, token: String) {
            saved.add(tv.id to token)
        }

        override suspend fun clear(tvId: String) {
            cleared.add(tvId)
        }
    }

    private class NoopWebSocket : WebSocket {
        override fun send(text: String): Boolean = true
        override fun send(bytes: ByteString): Boolean = true
        override fun queueSize(): Long = 0L
        override fun close(code: Int, reason: String?): Boolean = true
        override fun cancel() = Unit
        override fun request(): Request = Request.Builder().url("https://localhost/").build()
    }

    private val socket = NoopWebSocket()
    private val requests = mutableListOf<Request>()
    private lateinit var listener: WebSocketListener

    private fun newSession(scope: CoroutineScope, store: TokenStore): RemoteSession {
        val factory = WebSocket.Factory { request: Request, l: WebSocketListener ->
            requests.add(request)
            listener = l
            socket
        }
        return RemoteSession(socketFactory = factory, scope = scope, tokenStore = store)
    }

    private fun openResponse(): Response = Response.Builder()
        .request(Request.Builder().url("https://localhost/").build())
        .protocol(Protocol.HTTP_1_1)
        .code(101)
        .message("Switching Protocols")
        .build()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    // --- 1. A rotated token is persisted AND replayed on reconnection ------- #
    @Test
    fun tokenIssuedMidSession_isPersistedAndReplayedOnReconnect() = runTest(dispatcher) {
        val store = RecordingTokenStore()
        val session = newSession(this, store)

        session.connect(tv, token = "OLD-TOK")
        advanceUntilIdle()
        listener.onOpen(socket, openResponse())
        advanceUntilIdle()

        // First socket replayed the token we had on file.
        assertEquals("OLD-TOK", requests[0].url.queryParameter("token"))

        // The TV confirms the channel and hands over a *different* token.
        listener.onMessage(
            socket,
            """{"event":"ms.channel.connect","data":{"clients":[],"token":"NEW-TOK"}}""",
        )
        advanceUntilIdle()

        assertEquals(
            "the token the TV issued must be persisted",
            listOf("uuid:1" to "NEW-TOK"),
            store.saved,
        )

        // The link drops; the automatic reconnection must carry the fresh token.
        listener.onFailure(socket, IOException("link dropped"), null)
        advanceUntilIdle()

        assertTrue("session should have reconnected", requests.size >= 2)
        assertEquals("NEW-TOK", requests.last().url.queryParameter("token"))

        session.disconnect()
        advanceUntilIdle()
    }

    // --- 2. Denial is terminal: no reconnect storm, dead token dropped ------ #
    @Test
    fun unauthorized_stopsReconnecting_andClearsStoredToken() = runTest(dispatcher) {
        val store = RecordingTokenStore()
        val session = newSession(this, store)

        session.connect(tv, token = "DEAD-TOK")
        advanceUntilIdle()
        listener.onOpen(socket, openResponse())
        advanceUntilIdle()

        listener.onMessage(socket, """{"event":"ms.channel.unauthorized"}""")
        advanceUntilIdle()

        assertTrue(
            "denial must be terminal, not another reconnection attempt",
            session.state.value is ConnectionState.Error,
        )
        assertEquals(
            "the rejected token must be dropped so the next run re-pairs",
            listOf("uuid:1"),
            store.cleared,
        )
        assertEquals("no reconnection may be attempted after a denial", 1, requests.size)
        assertNull("nothing should be persisted on a denial", store.saved.firstOrNull())

        session.disconnect()
        advanceUntilIdle()
    }
}
