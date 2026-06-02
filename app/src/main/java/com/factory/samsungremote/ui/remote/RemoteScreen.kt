package com.factory.samsungremote.ui.remote

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.factory.samsungremote.R
import com.factory.samsungremote.data.registry.AppShortcut
import com.factory.samsungremote.data.registry.AppShortcutCatalog
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.registry.RemoteKeyCatalog
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.viewmodel.RemoteIntent
import com.factory.samsungremote.viewmodel.RemoteViewModel

/** Stable test tags for the remote-control UI, shared with Compose UI tests. */
object RemoteTestTags {
    const val DPAD_UP = "remote_dpad_up"
    const val DPAD_DOWN = "remote_dpad_down"
    const val DPAD_LEFT = "remote_dpad_left"
    const val DPAD_RIGHT = "remote_dpad_right"
    const val OK = "remote_ok"
    const val RETURN = "remote_return"
    const val HOME = "remote_home"
    const val MENU = "remote_menu"
    const val POWER = "remote_power"
    const val VOL_UP = "remote_vol_up"
    const val VOL_DOWN = "remote_vol_down"
    const val MUTE = "remote_mute"
    const val CH_UP = "remote_ch_up"
    const val CH_DOWN = "remote_ch_down"
    const val PLAY = "remote_play"
    const val PAUSE = "remote_pause"
    const val STOP = "remote_stop"
    const val REW = "remote_rew"
    const val FF = "remote_ff"
    const val APP_NETFLIX = "remote_app_netflix"
    const val APP_PRIME = "remote_app_prime"
    const val APP_DISNEY = "remote_app_disney"
    const val APP_YOUTUBE = "remote_app_youtube"
    const val TEXT_INPUT = "remote_text_input"
    const val TEXT_SEND = "remote_text_send"

    /**
     * Test tag for numeric-keypad digit [n] (0..9), the control that emits
     * `KEY_<n>`. Exposed as a function so tests can iterate the ten digits
     * without ten separate constants.
     */
    fun digit(n: Int): String {
        require(n in 0..9) { "digit must be 0..9: $n" }
        return "remote_digit_$n"
    }
}

/**
 * Minimum touch-target side for every control, per the Material accessibility
 * guideline (≥ 48 dp) called out in this task's acceptance criteria. Applied via
 * [Modifier.sizeIn] so labels can still grow the button beyond the floor.
 */
private val MinTouchTarget = 56.dp

/**
 * The keys this screen drives, resolved once from the static [RemoteKeyCatalog]
 * so the UI never hard-codes a `KEY_*` string and stays in sync with the catalog.
 */
private fun key(code: String): RemoteKey =
    requireNotNull(RemoteKeyCatalog.findByCode(code)) { "Missing key in catalog: $code" }

private val KeyUp = key("KEY_UP")
private val KeyDown = key("KEY_DOWN")
private val KeyLeft = key("KEY_LEFT")
private val KeyRight = key("KEY_RIGHT")
private val KeyEnter = key("KEY_ENTER")
private val KeyReturn = key("KEY_RETURN")
private val KeyHome = key("KEY_HOME")
private val KeyMenu = key("KEY_MENU")
private val KeyPower = key("KEY_POWER")
private val KeyVolUp = key("KEY_VOLUP")
private val KeyVolDown = key("KEY_VOLDOWN")
private val KeyMute = key("KEY_MUTE")
private val KeyChUp = key("KEY_CHUP")
private val KeyChDown = key("KEY_CHDOWN")
private val KeyPlay = key("KEY_PLAY")
private val KeyPause = key("KEY_PAUSE")
private val KeyStop = key("KEY_STOP")
private val KeyRew = key("KEY_REW")
private val KeyFf = key("KEY_FF")

/**
 * The numeric keypad keys (`KEY_0`..`KEY_9`), indexed by digit so
 * `NumericKeys[n]` is the [RemoteKey] for digit `n`. Resolved once from the
 * static [RemoteKeyCatalog] so the UI never hard-codes a `KEY_<n>` string.
 */
private val NumericKeys: List<RemoteKey> = (0..9).map { key("KEY_$it") }

/**
 * Key the streaming shortcuts fall back to when
 * [com.factory.samsungremote.data.repository.CommandRepository.launchApp] reports
 * the app did not open (e.g. the deep link is unsupported on this TV):
 * we drop the user onto the TV Home screen so they can navigate to the app by
 * key instead of being left with a silent no-op.
 */
private val FallbackNavKey = key("KEY_HOME")

/**
 * The launchable streaming apps this screen exposes as dedicated shortcuts,
 * resolved once from the static [AppShortcutCatalog] so the UI never hard-codes a
 * Tizen `appId` and stays in sync with the catalog.
 */
private fun appShortcut(appId: String): AppShortcut =
    requireNotNull(AppShortcutCatalog.findByAppId(appId)) {
        "Missing app shortcut in catalog: $appId"
    }

private val AppNetflix = appShortcut("11101200001")
private val AppPrime = appShortcut("3201910019365")
private val AppDisney = appShortcut("3201901017640")
private val AppYouTube = appShortcut("111299001912")

/**
 * Remote-control entry point: binds the [RemoteViewModel] to the stateless
 * [RemoteScreen] and opens the control connection to the chosen TV.
 *
 * On entry (and after process recreation) it replays the pairing [token] to
 * [RemoteViewModel.connect] for [tv], so the session connects to an authorized
 * device and the controls' intents reach an open socket. Both inputs are carried
 * here by the host's navigation from discovery → pairing → remote.
 *
 * Kept thin and Hilt-aware so it stays out of the UI test path — tests drive
 * [RemoteScreen] directly with a recording `onIntent` callback (no ViewModel/
 * Hilt/session involved), mirroring the discovery/pairing screens.
 *
 * @param tv    The TV that was discovered and paired with; the session connects here.
 * @param token Authorization token returned by pairing, replayed so an already
 *              authorized device is not re-prompted; `null` when unknown.
 */
@Composable
fun RemoteRoute(
    tv: DiscoveredTv,
    token: String?,
    modifier: Modifier = Modifier,
    viewModel: RemoteViewModel = hiltViewModel(),
) {
    // Open (or re-target) the connection for the paired TV, replaying the token.
    LaunchedEffect(tv.id, token) { viewModel.connect(tv, token) }

    // Collected so future state-driven UI (connected/reconnecting) can react; the
    // controls themselves are stateless and only emit intents.
    val connectionState by viewModel.connectionState.collectAsState()
    RemoteScreen(
        onIntent = { viewModel.onIntent(it) },
        modifier = modifier,
    )
}

/**
 * Stateless remote-control screen: renders the D-pad (up/down/left/right + OK),
 * the RETURN / HOME / MENU navigation keys, the volume (VOL- / MUTE / VOL+) and
 * channel (CH- / CH+) controls, the numeric keypad (KEY_0..KEY_9) for direct
 * channel entry, the media transport bar (REW / PLAY / PAUSE / STOP / FF), the
 * streaming app shortcuts (Netflix / Prime Video / Disney+ /
 * YouTube) and a POWER toggle, reporting every action as a [RemoteIntent]
 * through [onIntent].
 *
 * Holding no state of its own keeps it trivially previewable and testable: a
 * test can pass a recording `onIntent` and assert that tapping each control
 * emits the matching intent. Every control honors a ≥ 48 dp touch target.
 *
 * [onIntent] returns whether the resulting frame reached an open connection
 * (propagated from [com.factory.samsungremote.data.repository.CommandRepository]
 * via the ViewModel). The streaming shortcuts use this signal: when a
 * [RemoteIntent.LaunchApp] reports failure, the screen falls back to a
 * [RemoteIntent.PressKey] on [FallbackNavKey] (Home) so the user can reach the
 * app by key instead of facing a silent no-op.
 *
 * @param onIntent Called with the [RemoteIntent] produced by a control press;
 *                 returns `true` when the frame reached an open connection.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RemoteScreen(
    onIntent: (RemoteIntent) -> Boolean,
    modifier: Modifier = Modifier,
) {
    val press: (RemoteKey) -> Unit = { onIntent(RemoteIntent.PressKey(it)) }
    val type: (String) -> Unit = { text -> onIntent(RemoteIntent.TypeText(text)) }
    val launch: (AppShortcut) -> Unit = { shortcut ->
        // Fall back to key navigation (Home) when the app fails to launch.
        if (!onIntent(RemoteIntent.LaunchApp(shortcut.appId))) {
            onIntent(RemoteIntent.PressKey(FallbackNavKey))
        }
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.remote_title)) },
                actions = {
                    val powerDescription = stringResource(R.string.remote_cd_power)
                    IconButton(
                        onClick = { press(KeyPower) },
                        modifier = Modifier
                            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
                            .testTag(RemoteTestTags.POWER)
                            .semantics {
                                contentDescription = powerDescription
                            },
                    ) {
                        Text("⏻", style = MaterialTheme.typography.titleLarge)
                    }
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
        ) {
            DPad(onPress = press)
            NavRow(onPress = press)
            TextEntryRow(onSend = type)
            VolumeChannelRow(onPress = press)
            NumericKeypad(onPress = press)
            MediaRow(onPress = press)
            ShortcutRow(onLaunch = launch)
        }
    }
}

/**
 * The directional pad: UP on top, LEFT / OK / RIGHT in the middle and DOWN at the
 * bottom — the conventional cross layout, with OK ([RemoteKey] `KEY_ENTER`) at the
 * center.
 */
@Composable
private fun DPad(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        DirButton(
            label = stringResource(R.string.remote_dpad_up),
            contentDescription = stringResource(R.string.remote_cd_up),
            tag = RemoteTestTags.DPAD_UP,
            onClick = { onPress(KeyUp) },
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            DirButton(
                label = stringResource(R.string.remote_dpad_left),
                contentDescription = stringResource(R.string.remote_cd_left),
                tag = RemoteTestTags.DPAD_LEFT,
                onClick = { onPress(KeyLeft) },
            )
            OkButton(onClick = { onPress(KeyEnter) })
            DirButton(
                label = stringResource(R.string.remote_dpad_right),
                contentDescription = stringResource(R.string.remote_cd_right),
                tag = RemoteTestTags.DPAD_RIGHT,
                onClick = { onPress(KeyRight) },
            )
        }
        DirButton(
            label = stringResource(R.string.remote_dpad_down),
            contentDescription = stringResource(R.string.remote_cd_down),
            tag = RemoteTestTags.DPAD_DOWN,
            onClick = { onPress(KeyDown) },
        )
    }
}

/** RETURN / HOME / MENU laid out in a single row beneath the D-pad. */
@Composable
private fun NavRow(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        NavButton(
            label = stringResource(R.string.remote_return),
            contentDescription = stringResource(R.string.remote_cd_return),
            tag = RemoteTestTags.RETURN,
            onClick = { onPress(KeyReturn) },
        )
        NavButton(
            label = stringResource(R.string.remote_home),
            contentDescription = stringResource(R.string.remote_cd_home),
            tag = RemoteTestTags.HOME,
            onClick = { onPress(KeyHome) },
        )
        NavButton(
            label = stringResource(R.string.remote_menu),
            contentDescription = stringResource(R.string.remote_cd_menu),
            tag = RemoteTestTags.MENU,
            onClick = { onPress(KeyMenu) },
        )
    }
}

/**
 * Text-entry control: a single-line field plus a Send button for typing into the
 * focused field on the TV (e.g. a search box). The field holds its own transient
 * text via [rememberSaveable] — the only UI state on this otherwise-stateless
 * screen — so it survives recomposition and configuration changes.
 *
 * Submitting (tapping Send or pressing the keyboard's Done/Search action) forwards
 * the current text to [onSend], which the screen routes to a
 * [RemoteIntent.TypeText]; the protocol layer Base64-encodes it on the wire. Blank
 * input is ignored and the field is cleared after a successful send so the next
 * search starts fresh. Both controls honor the ≥ 48 dp touch target.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TextEntryRow(
    onSend: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var text by rememberSaveable { mutableStateOf("") }
    val submit: () -> Unit = {
        if (text.isNotBlank()) {
            onSend(text)
            text = ""
        }
    }
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            singleLine = true,
            label = { Text(stringResource(R.string.remote_text_label)) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { submit() }),
            modifier = Modifier
                .weight(1f)
                .sizeIn(minHeight = MinTouchTarget)
                .testTag(RemoteTestTags.TEXT_INPUT),
        )
        val sendDescription = stringResource(R.string.remote_cd_text_send)
        Button(
            onClick = submit,
            modifier = Modifier
                .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
                .testTag(RemoteTestTags.TEXT_SEND)
                .semantics { contentDescription = sendDescription },
        ) {
            Text(stringResource(R.string.remote_text_send))
        }
    }
}

/**
 * Volume and channel controls laid out in a single row beneath the navigation
 * keys: VOL- / MUTE / VOL+ followed by CH- / CH+. Each press emits the matching
 * [RemoteKey] (`KEY_VOLDOWN`, `KEY_MUTE`, `KEY_VOLUP`, `KEY_CHDOWN`, `KEY_CHUP`).
 */
@Composable
private fun VolumeChannelRow(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        NavButton(
            label = stringResource(R.string.remote_vol_down),
            contentDescription = stringResource(R.string.remote_cd_vol_down),
            tag = RemoteTestTags.VOL_DOWN,
            onClick = { onPress(KeyVolDown) },
        )
        NavButton(
            label = stringResource(R.string.remote_mute),
            contentDescription = stringResource(R.string.remote_cd_mute),
            tag = RemoteTestTags.MUTE,
            onClick = { onPress(KeyMute) },
        )
        NavButton(
            label = stringResource(R.string.remote_vol_up),
            contentDescription = stringResource(R.string.remote_cd_vol_up),
            tag = RemoteTestTags.VOL_UP,
            onClick = { onPress(KeyVolUp) },
        )
        NavButton(
            label = stringResource(R.string.remote_ch_down),
            contentDescription = stringResource(R.string.remote_cd_ch_down),
            tag = RemoteTestTags.CH_DOWN,
            onClick = { onPress(KeyChDown) },
        )
        NavButton(
            label = stringResource(R.string.remote_ch_up),
            contentDescription = stringResource(R.string.remote_cd_ch_up),
            tag = RemoteTestTags.CH_UP,
            onClick = { onPress(KeyChUp) },
        )
    }
}

/**
 * Numeric keypad (`KEY_0`..`KEY_9`) for direct channel entry, laid out as the
 * conventional 3×3 grid (1–9) with 0 centered beneath. Each digit press emits
 * the matching [RemoteKey] (`KEY_<n>`, resolved from [NumericKeys]).
 */
@Composable
private fun NumericKeypad(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // Phone-keypad order: 1-9 in three rows, then 0 on its own row.
        listOf(
            listOf(1, 2, 3),
            listOf(4, 5, 6),
            listOf(7, 8, 9),
            listOf(0),
        ).forEach { rowDigits ->
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                rowDigits.forEach { digit ->
                    DigitButton(
                        digit = digit,
                        onClick = { onPress(NumericKeys[digit]) },
                    )
                }
            }
        }
    }
}

/**
 * Media transport bar laid out in a single row beneath the volume/channel
 * controls: REW / PLAY / PAUSE / STOP / FF. Each press emits the matching
 * [RemoteKey] (`KEY_REW`, `KEY_PLAY`, `KEY_PAUSE`, `KEY_STOP`, `KEY_FF`).
 */
@Composable
private fun MediaRow(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        NavButton(
            label = stringResource(R.string.remote_rew),
            contentDescription = stringResource(R.string.remote_cd_rew),
            tag = RemoteTestTags.REW,
            onClick = { onPress(KeyRew) },
        )
        NavButton(
            label = stringResource(R.string.remote_play),
            contentDescription = stringResource(R.string.remote_cd_play),
            tag = RemoteTestTags.PLAY,
            onClick = { onPress(KeyPlay) },
        )
        NavButton(
            label = stringResource(R.string.remote_pause),
            contentDescription = stringResource(R.string.remote_cd_pause),
            tag = RemoteTestTags.PAUSE,
            onClick = { onPress(KeyPause) },
        )
        NavButton(
            label = stringResource(R.string.remote_stop),
            contentDescription = stringResource(R.string.remote_cd_stop),
            tag = RemoteTestTags.STOP,
            onClick = { onPress(KeyStop) },
        )
        NavButton(
            label = stringResource(R.string.remote_ff),
            contentDescription = stringResource(R.string.remote_cd_ff),
            tag = RemoteTestTags.FF,
            onClick = { onPress(KeyFf) },
        )
    }
}

/**
 * Streaming app shortcuts laid out in a single row beneath the media controls:
 * Netflix / Prime Video / Disney+ / YouTube. Each press asks [onLaunch] to launch
 * the matching [AppShortcut] (resolved from [AppShortcutCatalog]); the screen's
 * `launch` handler routes that to a [RemoteIntent.LaunchApp] and falls back to key
 * navigation when the app does not open.
 */
@Composable
private fun ShortcutRow(
    onLaunch: (AppShortcut) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ShortcutButton(
            label = stringResource(R.string.remote_app_netflix),
            tag = RemoteTestTags.APP_NETFLIX,
            onClick = { onLaunch(AppNetflix) },
        )
        ShortcutButton(
            label = stringResource(R.string.remote_app_prime),
            tag = RemoteTestTags.APP_PRIME,
            onClick = { onLaunch(AppPrime) },
        )
        ShortcutButton(
            label = stringResource(R.string.remote_app_disney),
            tag = RemoteTestTags.APP_DISNEY,
            onClick = { onLaunch(AppDisney) },
        )
        ShortcutButton(
            label = stringResource(R.string.remote_app_youtube),
            tag = RemoteTestTags.APP_YOUTUBE,
            onClick = { onLaunch(AppYouTube) },
        )
    }
}

/**
 * A directional (arrow) D-pad button with a ≥ 48 dp touch target and an explicit
 * [contentDescription] so TalkBack announces the direction in words ("Navigate up")
 * rather than the bare arrow [label].
 */
@Composable
private fun DirButton(
    label: String,
    contentDescription: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = contentDescription
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(tag)
            .semantics { this.contentDescription = description },
    ) {
        Text(label)
    }
}

/** The center OK / ENTER button, with an explicit TalkBack description. */
@Composable
private fun OkButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = stringResource(R.string.remote_cd_ok)
    Button(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(RemoteTestTags.OK)
            .semantics { contentDescription = description },
    ) {
        Text(stringResource(R.string.remote_ok))
    }
}

/**
 * A secondary navigation button (RETURN / HOME / MENU, VOL / CH, media transport)
 * with a ≥ 48 dp target and an explicit [contentDescription] so TalkBack announces
 * the action in words even when the visible [label] is an abbreviation or glyph.
 */
@Composable
private fun NavButton(
    label: String,
    contentDescription: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = contentDescription
    OutlinedButton(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(tag)
            .semantics { this.contentDescription = description },
    ) {
        Text(label)
    }
}

/**
 * A single numeric-keypad button. Labeled with [digit] (0–9) and tagged with
 * [RemoteTestTags.digit] so tests can locate each digit; carries an explicit
 * TalkBack description ("Digit N") and honors the ≥ 48 dp touch target like every
 * other control.
 */
@Composable
private fun DigitButton(
    digit: Int,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = stringResource(R.string.remote_cd_digit, digit)
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(RemoteTestTags.digit(digit))
            .semantics { contentDescription = description },
    ) {
        Text(digit.toString())
    }
}

/**
 * A streaming app shortcut button (Netflix / Prime / Disney+ / YouTube), with an
 * explicit "Launch <app>" TalkBack description derived from [label].
 */
@Composable
private fun ShortcutButton(
    label: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = stringResource(R.string.remote_cd_app_launch, label)
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(tag)
            .semantics { contentDescription = description },
    ) {
        Text(label)
    }
}
