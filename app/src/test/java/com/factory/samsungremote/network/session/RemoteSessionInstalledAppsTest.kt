package com.factory.samsungremote.network.session

import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.protocol.TizenProtocol
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
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Verifies the runtime app-discovery wiring on [RemoteSession] (ADR-0010): on the
 * control socket opening, the session asks the TV for its installed apps
 * (`ed.installedApp.get`) and publishes the parsed reply on [RemoteSession.installedApps].
 *
 * A fake [WebSocket] records the frames written and lets the test drive the
 * OkHttp listener callbacks (open + incoming message) directly, so the whole flow
 * runs deterministically on the test dispatcher with no real network.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RemoteSessionInstalledAppsTest {

    private val dispatcher = StandardTestDispatcher()

    private class RecordingWebSocket : WebSocket {
        val sent = mutableListOf<String>()
        override fun send(text: String): Boolean { sent.add(text); return true }
        override fun send(bytes: ByteString): Boolean = true
        override fun queueSize(): Long = 0L
        override fun close(code: Int, reason: String?): Boolean = true
        override fun cancel() = Unit
        override fun request(): Request = Request.Builder().url("https://localhost/").build()
    }

    private val socket = RecordingWebSocket()
    private lateinit var listener: WebSocketListener

    private fun newSession(scope: CoroutineScope): RemoteSession {
        val factory = WebSocket.Factory { _: Request, l: WebSocketListener ->
            listener = l
            socket
        }
        return RemoteSession(socketFactory = factory, scope = scope)
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

    @Test
    fun requestsInstalledAppsOnOpen_andPublishesParsedReply() = runTest(dispatcher) {
        val session = newSession(this)
        assertTrue(session.installedApps.value.isEmpty())

        session.connect(DiscoveredTv("uuid:1", "[TV] A", "192.168.0.10"), token = "T")
        advanceUntilIdle()
        listener.onOpen(socket, openResponse())
        advanceUntilIdle()

        assertTrue(
            "session should request the installed-app list when the socket opens",
            socket.sent.contains(TizenProtocol.requestInstalledApps()),
        )
        assertEquals(ConnectionState.Connected, session.state.value)

        listener.onMessage(socket, REPLY)
        advanceUntilIdle()

        val apps = session.installedApps.value
        assertEquals(2, apps.size)
        assertEquals("3201907018807", apps[0].appId)
        assertEquals("Netflix", apps[0].name)
        assertEquals("YouTube", apps[1].name)

        session.disconnect()
        advanceUntilIdle()
    }

    private companion object {
        const val REPLY =
            """{"event":"ed.installedApp.get","data":{"data":[""" +
                """{"appId":"3201907018807","app_type":2,"name":"Netflix"},""" +
                """{"appId":"111299001912","app_type":2,"name":"YouTube"}]}}"""
    }
}
