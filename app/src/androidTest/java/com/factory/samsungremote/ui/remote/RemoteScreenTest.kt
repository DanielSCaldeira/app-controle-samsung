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
        // Media transport bar (task a7e024f7 — play/pause/stop/rew/ff).
        RemoteTestTags.REW to "KEY_REW",
        RemoteTestTags.PLAY to "KEY_PLAY",
        RemoteTestTags.PAUSE to "KEY_PAUSE",
        RemoteTestTags.STOP to "KEY_STOP",
        RemoteTestTags.FF to "KEY_FF",
    )

    /** Just the media-transport controls added by task a7e024f7. */
    private val mediaControls: List<Pair<String, String>> = listOf(
        RemoteTestTags.REW to "KEY_REW",
        RemoteTestTags.PLAY to "KEY_PLAY",
        RemoteTestTags.PAUSE to "KEY_PAUSE",
        RemoteTestTags.STOP to "KEY_STOP",
        RemoteTestTags.FF to "KEY_FF",
    )

    /**
     * The numeric-keypad controls added by task f7ed960d: each digit's stable
     * test tag ([RemoteTestTags.digit]) paired with the `KEY_<n>` code it emits.
     */
    private val digitControls: List<Pair<String, String>> =
        (0..9).map { RemoteTestTags.digit(it) to "KEY_$it" }

    @Test
    fun tappingEachControl_firesMatchingPressKeyIntent() {
        val emitted = mutableListOf<RemoteIntent>()
        composeRule.setContent {
            RemoteScreen(onIntent = { emitted += it; true })
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
            RemoteScreen(onIntent = { true })
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
            RemoteScreen(onIntent = { emitted += it; true })
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

    @Test
    fun tappingEachMediaButton_firesItsRemoteKey() {
        val emitted = mutableListOf<RemoteIntent>()
        composeRule.setContent {
            RemoteScreen(onIntent = { emitted += it; true })
        }

        // Each media-transport button fires the matching RemoteKey on the fake.
        mediaControls.forEach { (tag, expectedCode) ->
            emitted.clear()
            composeRule.onNodeWithTag(tag).assertIsDisplayed()
            composeRule.onNodeWithTag(tag).performClick()

            assertEquals("media control $tag should emit one intent", 1, emitted.size)
            assertEquals(
                "media control $tag should emit its PressKey",
                RemoteIntent.PressKey(RemoteKeyCatalog.findByCode(expectedCode)!!),
                emitted.single(),
            )
        }
    }

    @Test
    fun mediaButtons_emitDistinctKeysInBarOrder() {
        val emitted = mutableListOf<RemoteIntent>()
        composeRule.setContent {
            RemoteScreen(onIntent = { emitted += it; true })
        }

        mediaControls.forEach { (tag, _) -> composeRule.onNodeWithTag(tag).performClick() }

        // REW / PLAY / PAUSE / STOP / FF — five distinct keys, none hard-coded to another.
        val codes = emitted.filterIsInstance<RemoteIntent.PressKey>().map { it.key.code }
        assertEquals(listOf("KEY_REW", "KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_FF"), codes)
    }

    @Test
    fun tappingEachDigit_firesItsRemoteKey() {
        val emitted = mutableListOf<RemoteIntent>()
        composeRule.setContent {
            RemoteScreen(onIntent = { emitted += it; true })
        }

        // Tapping each digit (0..9) fires the matching KEY_<n> on the fake callback.
        digitControls.forEach { (tag, expectedCode) ->
            emitted.clear()
            composeRule.onNodeWithTag(tag).assertIsDisplayed()
            composeRule.onNodeWithTag(tag).performClick()

            assertEquals("digit $tag should emit one intent", 1, emitted.size)
            assertEquals(
                "digit $tag should emit its PressKey",
                RemoteIntent.PressKey(RemoteKeyCatalog.findByCode(expectedCode)!!),
                emitted.single(),
            )
        }
    }

    @Test
    fun everyDigit_meetsMinimumTouchTarget() {
        composeRule.setContent {
            RemoteScreen(onIntent = { true })
        }

        // Material accessibility floor: every digit honors a ≥ 48 dp touch target.
        digitControls.forEach { (tag, _) ->
            composeRule.onNodeWithTag(tag).assertWidthIsAtLeast(48.dp)
            composeRule.onNodeWithTag(tag).assertHeightIsAtLeast(48.dp)
        }
    }
}
