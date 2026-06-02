package com.factory.samsungremote.ui.discovery

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.viewmodel.DiscoveryUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * Compose UI tests for the manual-IP fallback on [DiscoveryScreen]
 * (task ae10f898 — manual IP entry when SSDP/mDNS discovery is blocked).
 *
 * The screen is stateless, so these drive it directly with an empty
 * [DiscoveryUiState] (the realistic "nothing discovered" case where the
 * fallback matters) and assert on the manual-IP field/submit/error tags.
 *
 * Acceptance criteria covered:
 *   - A valid IP creates a TV candidate and starts pairing: typing a valid
 *     address and submitting fires `onTvSelected` with a manual [DiscoveredTv]
 *     candidate (id `manual:<ip>`, ipAddress `<ip>`).
 *   - An invalid IP shows a validation error: submitting a malformed address
 *     surfaces the inline error and does NOT invoke the callback.
 */
class DiscoveryManualIpTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun validIp_createsCandidate_andStartsPairing() {
        var selected: DiscoveredTv? = null
        composeRule.setContent {
            DiscoveryScreen(
                state = DiscoveryUiState(isScanning = false),
                onTvSelected = { selected = it },
                onRetry = {},
            )
        }

        composeRule.onNodeWithTag(DiscoveryTestTags.MANUAL_IP_FIELD)
            .performTextInput("192.168.0.50")
        composeRule.onNodeWithTag(DiscoveryTestTags.MANUAL_IP_SUBMIT).performClick()

        // A valid address is turned into a candidate and reported (starts pairing).
        assertEquals(DiscoveredTv("manual:192.168.0.50", "192.168.0.50", "192.168.0.50", null), selected)
        // No validation error for a valid address.
        composeRule.onNodeWithTag(DiscoveryTestTags.MANUAL_IP_ERROR).assertIsNotDisplayed()
    }

    @Test
    fun invalidIp_showsValidationError_andDoesNotPair() {
        var selected: DiscoveredTv? = null
        composeRule.setContent {
            DiscoveryScreen(
                state = DiscoveryUiState(isScanning = false),
                onTvSelected = { selected = it },
                onRetry = {},
            )
        }

        composeRule.onNodeWithTag(DiscoveryTestTags.MANUAL_IP_FIELD)
            .performTextInput("999.1")
        composeRule.onNodeWithTag(DiscoveryTestTags.MANUAL_IP_SUBMIT).performClick()

        // The inline validation error is shown and pairing is NOT started.
        composeRule.onNodeWithTag(DiscoveryTestTags.MANUAL_IP_ERROR).assertIsDisplayed()
        assertNull(selected)
    }
}
