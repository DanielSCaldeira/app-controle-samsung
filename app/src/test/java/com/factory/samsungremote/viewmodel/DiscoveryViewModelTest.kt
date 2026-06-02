package com.factory.samsungremote.viewmodel

import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.discovery.DiscoveryService
import com.factory.samsungremote.network.discovery.TvCandidateSource
import com.factory.samsungremote.network.discovery.TvCandidateValidator
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.asFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for [DiscoveryViewModel].
 *
 * The [DiscoveryService] is replaced by a [FakeDiscoveryService] that overrides
 * `discover()` to emit scripted [DiscoveredTv]s, so we assert the projection
 * into [DiscoveryUiState] without touching real sockets.
 *
 * Acceptance criterion covered: collecting from the fake service, the
 * `uiState` [kotlinx.coroutines.flow.StateFlow] exposes the discovered TV list
 * (de-duplicated by id), surfaces failures as [DiscoveryUiState.error], and
 * restarting a scan resets rather than accumulates.
 *
 * `viewModelScope` runs on `Dispatchers.Main`, so the test installs a
 * [StandardTestDispatcher] as Main and drives it with [advanceUntilIdle].
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DiscoveryViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    /** Fake service: overrides discover() to emit a scripted, cold flow. */
    private class FakeDiscoveryService(
        private val source: Flow<DiscoveredTv>,
    ) : DiscoveryService(
        TvCandidateSource { emptyFlow() },
        TvCandidateSource { emptyFlow() },
        TvCandidateValidator { null },
    ) {
        override fun discover(): Flow<DiscoveredTv> = source
    }

    private val tvs = listOf(
        DiscoveredTv("uuid:1", "[TV] Living Room", "192.168.0.10", "QN65Q80B"),
        DiscoveredTv("uuid:2", "[TV] Bedroom", "192.168.0.11", null),
        DiscoveredTv("uuid:1", "[TV] Living Room (dup)", "192.168.0.10", "QN65Q80B"),
    )

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun uiState_exposes_discovered_tv_list_dedupedById() = runTest(dispatcher) {
        val vm = DiscoveryViewModel(FakeDiscoveryService(tvs.asFlow()))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(listOf("uuid:1", "uuid:2"), state.tvs.map { it.id })
        assertEquals("[TV] Living Room", state.tvs[0].name)
        assertEquals("192.168.0.11", state.tvs[1].ipAddress)
        assertNull(state.error)
    }

    @Test
    fun failure_surfaces_as_error_and_stops_scanning() = runTest(dispatcher) {
        val vm = DiscoveryViewModel(FakeDiscoveryService(flow { throw RuntimeException("boom") }))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("boom", state.error)
        assertFalse(state.isScanning)
        assertEquals(emptyList<DiscoveredTv>(), state.tvs)
    }

    @Test
    fun startScan_resets_state_withoutAccumulating() = runTest(dispatcher) {
        val vm = DiscoveryViewModel(FakeDiscoveryService(tvs.asFlow()))
        advanceUntilIdle()

        vm.startScan()
        advanceUntilIdle()

        assertEquals(listOf("uuid:1", "uuid:2"), vm.uiState.value.tvs.map { it.id })
    }

    @Test
    fun stopScan_keepsResults_andClearsFlag() = runTest(dispatcher) {
        val vm = DiscoveryViewModel(FakeDiscoveryService(tvs.asFlow()))
        advanceUntilIdle()

        vm.stopScan()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.isScanning)
        assertEquals(2, state.tvs.size)
    }
}
