package com.factory.samsungremote.ui.remote

import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import com.factory.samsungremote.data.registry.RemoteKeyCatalog
import com.factory.samsungremote.viewmodel.RemoteIntent
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * Compose UI tests for [RemoteScreen] (task b8b43f30 — "Tela de controle:
 * D-pad, ENTER, RETURN/HOME/MENU").
 *
 * The screen is stateless: it takes an `onIntent` callback and emits a
 * [RemoteIntent.PressKey] per control press. The tests drive it directly with a
 * recording callback (the "fake" of the acceptance criteria) — no
 * ViewModel/Hilt/session involved — mirroring the discovery/pairing screens.
 *
 * Acceptance criteria covered:
 *  1. Tapping each direction / OK / RETURN / HOME / MENU / POWER fires the
 *     corresponding intent (verified against the recording callback), carrying
 *     the exact `KEY_*` code from [RemoteKeyCatalog].
 *  2. Every interactive control has a touch target ≥ 48 dp.
 */
class RemoteScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    /** The control's stable test tag paired with the protocol code it must emit. */
    private val controls: List<Pair<String, String>> = listOf(
        RemoteTestTags.DPAD_UP to "KEY_UP",
        RemoteTestTags.DPAD_DOWN to "KEY_DOWN",
        RemoteTestTags.DPAD_LEFT to "KEY_LEFT",
        RemoteTestTags.DPAD_RIGHT to "KEY_RIGHT",
        RemoteTestTags.OK to "KEY_ENTER",
        RemoteTestTags.RETURN to "KEY_RETURN",
        RemoteTestTags.HOME to "KEY_HOME",
        RemoteTestTags.MENU to "KEY_MENU",
        RemoteTestTags.POWER to "KEY_POWER",
    )

    @Test
    fun tappingEachControl_firesMatchingPressKeyIntent() {
        val emitted = mutableListOf<RemoteIntent>()
        composeRule.setContent {
            RemoteScreen(onIntent = { emitted += it })
        }

        controls.forEach { (tag, expectedCode) ->
            emitted.clear()
            composeRule.onNodeWithTag(tag).assertIsDisplayed()
            composeRule.onNodeWithTag(tag).performClick()

            // Exactly one intent per tap, and it carries the catalog key for this control.
            assertEquals("control $tag should emit one intent", 1, emitted.size)
            val intent = emitted.single()
            assertEquals(
                "control $tag should emit a PressKey",
                RemoteIntent.PressKey(RemoteKeyCatalog.findByCode(expectedCode)!!),
                intent,
            )
        }
    }

    @Test
    fun everyControl_meetsMinimumTouchTarget() {
        composeRule.setContent {
            RemoteScreen(onIntent = {})
        }

        // Material accessibility floor called out in the acceptance criteria.
        controls.forEach { (tag, _) ->
            composeRule.onNodeWithTag(tag).assertWidthIsAtLeast(48.dp)
            composeRule.onNodeWithTag(tag).assertHeightIsAtLeast(48.dp)
        }
    }

    @Test
    fun dpadAndOk_emitDistinctKeys() {
        val emitted = mutableListOf<RemoteIntent>()
        composeRule.setContent {
            RemoteScreen(onIntent = { emitted += it })
        }

        listOf(
            RemoteTestTags.DPAD_UP,
            RemoteTestTags.DPAD_DOWN,
            RemoteTestTags.DPAD_LEFT,
            RemoteTestTags.DPAD_RIGHT,
            RemoteTestTags.OK,
        ).forEach { composeRule.onNodeWithTag(it).performClick() }

        // No control is hard-coded to the same key as another (D-pad + OK = 5 distinct).
        val codes = emitted.filterIsInstance<RemoteIntent.PressKey>().map { it.key.code }
        assertEquals(listOf("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_ENTER"), codes)
    }
}
