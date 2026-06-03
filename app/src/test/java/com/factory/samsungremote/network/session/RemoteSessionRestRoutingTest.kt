package com.factory.samsungremote.network.session

import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.discovery.DiscoveredTv
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.ByteString
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * Verifies that the production [RemoteSession] routes app launch and text input
 * through the **REST** control plane (`http://<ip>:8001/api/v2/`, ADR-0010) once
 * connected, rather than the `ed.apps.launch`/`SendInputString` WebSocket frames
 * that 2020+ Tizen firmware ignores.
 *
 * A [MockWebServer] stands in for the TV's REST plane; the control WebSocket is a
 * no-op fake (the REST path must not depend on it). Commands are driven through
 * the real [CommandRepository] — the exact production path the ViewModel uses —
 * so we assert the REST request the launch/text actually produced.
 */
class RemoteSessionRestRoutingTest {

    /** Inert control socket: the REST path under test must not touch it. */
    private class NoopWebSocket : WebSocket {
        override fun send(text: String): Boolean = true
        override fun send(bytes: ByteString): Boolean = true
        override fun queueSize(): Long = 0L
        override fun close(code: Int, reason: String?): Boolean = true
        override fun cancel() = Unit
        override fun request(): Request = Request.Builder().url("https://localhost/").build()
    }

    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var session: RemoteSession
    private lateinit var repository: CommandRepository

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val factory = WebSocket.Factory { _: Request, _: WebSocketListener -> NoopWebSocket() }
        session = RemoteSession(
            socketFactory = factory,
            scope = scope,
            restHttpClient = OkHttpClient(),
            restPort = server.port,
            restScheme = "http",
        )
        repository = CommandRepository(session)
    }

    @After
    fun tearDown() {
        scope.cancel()
        server.shutdown()
    }

    @Test
    fun launchApp_afterConnect_hitsRestApplicationsEndpoint() {
        server.enqueue(MockResponse().setResponseCode(200))
        session.connect(DiscoveredTv("uuid:1", "[TV] A", server.hostName), token = "TOK")

        val dispatched = repository.launchApp("11101200001")

        val request = server.takeRequest(2, TimeUnit.SECONDS)
        assertNotNull("launch should reach the REST server", request)
        assertEquals("POST", request!!.method)
        assertEquals("/api/v2/applications/11101200001", request.path)
        assertEquals("launch should report dispatched", true, dispatched)
    }

    @Test
    fun sendText_afterConnect_hitsRestImeEndpointWithToken() {
        server.enqueue(MockResponse().setResponseCode(200))
        session.connect(DiscoveredTv("uuid:1", "[TV] A", server.hostName), token = "TOK")

        // "hi" -> Base64 "aGk="; "=" is percent-encoded as %3D in the path segment.
        repository.sendText("hi")

        val request = server.takeRequest(2, TimeUnit.SECONDS)
        assertNotNull("text should reach the REST server", request)
        assertEquals("POST", request!!.method)
        assertEquals("/api/v2/remoteControl/imeInput/aGk%3D?token=TOK", request.path)
    }
}
