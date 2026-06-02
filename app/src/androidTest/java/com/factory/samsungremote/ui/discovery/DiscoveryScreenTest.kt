package com.factory.samsungremote.ui.discovery

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.viewmodel.DiscoveryUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * Compose UI tests for [DiscoveryScreen].
 *
 * The screen is stateless, so the tests drive it directly with a hand-built
 * [DiscoveryUiState] — no ViewModel/Hilt involved.
 *
 * Acceptance criterion covered: the screen renders an item per discovered TV
 * and tapping a row fires [DiscoveryScreen]'s `onTvSelected` callback with that
 * exact [DiscoveredTv]. Scanning/empty states are checked for completeness.
 */
class DiscoveryScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    private val tvs = listOf(
        DiscoveredTv("uuid:1", "[TV] Living Room", "192.168.0.10", "QN65Q80B"),
        DiscoveredTv("uuid:2", "[TV] Bedroom", "192.168.0.11", null),
    )

    @Test
    fun rendersDiscoveredTvs_andFiresSelectionCallback() {
        var selected: DiscoveredTv? = null
        composeRule.setContent {
            DiscoveryScreen(
                state = DiscoveryUiState(tvs = tvs, isScanning = false),
                onTvSelected = { selected = it },
                onRetry = {},
            )
        }

        // Every discovered TV renders as its own row.
        composeRule.onNodeWithTag(DiscoveryTestTags.TV_LIST).assertIsDisplayed()
        composeRule.onNodeWithTag(DiscoveryTestTags.tvItem("uuid:1")).assertIsDisplayed()
        composeRule.onNodeWithTag(DiscoveryTestTags.tvItem("uuid:2")).assertIsDisplayed()

        // Tapping a row reports the chosen TV through the callback.
        composeRule.onNodeWithTag(DiscoveryTestTags.tvItem("uuid:2")).performClick()
        assertEquals(tvs[1], selected)
    }

    @Test
    fun showsProgress_whileScanningWithNoResults() {
        composeRule.setContent {
            DiscoveryScreen(
                state = DiscoveryUiState(isScanning = true),
                onTvSelected = {},
                onRetry = {},
            )
        }

        composeRule.onNodeWithTag(DiscoveryTestTags.PROGRESS).assertIsDisplayed()
    }

    @Test
    fun showsEmptyState_whenScanFinishesWithNoResults() {
        composeRule.setContent {
            DiscoveryScreen(
                state = DiscoveryUiState(isScanning = false),
                onTvSelected = {},
                onRetry = {},
            )
        }

        composeRule.onNodeWithTag(DiscoveryTestTags.EMPTY).assertIsDisplayed()
    }
}
