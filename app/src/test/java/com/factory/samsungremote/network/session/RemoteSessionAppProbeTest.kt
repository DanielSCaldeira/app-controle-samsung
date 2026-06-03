package com.factory.samsungremote.network.session

import com.factory.samsungremote.network.discovery.DiscoveredTv
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.ByteString
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Verifies the REST app-detection probe on [RemoteSession] (ADR-0011): a 2xx from
 * `GET /api/v2/applications/{id}` means the app is installed (404 means not), and
 * the TV model is read from the device-info endpoint for the not-found report.
 */
class RemoteSessionAppProbeTest {

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
        session.connect(DiscoveredTv("uuid:1", "[TV] A", server.hostName), token = "T")
    }

    @After
    fun tearDown() {
        scope.cancel()
        server.shutdown()
    }

    @Test
    fun isAppInstalled_trueOn2xx_andHitsStatusEndpoint() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"x","name":"Netflix"}"""))

        val installed = session.isAppInstalled("3201907018807")

        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/api/v2/applications/3201907018807", request.path)
        assertTrue(installed)
    }

    @Test
    fun isAppInstalled_falseOn404() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404))
        assertFalse(session.isAppInstalled("11101200001"))
    }

    @Test
    fun isAppInstalled_falseForBlankId_withoutRequest() = runBlocking {
        assertFalse(session.isAppInstalled(""))
        assertEquals("no request should be issued for a blank id", 0, server.requestCount)
    }

    @Test
    fun fetchModel_readsModelNameFromDeviceInfo() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"device":{"modelName":"QN70Q65DAGXZD"},"version":"2.0.25"}"""),
        )

        val model = session.fetchModel()

        val request = server.takeRequest()
        assertEquals("/api/v2/", request.path)
        assertEquals("QN70Q65DAGXZD", model)
    }

    @Test
    fun fetchModel_nullWhenDeviceInfoUnavailable() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404))
        assertNull(session.fetchModel())
    }
}
