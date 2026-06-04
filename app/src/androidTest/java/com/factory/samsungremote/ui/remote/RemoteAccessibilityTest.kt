package com.factory.samsungremote.ui.remote

import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.unit.dp
import org.junit.Rule
import org.junit.Test

/**
 * Compose accessibility (TalkBack) tests for [RemoteScreen] — task
 * "Acessibilidade e TalkBack".
 *
 * Acceptance criterion verified here: **every button has a non-empty
 * contentDescription and a touch target of at least 48 dp.** The screen is
 * stateless, so the test renders it directly with a no-op `onIntent` and then,
 * for every interactive control tag, asserts:
 *   1. the node exposes a non-empty `contentDescription` in its semantics (so
 *      TalkBack announces the action in words, not the bare arrow/glyph/label);
 *   2. the node measures ≥ 48 dp on both axes (Material minimum touch target).
 *
 * The list below is the full set of buttons the screen renders: the D-pad +
 * OK, RETURN/HOME/MENU, POWER, volume/channel, media transport, the ten numeric
 * digits, the streaming shortcuts and the text-Send button. The free-text input
 * field is intentionally excluded (it is labelled, not a button).
 */
class RemoteAccessibilityTest {

    @get:Rule
    val composeRule = createComposeRule()

    /** Every button the remote screen exposes, by its stable test tag. */
    private val buttonTags: List<String> = buildList {
        // D-pad + OK
        add(RemoteTestTags.DPAD_UP)
        add(RemoteTestTags.DPAD_DOWN)
        add(RemoteTestTags.DPAD_LEFT)
        add(RemoteTestTags.DPAD_RIGHT)
        add(RemoteTestTags.OK)
        // Primary navigation + power
        add(RemoteTestTags.RETURN)
        add(RemoteTestTags.HOME)
        add(RemoteTestTags.MENU)
        add(RemoteTestTags.POWER)
        // Volume / channel
        add(RemoteTestTags.VOL_DOWN)
        add(RemoteTestTags.MUTE)
        add(RemoteTestTags.VOL_UP)
        add(RemoteTestTags.CH_DOWN)
        add(RemoteTestTags.CH_UP)
        // Media transport
        add(RemoteTestTags.REW)
        add(RemoteTestTags.PLAY)
        add(RemoteTestTags.PAUSE)
        add(RemoteTestTags.STOP)
        add(RemoteTestTags.FF)
        // Numeric keypad 0..9
        (0..9).forEach { add(RemoteTestTags.digit(it)) }
        // Streaming shortcuts
        add(RemoteTestTags.APP_NETFLIX)
        add(RemoteTestTags.APP_PRIME)
        add(RemoteTestTags.APP_DISNEY)
        add(RemoteTestTags.APP_YOUTUBE)
        // Text-entry Send button
        add(RemoteTestTags.TEXT_SEND)
    }

    /** Matches a node whose semantics carry a non-blank contentDescription. */
    private fun hasNonEmptyContentDescription(): SemanticsMatcher =
        SemanticsMatcher("has non-empty contentDescription") { node ->
            val descriptions = node.config.getOrNull(SemanticsProperties.ContentDescription)
            descriptions != null && descriptions.any { it.isNotBlank() }
        }

    @Test
    fun everyButton_hasNonEmptyContentDescription() {
        composeRule.setContent {
            RemoteScreen(onIntent = { true })
        }

        // The keypad + text-entry buttons live behind the keypad toggle; reveal
        // them so every button is in the tree for this pass.
        composeRule.onNodeWithTag(RemoteTestTags.KEYPAD_TOGGLE).performClick()

        // TalkBack reads the contentDescription aloud; none may be empty.
        buttonTags.forEach { tag ->
            composeRule.onNodeWithTag(tag).assert(hasNonEmptyContentDescription())
        }
    }

    @Test
    fun everyButton_meetsMinimumTouchTarget() {
        composeRule.setContent {
            RemoteScreen(onIntent = { true })
        }

        // Reveal the keypad + text-entry buttons before measuring them.
        composeRule.onNodeWithTag(RemoteTestTags.KEYPAD_TOGGLE).performClick()

        // Material accessibility floor: ≥ 48 dp on both axes for every button.
        buttonTags.forEach { tag ->
            composeRule.onNodeWithTag(tag).assertWidthIsAtLeast(48.dp)
            composeRule.onNodeWithTag(tag).assertHeightIsAtLeast(48.dp)
        }
    }
}
