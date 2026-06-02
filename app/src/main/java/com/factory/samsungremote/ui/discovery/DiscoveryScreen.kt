package com.factory.samsungremote.ui.discovery

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
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
 * through callbacks. Holding no state of its own keeps it trivially previewable
 * and testable.
 *
 * Lists the discovered TVs; while a scan is in flight it shows a progress
 * indicator, and once a scan ends with no results it offers a retry. Tapping a
 * row invokes [onTvSelected] with that [DiscoveredTv].
 *
 * @param onTvSelected Called with the chosen TV when a row is tapped.
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
