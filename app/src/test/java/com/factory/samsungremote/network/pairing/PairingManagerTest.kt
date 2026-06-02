package com.factory.samsungremote.network.pairing

import com.factory.samsungremote.data.crypto.TokenCipher
import com.factory.samsungremote.data.db.KnownTv
import com.factory.samsungremote.data.db.KnownTvDao
import com.factory.samsungremote.data.registry.TvRegistry
import com.factory.samsungremote.network.discovery.DiscoveredTv
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.nio.charset.StandardCharsets
import java.util.Base64

/**
 * Unit tests for [PairingManager].
 *
 * The TV side is simulated with a fake [WebSocket.Factory] (the injection seam
 * the production code exposes precisely so a `MockWebServer`/fake can stand in
 * for a real TV — see the class KDoc). The fake drives the [WebSocketListener]
 * with scripted Tizen protocol messages and records the handshake [Request], so
 * we can assert both the URL the manager builds and how it reacts to each event.
 *
 * Acceptance criteria covered:
 *  - a handshake that yields `data.token` is extracted AND persisted via
 *    [TvRegistry] (stored encrypted, recoverable decrypted);
 *  - an authorization failure surfaces as a treatable [PairingException]
 *    carrying [PairingFailureReason.UNAUTHORIZED] and persists nothing.
 *
 * Edge cases: token renewal (existing token replayed), a connection that closes
 * before any token (NO_TOKEN), and a transport failure (CONNECTION_FAILED).
 */
class PairingManagerTest {

    private val tv = DiscoveredTv(
        id = "uuid-1",
        name = "Living Room TV",
        ipAddress = "192.168.0.10",
    )

    // --- Happy path: token extracted and persisted via TvRegistry ----------- #
    @Test
    fun pair_withToken_extractsPersistsAndReturnsIt() = runTest {
        val dao = FakeKnownTvDao()
        val registry = TvRegistry(dao, FakeTokenCipher())
        val factory = FakeWebSocketFactory { ws, listener ->
            listener.onMessage(
                ws,
                """{"event":"ms.channel.connect","data":{"clients":[],"token":"TOK-123"}}""",
            )
        }
        val manager = PairingManager(registry, factory)

        val token = manager.pair(tv)

        // 1. Extracted and returned.
        assertEquals("TOK-123", token)
        // 2. Persisted via the registry (round-trips through decryption).
        assertEquals("TOK-123", registry.getToken("uuid-1"))
        // 3. Stored ENCRYPTED on the row, never in clear text.
        assertEquals("enc:TOK-123", dao.getById("uuid-1")?.tokenEncrypted)
        assertEquals("Living Room TV", dao.getById("uuid-1")?.name)

        // 4. Handshake URL: wss control endpoint with the Base64 name, no token.
        val url = factory.lastRequest!!.url
        val expectedName = Base64.getEncoder()
            .encodeToString("SamsungRemote".toByteArray(StandardCharsets.UTF_8))
        assertEquals(expectedName, url.queryParameter("name"))
        assertNull(url.queryParameter("token"))
        assertEquals("192.168.0.10", url.host)
        assertEquals(8002, url.port)
        assertEquals("/api/v2/channels/samsung.remote.control", url.encodedPath)
        // OkHttp normalises the wss scheme to https on the request URL.
        assertEquals("https", url.scheme)
    }

    // --- Authorization failure propagates a treatable error ----------------- #
    @Test
    fun pair_unauthorized_throwsTreatableExceptionAndPersistsNothing() = runTest {
        val dao = FakeKnownTvDao()
        val registry = TvRegistry(dao, FakeTokenCipher())
        val factory = FakeWebSocketFactory { ws, listener ->
            listener.onMessage(ws, """{"event":"ms.channel.unauthorized"}""")
        }
        val manager = PairingManager(registry, factory)

        val error = runCatching { manager.pair(tv) }.exceptionOrNull()

        assertTrue("expected a PairingException, got $error", error is PairingException)
        assertEquals(
            PairingFailureReason.UNAUTHORIZED,
            (error as PairingException).reason,
        )
        // No token leaked into storage on denial.
        assertNull(registry.getToken("uuid-1"))
        assertTrue(dao.getAll().isEmpty())
    }

    // --- Renewal: existing token replayed and re-persisted ------------------ #
    @Test
    fun pair_withStoredToken_replaysItForRenewal() = runTest {
        val dao = FakeKnownTvDao()
        val registry = TvRegistry(dao, FakeTokenCipher())
        // Already paired previously: a token is on file.
        registry.saveTv(
            KnownTv(id = "uuid-1", name = "Living Room TV", ipAddress = "192.168.0.10"),
            token = "OLD-TOK",
        )
        // TV re-confirms the connection without issuing a fresh token.
        val factory = FakeWebSocketFactory { ws, listener ->
            listener.onMessage(ws, """{"event":"ms.channel.connect","data":{"clients":[]}}""")
        }
        val manager = PairingManager(registry, factory)

        val token = manager.pair(tv)

        assertEquals("OLD-TOK", token)
        // The stored token was replayed in the handshake URL for renewal.
        assertEquals("OLD-TOK", factory.lastRequest!!.url.queryParameter("token"))
        // And it remains persisted afterwards.
        assertEquals("OLD-TOK", registry.getToken("uuid-1"))
    }

    // --- Edge: closed before any token -> NO_TOKEN -------------------------- #
    @Test
    fun pair_closedBeforeToken_failsWithNoToken() = runTest {
        val registry = TvRegistry(FakeKnownTvDao(), FakeTokenCipher())
        val factory = FakeWebSocketFactory { ws, listener ->
            listener.onClosed(ws, 1000, "bye")
        }
        val manager = PairingManager(registry, factory)

        val error = runCatching { manager.pair(tv) }.exceptionOrNull()

        assertTrue(error is PairingException)
        assertEquals(PairingFailureReason.NO_TOKEN, (error as PairingException).reason)
    }

    // --- Edge: transport failure -> CONNECTION_FAILED (cause preserved) ----- #
    @Test
    fun pair_transportFailure_failsWithConnectionFailed() = runTest {
        val registry = TvRegistry(FakeKnownTvDao(), FakeTokenCipher())
        val boom = IOException("socket exploded")
        val factory = FakeWebSocketFactory { ws, listener ->
            listener.onFailure(ws, boom, null)
        }
        val manager = PairingManager(registry, factory)

        val error = runCatching { manager.pair(tv) }.exceptionOrNull()

        assertTrue(error is PairingException)
        assertEquals(PairingFailureReason.CONNECTION_FAILED, (error as PairingException).reason)
        assertSame(boom, error.cause)
    }

    // --------------------------------------------------------------------- #
    // Test doubles
    // --------------------------------------------------------------------- #

    /** Reversible, non-secret stand-in for the Keystore-backed cipher. */
    private class FakeTokenCipher : TokenCipher {
        override fun encrypt(plaintext: String): String = "enc:$plaintext"
        override fun decrypt(ciphertext: String): String = ciphertext.removePrefix("enc:")
    }

    /** In-memory DAO so the registry can persist without Room/Android. */
    private class FakeKnownTvDao : KnownTvDao {
        private val rows = LinkedHashMap<String, KnownTv>()
        override suspend fun upsert(tv: KnownTv) {
            rows[tv.id] = tv
        }

        override suspend fun getById(id: String): KnownTv? = rows[id]
        override suspend fun getAll(): List<KnownTv> = rows.values.toList()
        override fun observeAll(): Flow<List<KnownTv>> = flowOf(rows.values.toList())
        override suspend fun delete(id: String) {
            rows.remove(id)
        }
    }

    /**
     * Fake [WebSocket.Factory] that records the handshake request and runs a
     * [script] to drive the listener (deliver messages, close, or fail), exactly
     * as a real TV / `MockWebServer` would over the wire.
     */
    private class FakeWebSocketFactory(
        private val script: (FakeWebSocket, WebSocketListener) -> Unit,
    ) : WebSocket.Factory {
        var lastRequest: Request? = null

        override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket {
            lastRequest = request
            val ws = FakeWebSocket(request)
            script(ws, listener)
            return ws
        }
    }

    /** Minimal [WebSocket] that records sends and close/cancel calls. */
    private class FakeWebSocket(private val request: Request) : WebSocket {
        override fun request(): Request = request
        override fun queueSize(): Long = 0
        override fun send(text: String): Boolean = true
        override fun send(bytes: ByteString): Boolean = true
        override fun close(code: Int, reason: String?): Boolean = true
        override fun cancel() = Unit
    }
}
