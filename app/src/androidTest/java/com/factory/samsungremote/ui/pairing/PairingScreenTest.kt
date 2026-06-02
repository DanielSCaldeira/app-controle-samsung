package com.factory.samsungremote.ui.pairing

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.factory.samsungremote.network.pairing.PairingFailureReason
import com.factory.samsungremote.viewmodel.PairingStatus
import com.factory.samsungremote.viewmodel.PairingUiState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * Compose UI tests for [PairingScreen].
 *
 * The screen is stateless, so the tests drive it directly with a hand-built
 * [PairingUiState] — no ViewModel/Hilt/PairingManager involved.
 *
 * Acceptance criteria covered (task 250ebe0e — "Tela de pareamento"):
 *  1. The "accept on your TV / waiting for authorization" instruction is shown
 *     while pairing is in flight ([PairingStatus.Pairing]).
 *  2. When a token arrives ([PairingStatus.Success]) the screen navigates on by
 *     firing `onPaired` with that exact token — and only once.
 *  3. On failure ([PairingStatus.Error]) the screen shows a retry affordance and
 *     tapping it fires `onRetry`.
 */
class PairingScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun showsWaitingInstruction_whilePairing() {
        composeRule.setContent {
            PairingScreen(
                state = PairingUiState(status = PairingStatus.Pairing),
                onPaired = {},
                onRetry = {},
            )
        }

        // "Aguardando autorização": the instruction and the progress spinner.
        composeRule.onNodeWithTag(PairingTestTags.INSTRUCTION).assertIsDisplayed()
        composeRule.onNodeWithTag(PairingTestTags.PROGRESS).assertIsDisplayed()
    }

    @Test
    fun navigatesOnce_whenTokenReceived() {
        val paired = mutableListOf<String>()
        composeRule.setContent {
            PairingScreen(
                state = PairingUiState(
                    status = PairingStatus.Success,
                    token = "FAKE-TOKEN-123",
                ),
                onPaired = { paired += it },
                onRetry = {},
            )
        }
        composeRule.waitForIdle()

        // Success → navigate to the control screen, exactly once, with the token.
        assertEquals(listOf("FAKE-TOKEN-123"), paired)
    }

    @Test
    fun doesNotNavigate_whilePairing() {
        val paired = mutableListOf<String>()
        composeRule.setContent {
            PairingScreen(
                state = PairingUiState(status = PairingStatus.Pairing),
                onPaired = { paired += it },
                onRetry = {},
            )
        }
        composeRule.waitForIdle()

        assertEquals(emptyList<String>(), paired)
    }

    @Test
    fun showsRetry_onError_andFiresCallback() {
        var retries = 0
        var paired: String? = null
        composeRule.setContent {
            PairingScreen(
                state = PairingUiState(
                    status = PairingStatus.Error,
                    failureReason = PairingFailureReason.UNAUTHORIZED,
                ),
                onPaired = { paired = it },
                onRetry = { retries++ },
            )
        }

        // Error message + retry button are shown; no navigation happened.
        composeRule.onNodeWithTag(PairingTestTags.ERROR).assertIsDisplayed()
        composeRule.onNodeWithTag(PairingTestTags.RETRY).assertIsDisplayed()
        assertNull(paired)

        // Tapping "Try again" asks the host to pair again.
        composeRule.onNodeWithTag(PairingTestTags.RETRY).performClick()
        assertEquals(1, retries)
    }
}
