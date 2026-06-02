package com.factory.samsungremote.data.repository

import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.network.protocol.TizenProtocol
import com.factory.samsungremote.network.session.CommandTransport
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for [CommandRepository].
 *
 * The transport ([com.factory.samsungremote.network.session.RemoteSession] in
 * production) is replaced by a [RecordingTransport] fake — the exact
 * [CommandTransport] seam the repository depends on — so we can assert the
 * protocol JSON each domain action maps to without opening a socket.
 *
 * Acceptance criteria covered: with a mocked RemoteSession (transport),
 * `sendKey` / `launchApp` / `sendText` each invoke the transport exactly once
 * with the correct JSON message for their case. Frames are asserted by parsing
 * the JSON and checking the semantic fields (method + params), so the test does
 * not depend on `org.json`'s key ordering; each frame is also anchored to
 * [TizenProtocol] to prove the mapping goes through the protocol layer.
 */
class CommandRepositoryTest {

    /** Fake transport that records every frame and returns a scripted result. */
    private class RecordingTransport(
        private val result: Boolean = true,
    ) : CommandTransport {
        val frames = mutableListOf<String>()
        var callCount = 0
            private set

        override fun send(frame: String): Boolean {
            callCount++
            frames.add(frame)
            return result
        }

        /** The single frame sent; fails if not exactly one send happened. */
        fun onlyFrame(): String {
            assertEquals("expected exactly one transport.send() call", 1, callCount)
            return frames.single()
        }
    }

    private val volUp = RemoteKey(
        code = "KEY_VOLUP",
        category = KeyCategory.VOLUME,
        label = "Volume Up",
    )

    // --- sendKey ------------------------------------------------------------ #
    @Test
    fun sendKey_sendsSendRemoteKeyFrameForKeyCode() {
        val transport = RecordingTransport()
        val repository = CommandRepository(transport)

        val accepted = repository.sendKey(volUp)

        val frame = transport.onlyFrame()
        val params = JSONObject(frame).also {
            assertEquals("ms.remote.control", it.getString("method"))
        }.getJSONObject("params")
        assertEquals("Click", params.getString("Cmd"))
        assertEquals("KEY_VOLUP", params.getString("DataOfCmd"))
        assertEquals("false", params.getString("Option"))
        assertEquals("SendRemoteKey", params.getString("TypeOfRemote"))

        // Anchor: the repository maps through the protocol layer using key.code.
        assertEquals(TizenProtocol.sendKey(volUp.code), frame)
        assertTrue("returns the transport result", accepted)
    }

    // --- launchApp ---------------------------------------------------------- #
    @Test
    fun launchApp_sendsAppsLaunchFrameForAppId() {
        val transport = RecordingTransport()
        val repository = CommandRepository(transport)

        val accepted = repository.launchApp("11101200001")

        val frame = transport.onlyFrame()
        val params = JSONObject(frame).also {
            assertEquals("ms.channel.emit", it.getString("method"))
        }.getJSONObject("params")
        assertEquals("ed.apps.launch", params.getString("event"))
        assertEquals("host", params.getString("to"))
        val data = params.getJSONObject("data")
        assertEquals("DEEP_LINK", data.getString("action_type"))
        assertEquals("11101200001", data.getString("appId"))

        assertEquals(TizenProtocol.launchApp("11101200001"), frame)
        assertTrue(accepted)
    }

    // --- sendText ----------------------------------------------------------- #
    @Test
    fun sendText_sendsBase64EncodedSendInputStringFrame() {
        val transport = RecordingTransport()
        val repository = CommandRepository(transport)

        // "hi" -> Base64 "aGk="
        val accepted = repository.sendText("hi")

        val frame = transport.onlyFrame()
        val params = JSONObject(frame).also {
            assertEquals("ms.remote.control", it.getString("method"))
        }.getJSONObject("params")
        assertEquals("aGk=", params.getString("Cmd"))
        assertEquals("base64", params.getString("DataOfCmd"))
        assertEquals("SendInputString", params.getString("TypeOfRemote"))

        assertEquals(TizenProtocol.sendText("hi"), frame)
        assertTrue(accepted)
    }

    // --- Edge case: transport reports no open connection -------------------- #
    @Test
    fun commands_propagateTransportFalseWhenNotConnected() {
        val transport = RecordingTransport(result = false)
        val repository = CommandRepository(transport)

        assertFalse(repository.sendKey(volUp))
        assertFalse(repository.sendText("hi"))
        assertFalse(repository.launchApp("11101200001"))

        // Still attempted the write for each action, in order.
        assertEquals(3, transport.frames.size)
        assertEquals(TizenProtocol.sendKey(volUp.code), transport.frames[0])
        assertEquals(TizenProtocol.sendText("hi"), transport.frames[1])
        assertEquals(TizenProtocol.launchApp("11101200001"), transport.frames[2])
    }
}
