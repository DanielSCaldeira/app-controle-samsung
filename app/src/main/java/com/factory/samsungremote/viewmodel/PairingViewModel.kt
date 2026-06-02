package com.factory.samsungremote.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.pairing.PairingException
import com.factory.samsungremote.network.pairing.PairingFailureReason
import com.factory.samsungremote.network.pairing.PairingManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Where the pairing handshake currently stands, for the screen to render. */
enum class PairingStatus {
    /** Waiting on the user to accept the on-screen prompt on the TV. */
    Pairing,

    /** The TV returned a token; pairing succeeded. */
    Success,

    /** The handshake failed; [PairingUiState.failureReason] says why. */
    Error,
}

/**
 * UI state for the pairing screen (architecture §5 — pairing flow).
 *
 * A single immutable snapshot the screen renders directly. The flow has one
 * happy path (waiting → success) and one recoverable failure path (waiting →
 * error → retry), so the three [PairingStatus] values are mutually exclusive.
 *
 * @property status        Where the handshake currently stands.
 * @property token         The authorization token, present only on [PairingStatus.Success].
 * @property failureReason Why pairing failed, present only on [PairingStatus.Error];
 *                         `null` for an unclassified/unexpected error.
 */
data class PairingUiState(
    val status: PairingStatus = PairingStatus.Pairing,
    val token: String? = null,
    val failureReason: PairingFailureReason? = null,
)

/**
 * Drives the pairing screen: runs the [PairingManager] handshake for a chosen
 * [DiscoveredTv] and projects its outcome into an observable [PairingUiState].
 *
 * The screen observes [uiState] as the single source of truth (ADR-0003 — the UI
 * never reaches a dead end): while the handshake is in flight the state stays
 * [PairingStatus.Pairing] ("accept on the TV"), a returned token flips it to
 * [PairingStatus.Success] (the host then navigates onward), and any
 * [PairingException] surfaces as [PairingStatus.Error] with a treatable
 * [PairingFailureReason] so the screen can offer [retry].
 *
 * The handshake runs in [viewModelScope], so it is cancelled with the ViewModel;
 * a fresh attempt cancels any in-flight one first so the two never interleave.
 *
 * @param pairingManager Performs the Tizen handshake; injected so tests can
 *                       substitute a fake that returns a scripted token or throws.
 */
@HiltViewModel
class PairingViewModel @Inject constructor(
    private val pairingManager: PairingManager,
) : ViewModel() {

    private val _uiState = MutableStateFlow(PairingUiState())
    val uiState: StateFlow<PairingUiState> = _uiState.asStateFlow()

    private var pairJob: Job? = null

    /**
     * Starts (or restarts) pairing with [tv].
     *
     * Cancels any attempt already running, resets to [PairingStatus.Pairing],
     * then awaits [PairingManager.pair]. Success carries the token; a
     * [PairingException] is mapped to [PairingStatus.Error] keeping its
     * [PairingFailureReason]; any other failure becomes an unclassified error.
     */
    fun pair(tv: DiscoveredTv) {
        pairJob?.cancel()
        _uiState.value = PairingUiState(status = PairingStatus.Pairing)
        pairJob = viewModelScope.launch {
            try {
                val token = pairingManager.pair(tv)
                _uiState.value = PairingUiState(status = PairingStatus.Success, token = token)
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (error: PairingException) {
                _uiState.value = PairingUiState(
                    status = PairingStatus.Error,
                    failureReason = error.reason,
                )
            } catch (error: Exception) {
                _uiState.value = PairingUiState(status = PairingStatus.Error)
            }
        }
    }
}
