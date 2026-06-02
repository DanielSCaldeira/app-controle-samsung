package com.factory.samsungremote.ui.remote

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.factory.samsungremote.R
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.registry.RemoteKeyCatalog
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
 * Remote-control entry point: binds the [RemoteViewModel] to the stateless
 * [RemoteScreen].
 *
 * Kept thin and Hilt-aware so it stays out of the UI test path — tests drive
 * [RemoteScreen] directly with a recording `onIntent` callback (no ViewModel/
 * Hilt/session involved), mirroring the discovery/pairing screens.
 */
@Composable
fun RemoteRoute(
    modifier: Modifier = Modifier,
    viewModel: RemoteViewModel = hiltViewModel(),
) {
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
 * channel (CH- / CH+) controls, the media transport bar (REW / PLAY / PAUSE /
 * STOP / FF) and a POWER toggle, reporting every press as a
 * [RemoteIntent.PressKey] through [onIntent].
 *
 * Holding no state of its own keeps it trivially previewable and testable: a
 * test can pass a recording `onIntent` and assert that tapping each control
 * emits the matching key. Every control honors a ≥ 48 dp touch target.
 *
 * @param onIntent Called with the [RemoteIntent] produced by a control press.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RemoteScreen(
    onIntent: (RemoteIntent) -> Unit,
    modifier: Modifier = Modifier,
) {
    val press: (RemoteKey) -> Unit = { onIntent(RemoteIntent.PressKey(it)) }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.remote_title)) },
                actions = {
                    IconButton(
                        onClick = { press(KeyPower) },
                        modifier = Modifier
                            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
                            .testTag(RemoteTestTags.POWER)
                            .semantics {
                                contentDescription = "Power"
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
            VolumeChannelRow(onPress = press)
            MediaRow(onPress = press)
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
            tag = RemoteTestTags.DPAD_UP,
            onClick = { onPress(KeyUp) },
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            DirButton(
                label = stringResource(R.string.remote_dpad_left),
                tag = RemoteTestTags.DPAD_LEFT,
                onClick = { onPress(KeyLeft) },
            )
            OkButton(onClick = { onPress(KeyEnter) })
            DirButton(
                label = stringResource(R.string.remote_dpad_right),
                tag = RemoteTestTags.DPAD_RIGHT,
                onClick = { onPress(KeyRight) },
            )
        }
        DirButton(
            label = stringResource(R.string.remote_dpad_down),
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
            tag = RemoteTestTags.RETURN,
            onClick = { onPress(KeyReturn) },
        )
        NavButton(
            label = stringResource(R.string.remote_home),
            tag = RemoteTestTags.HOME,
            onClick = { onPress(KeyHome) },
        )
        NavButton(
            label = stringResource(R.string.remote_menu),
            tag = RemoteTestTags.MENU,
            onClick = { onPress(KeyMenu) },
        )
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
            tag = RemoteTestTags.VOL_DOWN,
            onClick = { onPress(KeyVolDown) },
        )
        NavButton(
            label = stringResource(R.string.remote_mute),
            tag = RemoteTestTags.MUTE,
            onClick = { onPress(KeyMute) },
        )
        NavButton(
            label = stringResource(R.string.remote_vol_up),
            tag = RemoteTestTags.VOL_UP,
            onClick = { onPress(KeyVolUp) },
        )
        NavButton(
            label = stringResource(R.string.remote_ch_down),
            tag = RemoteTestTags.CH_DOWN,
            onClick = { onPress(KeyChDown) },
        )
        NavButton(
            label = stringResource(R.string.remote_ch_up),
            tag = RemoteTestTags.CH_UP,
            onClick = { onPress(KeyChUp) },
        )
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
            tag = RemoteTestTags.REW,
            onClick = { onPress(KeyRew) },
        )
        NavButton(
            label = stringResource(R.string.remote_play),
            tag = RemoteTestTags.PLAY,
            onClick = { onPress(KeyPlay) },
        )
        NavButton(
            label = stringResource(R.string.remote_pause),
            tag = RemoteTestTags.PAUSE,
            onClick = { onPress(KeyPause) },
        )
        NavButton(
            label = stringResource(R.string.remote_stop),
            tag = RemoteTestTags.STOP,
            onClick = { onPress(KeyStop) },
        )
        NavButton(
            label = stringResource(R.string.remote_ff),
            tag = RemoteTestTags.FF,
            onClick = { onPress(KeyFf) },
        )
    }
}

/** A directional (arrow) D-pad button with a ≥ 48 dp touch target. */
@Composable
private fun DirButton(
    label: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    FilledTonalButton(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(tag),
    ) {
        Text(label)
    }
}

/** The center OK / ENTER button. */
@Composable
private fun OkButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Button(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(RemoteTestTags.OK),
    ) {
        Text(stringResource(R.string.remote_ok))
    }
}

/** A secondary navigation button (RETURN / HOME / MENU) with a ≥ 48 dp target. */
@Composable
private fun NavButton(
    label: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier
            .sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)
            .testTag(tag),
    ) {
        Text(label)
    }
}
