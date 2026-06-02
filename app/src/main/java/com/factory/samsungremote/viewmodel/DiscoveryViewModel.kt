package com.factory.samsungremote.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.discovery.DiscoveryService
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * UI state for the discovery screen (architecture §3 — discovery ViewModel).
 *
 * A single immutable snapshot the screen renders directly: the TVs confirmed so
 * far, whether a scan is still in flight, and a terminal error message if
 * discovery failed. The three are intentionally orthogonal — a scan can keep
 * running while results trickle in ([isScanning] `true` with a growing [tvs]),
 * and a non-null [error] means the scan stopped without recovering.
 *
 * @property tvs        TVs confirmed so far, de-duplicated by [DiscoveredTv.id],
 *                      in the order they were discovered.
 * @property isScanning `true` while the underlying discovery flow is being
 *                      collected.
 * @property error      Human-readable message when discovery failed, else `null`.
 */
data class DiscoveryUiState(
    val tvs: List<DiscoveredTv> = emptyList(),
    val isScanning: Boolean = false,
    val error: String? = null,
)

/**
 * Drives the "choose a TV" screen: collects the cold [DiscoveryService.discover]
 * flow and projects each confirmed [DiscoveredTv] into an observable
 * [DiscoveryUiState].
 *
 * The screen observes [uiState] as the single source of truth (ADR-0003 — the
 * UI never reaches a dead end): results stream in as they are confirmed, a
 * failure surfaces as [DiscoveryUiState.error], and [startScan] restarts a fresh
 * scan (used by the retry affordance). Collection runs in [viewModelScope], so
 * it is torn down with the ViewModel; an in-progress scan is cancelled before a
 * new one starts so the two never interleave.
 *
 * Selecting a TV (pairing/connecting) is the hosting layer's job — this
 * ViewModel only produces the list to choose from.
 *
 * @param discoveryService The LAN discovery pipeline; injected so tests can
 *                         substitute a fake that emits scripted TVs.
 */
@HiltViewModel
class DiscoveryViewModel @Inject constructor(
    private val discoveryService: DiscoveryService,
) : ViewModel() {

    private val _uiState = MutableStateFlow(DiscoveryUiState())
    val uiState: StateFlow<DiscoveryUiState> = _uiState.asStateFlow()

    private var scanJob: Job? = null

    init {
        startScan()
    }

    /**
     * (Re)starts discovery from a clean slate.
     *
     * Cancels any scan already running, resets the state to "scanning with no
     * results", then collects [DiscoveryService.discover], appending each newly
     * confirmed TV. The discovery flow is continuous (mDNS keeps probing), so on
     * the happy path collection stays active until the ViewModel is cleared or
     * [startScan] is called again; if the flow completes or fails, [isScanning]
     * is cleared and any error is surfaced.
     */
    fun startScan() {
        scanJob?.cancel()
        _uiState.value = DiscoveryUiState(isScanning = true)
        scanJob = viewModelScope.launch {
            try {
                discoveryService.discover().collect { tv ->
                    _uiState.update { state ->
                        if (state.tvs.any { it.id == tv.id }) {
                            state
                        } else {
                            state.copy(tvs = state.tvs + tv)
                        }
                    }
                }
                // Flow completed without error (e.g. a bounded fake source).
                _uiState.update { it.copy(isScanning = false) }
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        isScanning = false,
                        error = error.message ?: "Discovery failed",
                    )
                }
            }
        }
    }

    /** Stops the current scan, leaving the already-discovered TVs in place. */
    fun stopScan() {
        scanJob?.cancel()
        scanJob = null
        _uiState.update { it.copy(isScanning = false) }
    }
}
