package com.factory.samsungremote.ui.discovery

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.hilt.navigation.compose.hiltViewModel
import com.factory.samsungremote.R
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.viewmodel.DiscoveryUiState
import com.factory.samsungremote.viewmodel.DiscoveryViewModel

/** Stable test tags for the discovery UI, shared with Compose UI tests. */
object DiscoveryTestTags {
    const val PROGRESS = "discovery_progress"
    const val EMPTY = "discovery_empty"
    const val ERROR = "discovery_error"
    const val TV_LIST = "discovery_tv_list"

    /** Manual IP fallback entry. */
    const val MANUAL_IP_FIELD = "discovery_manual_ip_field"
    const val MANUAL_IP_SUBMIT = "discovery_manual_ip_submit"
    const val MANUAL_IP_ERROR = "discovery_manual_ip_error"

    /** Per-item tag, qualified by the TV id so a specific row can be targeted. */
    fun tvItem(id: String): String = "discovery_tv_item_$id"
}

/**
 * Discovery entry point: binds the [DiscoveryViewModel] to the stateless
 * [DiscoveryScreen].
 *
 * Kept thin and Hilt-aware so it stays out of the unit/UI test path — tests
 * drive [DiscoveryScreen] directly with a hand-built [DiscoveryUiState].
 *
 * @param onTvSelected Invoked when the user picks a TV to pair/connect to.
 */
@Composable
fun DiscoveryRoute(
    onTvSelected: (DiscoveredTv) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: DiscoveryViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsState()
    DiscoveryScreen(
        state = uiState,
        onTvSelected = onTvSelected,
        onRetry = viewModel::startScan,
        modifier = modifier,
    )
}

/**
 * Stateless discovery screen: renders the [state] and reports user intent
 * through callbacks. Holding no business state of its own keeps it trivially
 * previewable and testable.
 *
 * Lists the discovered TVs; while a scan is in flight it shows a progress
 * indicator, and once a scan ends with no results it offers a retry. Tapping a
 * row invokes [onTvSelected] with that [DiscoveredTv].
 *
 * A manual-IP fallback is always available below the list (ADR-0003 — the UI
 * never reaches a dead end): on networks where SSDP/mDNS multicast is blocked,
 * the user can type the TV's IP directly. A valid address is turned into a
 * [DiscoveredTv] candidate and reported through [onTvSelected] just like a
 * discovered row, which starts pairing.
 *
 * @param onTvSelected Called with the chosen TV when a row is tapped or a valid
 *                     manual IP is submitted.
 * @param onRetry      Called when the user asks to scan again.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscoveryScreen(
    state: DiscoveryUiState,
    onTvSelected: (DiscoveredTv) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = { TopAppBar(title = { Text(stringResource(R.string.discovery_title)) }) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
            ) {
                if (state.tvs.isNotEmpty()) {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .testTag(DiscoveryTestTags.TV_LIST),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(items = state.tvs, key = { it.id }) { tv ->
                            TvRow(tv = tv, onClick = { onTvSelected(tv) })
                        }
                    }
                } else {
                    EmptyContent(state = state, onRetry = onRetry)
                }
            }
            HorizontalDivider()
            ManualIpEntry(onSubmit = onTvSelected)
        }
    }
}

@Composable
private fun TvRow(
    tv: DiscoveredTv,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .testTag(DiscoveryTestTags.tvItem(tv.id))
            .clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = tv.name,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val subtitle = listOfNotNull(tv.modelName, tv.ipAddress).joinToString(" • ")
            if (subtitle.isNotEmpty()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

/** Shown when no TVs have been discovered: scanning spinner, error, or empty + retry. */
@Composable
private fun EmptyContent(
    state: DiscoveryUiState,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        when {
            state.isScanning -> {
                CircularProgressIndicator(modifier = Modifier.testTag(DiscoveryTestTags.PROGRESS))
                Text(
                    text = stringResource(R.string.discovery_scanning),
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(top = 16.dp),
                )
            }

            state.error != null -> {
                Text(
                    text = state.error,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.testTag(DiscoveryTestTags.ERROR),
                )
                RetryButton(onRetry, Modifier.padding(top = 16.dp))
            }

            else -> {
                Text(
                    text = stringResource(R.string.discovery_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.testTag(DiscoveryTestTags.EMPTY),
                )
                RetryButton(onRetry, Modifier.padding(top = 16.dp))
            }
        }
    }
}

@Composable
private fun RetryButton(onRetry: () -> Unit, modifier: Modifier = Modifier) {
    OutlinedButton(onClick = onRetry, modifier = modifier) {
        Text(stringResource(R.string.discovery_retry))
    }
}

/**
 * Manual-IP fallback for networks where SSDP/mDNS multicast is blocked.
 *
 * Holds only its own transient field/validation state (presentation-local, so
 * the screen stays free of business state). On submit, the entered text is
 * validated as an IPv4 address: a valid address is turned into a [DiscoveredTv]
 * candidate via [manualTvCandidate] and handed to [onSubmit] (which starts
 * pairing); an invalid one surfaces an inline validation error and the callback
 * is not invoked.
 */
@Composable
private fun ManualIpEntry(
    onSubmit: (DiscoveredTv) -> Unit,
    modifier: Modifier = Modifier,
) {
    var ip by rememberSaveable { mutableStateOf("") }
    var showError by rememberSaveable { mutableStateOf(false) }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text = stringResource(R.string.discovery_manual_hint),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = ip,
            onValueChange = {
                ip = it
                showError = false
            },
            label = { Text(stringResource(R.string.discovery_manual_label)) },
            singleLine = true,
            isError = showError,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier
                .fillMaxWidth()
                .testTag(DiscoveryTestTags.MANUAL_IP_FIELD),
        )
        if (showError) {
            Text(
                text = stringResource(R.string.discovery_manual_invalid),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.testTag(DiscoveryTestTags.MANUAL_IP_ERROR),
            )
        }
        Button(
            onClick = {
                val candidate = ip.trim().takeIf(::isValidIpv4)?.let(::manualTvCandidate)
                if (candidate != null) {
                    onSubmit(candidate)
                    ip = ""
                    showError = false
                } else {
                    showError = true
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .testTag(DiscoveryTestTags.MANUAL_IP_SUBMIT),
        ) {
            Text(stringResource(R.string.discovery_manual_connect))
        }
    }
}

/**
 * Builds a transient [DiscoveredTv] candidate from a manually-entered [ip].
 *
 * The id is derived from the address (`manual:<ip>`) so a hand-typed TV
 * de-duplicates against itself across submissions; the model name is unknown
 * until pairing/connection resolves it.
 */
internal fun manualTvCandidate(ip: String): DiscoveredTv = DiscoveredTv(
    id = "manual:$ip",
    name = ip,
    ipAddress = ip,
    modelName = null,
)

/**
 * Validates [input] as a dotted-quad IPv4 address (four octets, each `0..255`).
 *
 * Lenient on surrounding whitespace; rejects empty octets, non-numeric octets,
 * octets longer than three digits, and the wrong number of octets.
 */
internal fun isValidIpv4(input: String): Boolean {
    val parts = input.trim().split(".")
    if (parts.size != 4) return false
    return parts.all { part ->
        part.isNotEmpty() &&
            part.length <= 3 &&
            part.all(Char::isDigit) &&
            part.toInt() in 0..255
    }
}
