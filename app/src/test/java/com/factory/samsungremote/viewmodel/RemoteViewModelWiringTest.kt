package com.factory.samsungremote.viewmodel

import com.factory.samsungremote.data.favorites.FavoriteAppsStore
import com.factory.samsungremote.data.favorites.KeyValueStore
import com.factory.samsungremote.data.registry.RemoteKeyCatalog
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.protocol.TizenProtocol
import com.factory.samsungremote.network.session.ConnectionState
import com.factory.samsungremote.network.session.RemoteSession
import com.factory.samsungremote.network.wol.WakeOnLan
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.Dispatchers
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Wiring test for the discovery → pairing → remote flow that `MainActivity`'s
 * navigation now connects.
 *
 * The navigation host carries the selected [DiscoveredTv] and pairing token into
 * [com.factory.samsungremote.ui.remote.RemoteRoute], which on entry replays them
 * to [RemoteViewModel.connect] and routes every control press through
 * [RemoteViewModel.onIntent]. This test exercises that exact seam end to end at
 * the JVM level: it builds the **real** [RemoteSession] (the production
 * [com.factory.samsungremote.network.session.CommandTransport]) over a fake
 * [WebSocket] that records the frames written to it, so we prove that after
 * selecting a TV at least one command (VOL+ / HOME — the acceptance examples)
 * actually reaches the session's open socket.
 *
 * Acceptance criteria covered (the unit-testable half of the navigation task):
 *  - Selecting a TV connects the session to *that* TV (its IP/token are replayed
 *    through [RemoteViewModel.connect], driving [RemoteSession] off
 *    [ConnectionState.Disconnected]).
 *  - VOL+ and HOME presses, routed via the ViewModel the remote screen drives,
 *    are serialized through [TizenProtocol] and handed to the live socket.
 *
 * The screen ordering itself (discovery first, then pairing, then remote) is a
 * Compose concern verified by the instrumented UI tests under `androidTest` and
 * enforced at compile time by `assembleDebug` (the host wires
 * `DiscoveryRoute → PairingRoute → RemoteRoute` with matching types).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RemoteViewModelWiringTest {

    private val dispatcher = StandardTestDispatcher()

    /**
     * Fake control socket: records every text frame the session writes and
     * reports success, standing in for a connected TV without a real network.
     */
    private class RecordingWebSocket : WebSocket {
        val sent = mutableListOf<String>()

        override fun send(text: String): Boolean {
            sent.add(text)
            return true
        }

        override fun send(bytes: ByteString): Boolean = true
        override fun queueSize(): Long = 0L
        override fun close(code: Int, reason: String?): Boolean = true
        override fun cancel() = Unit
        override fun request(): Request = Request.Builder().url("https://localhost/").build()
    }

    private val socket = RecordingWebSocket()

    /**
     * Builds a [RemoteViewModel] over the real [RemoteSession] + [CommandRepository],
     * with the socket factory pinned to [socket]. The session runs on the test
     * scope so virtual time drives its connection loop deterministically.
     */
    private fun buildViewModel(scope: kotlinx.coroutines.CoroutineScope): RemoteViewModel {
        val factory = WebSocket.Factory { _: Request, _: WebSocketListener -> socket }
        val session = RemoteSession(socketFactory = factory, scope = scope)
        val repository = CommandRepository(session)
        val favorites = FavoriteAppsStore(InMemoryKeyValueStore())
        return RemoteViewModel(repository, session, WakeOnLan(), favorites)
    }

    /** Map-backed [KeyValueStore] so the favorites store needs no Android prefs. */
    private class InMemoryKeyValueStore : KeyValueStore {
        private val map = mutableMapOf<String, String>()
        override fun getString(key: String): String? = map[key]
        override fun putString(key: String, value: String) { map[key] = value }
    }

    /**
     * Cancels the session's connection loop so the test scope has no lingering
     * coroutine (the loop otherwise parks forever waiting on socket signals,
     * which `runTest` would flag as an uncompleted coroutine).
     */
    private fun TestScope.teardownSession(vm: RemoteViewModel) {
        vm.disconnect()
        advanceUntilIdle()
    }

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun connect_opensSessionForSelectedTv() = runTest(dispatcher) {
        val vm = buildViewModel(this)
        assertEquals(ConnectionState.Disconnected, vm.connectionState.value)

        val tv = DiscoveredTv("uuid:living", "[TV] Living Room", "192.168.0.10")
        vm.connect(tv, token = "TOKEN-123")
        advanceUntilIdle()

        // Selecting a TV drove the session off Disconnected: the connection loop
        // for that TV is now live (Connecting/Connected), proving the navigation's
        // tv/token reached the session rather than staying idle.
        assertTrue(
            "expected the session to leave Disconnected after connect(), was " +
                vm.connectionState.value,
            vm.connectionState.value != ConnectionState.Disconnected,
        )

        teardownSession(vm)
    }

    @Test
    fun volumeUpCommand_reachesOpenSession() = runTest(dispatcher) {
        val vm = buildViewModel(this)
        vm.connect(DiscoveredTv("uuid:1", "[TV] A", "192.168.0.10"), token = "T")
        advanceUntilIdle()

        val volUp = requireNotNull(RemoteKeyCatalog.findByCode("KEY_VOLUP"))
        val reached = vm.onIntent(RemoteIntent.PressKey(volUp))

        assertTrue("VOL+ should report reaching the open connection", reached)
        assertEquals(listOf(TizenProtocol.sendKey("KEY_VOLUP")), socket.sent)

        teardownSession(vm)
    }

    @Test
    fun homeCommand_reachesOpenSession() = runTest(dispatcher) {
        val vm = buildViewModel(this)
        vm.connect(DiscoveredTv("uuid:1", "[TV] A", "192.168.0.10"), token = "T")
        advanceUntilIdle()

        val home = requireNotNull(RemoteKeyCatalog.findByCode("KEY_HOME"))
        val reached = vm.pressKey(home)

        assertTrue("HOME should report reaching the open connection", reached)
        assertEquals(listOf(TizenProtocol.sendKey("KEY_HOME")), socket.sent)

        teardownSession(vm)
    }

    @Test
    fun commandsBeforeConnect_doNotReachAnySocket() = runTest(dispatcher) {
        // Edge case: no TV selected yet (session still Disconnected) → the press is
        // reported as not reaching a connection and nothing is written to a socket.
        val vm = buildViewModel(this)

        val volUp = requireNotNull(RemoteKeyCatalog.findByCode("KEY_VOLUP"))
        val reached = vm.onIntent(RemoteIntent.PressKey(volUp))

        assertEquals(false, reached)
        assertTrue("no frame should be sent before a TV is connected", socket.sent.isEmpty())
    }
}
