package com.factory.samsungremote.ui.pairing

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.factory.samsungremote.R
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.pairing.PairingFailureReason
import com.factory.samsungremote.viewmodel.PairingStatus
import com.factory.samsungremote.viewmodel.PairingUiState
import com.factory.samsungremote.viewmodel.PairingViewModel

/** Stable test tags for the pairing UI, shared with Compose UI tests. */
object PairingTestTags {
    const val INSTRUCTION = "pairing_instruction"
    const val PROGRESS = "pairing_progress"
    const val ERROR = "pairing_error"
    const val RETRY = "pairing_retry"
}

/**
 * Pairing entry point: binds the [PairingViewModel] to the stateless
 * [PairingScreen] and kicks off the handshake for [tv].
 *
 * Kept thin and Hilt-aware so it stays out of the UI test path — tests drive
 * [PairingScreen] directly with a hand-built [PairingUiState].
 *
 * @param tv        The TV chosen on the discovery screen to pair with.
 * @param onPaired  Invoked with the authorization token once pairing succeeds;
 *                  the host navigates on to the control screen.
 */
@Composable
fun PairingRoute(
    tv: DiscoveredTv,
    onPaired: (String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: PairingViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()

    // Start (and restart, after process recreation) the handshake for this TV.
    LaunchedEffect(tv.id) { viewModel.pair(tv) }

    PairingScreen(
        state = uiState,
        onPaired = onPaired,
        onRetry = { viewModel.pair(tv) },
        modifier = modifier,
    )
}

/**
 * Stateless pairing screen: renders the [state] and reports intent through
 * callbacks. Holding no state of its own keeps it trivially previewable and
 * testable.
 *
 * While the handshake is in flight it shows the "accept on your TV" instruction
 * with a spinner; on success it fires [onPaired] (navigation, done once via a
 * keyed [LaunchedEffect] so it survives recomposition); on failure it shows a
 * reason-specific message and a retry affordance wired to [onRetry].
 *
 * @param onPaired Called once with the token when [state] reaches success.
 * @param onRetry  Called when the user asks to pair again after a failure.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PairingScreen(
    state: PairingUiState,
    onPaired: (String) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    // Navigate exactly once when pairing succeeds, even across recompositions.
    LaunchedEffect(state.status, state.token) {
        if (state.status == PairingStatus.Success && state.token != null) {
            onPaired(state.token)
        }
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = { TopAppBar(title = { Text(stringResource(R.string.pairing_title)) }) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            when (state.status) {
                PairingStatus.Pairing -> WaitingContent()
                PairingStatus.Success -> WaitingContent()
                PairingStatus.Error -> ErrorContent(
                    reason = state.failureReason,
                    onRetry = onRetry,
                )
            }
        }
    }
}

/** "Accept on your TV" instruction plus an in-flight spinner. */
@Composable
private fun WaitingContent(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = stringResource(R.string.pairing_instruction),
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            modifier = Modifier.testTag(PairingTestTags.INSTRUCTION),
        )
        CircularProgressIndicator(
            modifier = Modifier
                .padding(top = 24.dp)
                .testTag(PairingTestTags.PROGRESS),
        )
        Text(
            text = stringResource(R.string.pairing_waiting),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 16.dp),
        )
    }
}

/** Reason-specific failure message plus a retry button. */
@Composable
private fun ErrorContent(
    reason: PairingFailureReason?,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = stringResource(reason.toMessageRes()),
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.error,
            textAlign = TextAlign.Center,
            modifier = Modifier.testTag(PairingTestTags.ERROR),
        )
        OutlinedButton(
            onClick = onRetry,
            modifier = Modifier
                .padding(top = 16.dp)
                .testTag(PairingTestTags.RETRY),
        ) {
            Text(stringResource(R.string.pairing_retry))
        }
    }
}

/** Maps a coarse [PairingFailureReason] to its user-facing message resource. */
private fun PairingFailureReason?.toMessageRes(): Int = when (this) {
    PairingFailureReason.UNAUTHORIZED -> R.string.pairing_error_unauthorized
    PairingFailureReason.CONNECTION_FAILED -> R.string.pairing_error_connection
    PairingFailureReason.NO_TOKEN -> R.string.pairing_error_no_token
    null -> R.string.pairing_error_generic
}
