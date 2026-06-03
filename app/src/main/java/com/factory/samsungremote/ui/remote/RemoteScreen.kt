package com.factory.samsungremote.ui.remote

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Dialpad
import androidx.compose.material.icons.rounded.FastForward
import androidx.compose.material.icons.rounded.FastRewind
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.KeyboardArrowLeft
import androidx.compose.material.icons.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.KeyboardArrowUp
import androidx.compose.material.icons.rounded.Menu
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material.icons.rounded.Remove
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material.icons.rounded.VolumeDown
import androidx.compose.material.icons.rounded.VolumeOff
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.res.stringResource
import androidx.hilt.navigation.compose.hiltViewModel
import kotlinx.coroutines.delay
import com.factory.samsungremote.R
import com.factory.samsungremote.data.registry.AppShortcut
import com.factory.samsungremote.data.registry.AppShortcutCatalog
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.registry.RemoteKeyCatalog
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.protocol.InstalledApp
import com.factory.samsungremote.network.session.ConnectionState
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
    const val KEYPAD_TOGGLE = "remote_keypad_toggle"

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
 * guideline (≥ 48 dp). All controls are sized at or above this floor.
 */
private val MinTouchTarget = 56.dp

/**
 * Debounce window for search-as-you-type: a burst of keystrokes collapses into a
 * single text send once the user pauses, so the TV's focused field stays in sync
 * without one network call per character.
 */
private const val LiveSendDebounceMs = 300L

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
 * `NumericKeys[n]` is the [RemoteKey] for digit `n`.
 */
private val NumericKeys: List<RemoteKey> = (0..9).map { key("KEY_$it") }

/** Key the streaming shortcuts fall back to when a launch reports failure. */
private val FallbackNavKey = key("KEY_HOME")

private fun appShortcut(appId: String): AppShortcut =
    requireNotNull(AppShortcutCatalog.findByAppId(appId)) {
        "Missing app shortcut in catalog: $appId"
    }

private val AppNetflix = appShortcut("3201907018807")
private val AppPrime = appShortcut("3201910019365")
private val AppDisney = appShortcut("3201901017640")
private val AppYouTube = appShortcut("111299001912")

/** Brand accents for the streaming shortcut chips (purely cosmetic). */
private val NetflixColor = Color(0xFFE50914)
private val PrimeColor = Color(0xFF00A8E1)
private val DisneyColor = Color(0xFF113CCF)
private val YouTubeColor = Color(0xFFFF0000)

/** Neutral badge color for discovered apps without a known brand accent. */
private val GenericAppColor = Color(0xFF5B6470)

/**
 * Resolves the app id to launch for a curated [shortcut] against the TV's
 * [installed] app list: prefer an entry whose id already matches, else match by
 * name (exact, then containment), falling back to the catalog id when discovery
 * hasn't run or the app isn't present. This is what makes the curated buttons
 * work across TV models whose ids differ (ADR-0010).
 */
private fun resolveAppId(shortcut: AppShortcut, installed: List<InstalledApp>): String {
    if (installed.isEmpty()) return shortcut.appId
    val match = installed.firstOrNull { it.appId == shortcut.appId }
        ?: installed.firstOrNull { it.name.equals(shortcut.name, ignoreCase = true) }
        ?: installed.firstOrNull {
            it.name.contains(shortcut.name, ignoreCase = true) ||
                shortcut.name.contains(it.name, ignoreCase = true)
        }
    return match?.appId ?: shortcut.appId
}

/** Brand accent for a discovered [app] when its name matches a known service. */
private fun accentFor(app: InstalledApp): Color = when {
    app.name.contains("netflix", ignoreCase = true) -> NetflixColor
    app.name.contains("prime", ignoreCase = true) -> PrimeColor
    app.name.contains("disney", ignoreCase = true) -> DisneyColor
    app.name.contains("youtube", ignoreCase = true) -> YouTubeColor
    else -> GenericAppColor
}

/**
 * Remote-control entry point: binds the [RemoteViewModel] to the stateless
 * [RemoteScreen] and opens the control connection to the chosen TV.
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
    LaunchedEffect(tv.id, token) { viewModel.connect(tv, token) }

    val connectionState by viewModel.connectionState.collectAsState()
    val installedApps by viewModel.installedApps.collectAsState()
    RemoteScreen(
        onIntent = { viewModel.onIntent(it) },
        tvName = tv.name,
        connectionState = connectionState,
        installedApps = installedApps,
        modifier = modifier,
    )
}

/**
 * Stateless remote-control screen. Renders, in a single scrollable column with a
 * clear visual hierarchy: a status header with a POWER toggle, a circular D-pad
 * (the hero control) with the OK center, the RETURN / HOME / MENU navigation row,
 * a text-entry/search row, volume & channel rockers, the media transport bar, the
 * numeric keypad and the streaming app shortcuts — reporting every action as a
 * [RemoteIntent] through [onIntent].
 *
 * Every control carries a stable test tag, a non-empty `contentDescription` for
 * TalkBack, and a ≥ 48 dp touch target. [onIntent] returns whether the resulting
 * frame reached an open connection; the streaming shortcuts use that to fall back
 * to Home navigation when an app fails to launch.
 *
 * @param onIntent        Called with the [RemoteIntent] produced by a control;
 *                        returns `true` when the frame reached an open connection.
 * @param tvName          Name of the connected TV for the header; `null` → generic title.
 * @param connectionState Current session state, surfaced as a colored status dot.
 * @param installedApps   Apps discovered on the connected TV (ADR-0010). Used to
 *                        resolve the curated shortcuts' real app ids and to render
 *                        the "all apps" list; empty until discovery completes.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RemoteScreen(
    onIntent: (RemoteIntent) -> Boolean,
    modifier: Modifier = Modifier,
    tvName: String? = null,
    connectionState: ConnectionState? = null,
    installedApps: List<InstalledApp> = emptyList(),
) {
    val press: (RemoteKey) -> Unit = { onIntent(RemoteIntent.PressKey(it)) }
    val type: (String) -> Unit = { text -> onIntent(RemoteIntent.TypeText(text)) }
    // Launch by a concrete id, falling back to Home navigation when the app can't
    // be launched (e.g. not connected).
    val launchById: (String) -> Unit = { appId ->
        if (!onIntent(RemoteIntent.LaunchApp(appId))) {
            onIntent(RemoteIntent.PressKey(FallbackNavKey))
        }
    }
    // A curated shortcut launches the app id the TV actually reports for it (so the
    // button works on any model), falling back to the catalog id before discovery.
    val launch: (AppShortcut) -> Unit = { shortcut ->
        launchById(resolveAppId(shortcut, installedApps))
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                    titleContentColor = MaterialTheme.colorScheme.onBackground,
                ),
                title = { HeaderTitle(tvName, connectionState) },
                actions = { PowerButton(onClick = { press(KeyPower) }) },
            )
        },
    ) { innerPadding ->
        var panelExpanded by remember { mutableStateOf(false) }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            DPad(onPress = press)
            NavRow(
                onPress = press,
                panelExpanded = panelExpanded,
                onTogglePanel = { panelExpanded = !panelExpanded },
            )
            // Keypad + text entry are used less often, so they stay hidden behind
            // the keypad toggle and expand inline only when asked for.
            AnimatedVisibility(visible = panelExpanded) {
                SectionCard(title = "Keypad & search") {
                    TextEntryRow(onSend = type)
                    Spacer(Modifier.height(4.dp))
                    NumericKeypad(onPress = press)
                }
            }
            VolumeChannelRow(onPress = press)
            SectionCard(title = "Media") { MediaRow(onPress = press) }
            SectionCard(title = "Favoritos") { AppGrid(onLaunch = launch) }
            // Full list of apps the TV reports as installed (ADR-0010); appears once
            // discovery completes so the user can open anything on this TV.
            if (installedApps.isNotEmpty()) {
                SectionCard(title = "Todos os apps da TV") {
                    InstalledAppGrid(apps = installedApps, onLaunch = launchById)
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

/** TV name + a colored connection-status dot in the app bar. */
@Composable
private fun HeaderTitle(tvName: String?, connectionState: ConnectionState?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        if (connectionState != null) {
            val dot = when (connectionState) {
                is ConnectionState.Connected -> Color(0xFF36D399)
                is ConnectionState.Connecting, is ConnectionState.Reconnecting ->
                    MaterialTheme.colorScheme.secondary
                is ConnectionState.Error -> MaterialTheme.colorScheme.error
                is ConnectionState.Disconnected -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            Box(
                Modifier
                    .padding(end = 10.dp)
                    .size(9.dp)
                    .background(dot, CircleShape),
            )
        }
        Text(
            text = tvName ?: stringResource(R.string.remote_title),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

/** Round Power toggle, tinted with the reserved error/red color. */
@Composable
private fun PowerButton(onClick: () -> Unit) {
    val description = stringResource(R.string.remote_cd_power)
    CircleControl(
        icon = Icons.Rounded.PowerSettingsNew,
        contentDescription = description,
        tag = RemoteTestTags.POWER,
        onClick = onClick,
        size = MinTouchTarget,
        container = MaterialTheme.colorScheme.error.copy(alpha = 0.16f),
        content = MaterialTheme.colorScheme.error,
    )
}

/**
 * The directional pad as a single circular control: a layered disc with UP /
 * DOWN / LEFT / RIGHT arrows at the cardinal points and the OK (`KEY_ENTER`)
 * button filling the center — the conventional cross, the way physical remotes
 * and modern remote apps present it.
 */
@Composable
private fun DPad(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    val ring = MaterialTheme.colorScheme.surfaceVariant
    Box(
        modifier = modifier
            .size(268.dp)
            .background(MaterialTheme.colorScheme.surface, CircleShape)
            .padding(6.dp)
            .background(ring, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        ArrowControl(
            icon = Icons.Rounded.KeyboardArrowUp,
            contentDescription = stringResource(R.string.remote_cd_up),
            tag = RemoteTestTags.DPAD_UP,
            onClick = { onPress(KeyUp) },
            modifier = Modifier.align(Alignment.TopCenter),
        )
        ArrowControl(
            icon = Icons.Rounded.KeyboardArrowDown,
            contentDescription = stringResource(R.string.remote_cd_down),
            tag = RemoteTestTags.DPAD_DOWN,
            onClick = { onPress(KeyDown) },
            modifier = Modifier.align(Alignment.BottomCenter),
        )
        ArrowControl(
            icon = Icons.Rounded.KeyboardArrowLeft,
            contentDescription = stringResource(R.string.remote_cd_left),
            tag = RemoteTestTags.DPAD_LEFT,
            onClick = { onPress(KeyLeft) },
            modifier = Modifier.align(Alignment.CenterStart),
        )
        ArrowControl(
            icon = Icons.Rounded.KeyboardArrowRight,
            contentDescription = stringResource(R.string.remote_cd_right),
            tag = RemoteTestTags.DPAD_RIGHT,
            onClick = { onPress(KeyRight) },
            modifier = Modifier.align(Alignment.CenterEnd),
        )
        OkButton(onClick = { onPress(KeyEnter) })
    }
}

/** A transparent arrow hit-area sitting on the D-pad disc (≥ 56 dp). */
@Composable
private fun ArrowControl(
    icon: ImageVector,
    contentDescription: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = contentDescription
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onSurface,
        modifier = modifier
            .size(72.dp)
            .testTag(tag)
            .semantics { this.contentDescription = description },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(34.dp))
        }
    }
}

/** The center OK / ENTER button — a filled accent disc. */
@Composable
private fun OkButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = stringResource(R.string.remote_cd_ok)
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = MaterialTheme.colorScheme.primary,
        contentColor = MaterialTheme.colorScheme.onPrimary,
        modifier = modifier
            .size(104.dp)
            .testTag(RemoteTestTags.OK)
            .semantics { contentDescription = description },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = stringResource(R.string.remote_ok),
                fontWeight = FontWeight.Bold,
                fontSize = 20.sp,
            )
        }
    }
}

/**
 * RETURN / HOME / MENU beneath the D-pad, plus a Keypad toggle that reveals the
 * less-used numeric keypad + text-entry panel on demand.
 */
@Composable
private fun NavRow(
    onPress: (RemoteKey) -> Unit,
    panelExpanded: Boolean,
    onTogglePanel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CircleControl(
            icon = Icons.AutoMirrored.Rounded.ArrowBack,
            contentDescription = stringResource(R.string.remote_cd_return),
            tag = RemoteTestTags.RETURN,
            onClick = { onPress(KeyReturn) },
        )
        CircleControl(
            icon = Icons.Rounded.Home,
            contentDescription = stringResource(R.string.remote_cd_home),
            tag = RemoteTestTags.HOME,
            onClick = { onPress(KeyHome) },
            container = MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
            content = MaterialTheme.colorScheme.primary,
        )
        CircleControl(
            icon = Icons.Rounded.Menu,
            contentDescription = stringResource(R.string.remote_cd_menu),
            tag = RemoteTestTags.MENU,
            onClick = { onPress(KeyMenu) },
        )
        CircleControl(
            icon = Icons.Rounded.Dialpad,
            contentDescription = stringResource(R.string.remote_cd_keypad_toggle),
            tag = RemoteTestTags.KEYPAD_TOGGLE,
            onClick = onTogglePanel,
            container = if (panelExpanded) {
                MaterialTheme.colorScheme.primary
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            },
            content = if (panelExpanded) {
                MaterialTheme.colorScheme.onPrimary
            } else {
                MaterialTheme.colorScheme.onSurface
            },
        )
    }
}

/**
 * Text-entry control: a single-line field plus a Send button for typing into the
 * focused field on the TV. The field holds its own transient text via
 * [rememberSaveable].
 *
 * **Search-as-you-type.** As the user types, the current text is mirrored onto the
 * TV's focused field after a short [LiveSendDebounceMs] pause, so a burst of
 * keystrokes collapses into one send and the TV keeps up live (Samsung's IME input
 * replaces the field contents, so sending the latest full string stays in sync).
 * The Send button remains for an explicit immediate submit, after which the field
 * is cleared. Blank input is ignored.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TextEntryRow(
    onSend: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var text by rememberSaveable { mutableStateOf("") }
    // Mirror keystrokes to the TV after the user pauses; relaunching on each change
    // cancels the prior pending send, which is the debounce.
    LaunchedEffect(text) {
        val current = text
        if (current.isNotBlank()) {
            delay(LiveSendDebounceMs)
            onSend(current)
        }
    }
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
            shape = RoundedCornerShape(16.dp),
            label = { Text(stringResource(R.string.remote_text_label)) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { submit() }),
            modifier = Modifier
                .weight(1f)
                .sizeIn(minHeight = MinTouchTarget)
                .testTag(RemoteTestTags.TEXT_INPUT),
        )
        CircleControl(
            icon = Icons.AutoMirrored.Rounded.Send,
            contentDescription = stringResource(R.string.remote_cd_text_send),
            tag = RemoteTestTags.TEXT_SEND,
            onClick = submit,
            container = MaterialTheme.colorScheme.primary,
            content = MaterialTheme.colorScheme.onPrimary,
        )
    }
}

/**
 * Volume and channel "rockers" side by side: VOL- / MUTE / VOL+ in one pill and
 * CH- / CH+ in another, each emitting the matching [RemoteKey].
 */
@Composable
private fun VolumeChannelRow(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Rocker(
            title = "Volume",
            modifier = Modifier.weight(1f),
        ) {
            FlatControl(
                icon = Icons.Rounded.VolumeDown,
                contentDescription = stringResource(R.string.remote_cd_vol_down),
                tag = RemoteTestTags.VOL_DOWN,
                onClick = { onPress(KeyVolDown) },
            )
            FlatControl(
                icon = Icons.Rounded.VolumeOff,
                contentDescription = stringResource(R.string.remote_cd_mute),
                tag = RemoteTestTags.MUTE,
                onClick = { onPress(KeyMute) },
            )
            FlatControl(
                icon = Icons.Rounded.VolumeUp,
                contentDescription = stringResource(R.string.remote_cd_vol_up),
                tag = RemoteTestTags.VOL_UP,
                onClick = { onPress(KeyVolUp) },
            )
        }
        Rocker(
            title = "Channel",
            modifier = Modifier.weight(1f),
        ) {
            FlatControl(
                icon = Icons.Rounded.Remove,
                contentDescription = stringResource(R.string.remote_cd_ch_down),
                tag = RemoteTestTags.CH_DOWN,
                onClick = { onPress(KeyChDown) },
            )
            FlatControl(
                icon = Icons.Rounded.Add,
                contentDescription = stringResource(R.string.remote_cd_ch_up),
                tag = RemoteTestTags.CH_UP,
                onClick = { onPress(KeyChUp) },
            )
        }
    }
}

/** A rounded "pill" grouping rocker buttons under a small caption. */
@Composable
private fun Rocker(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Caption(title)
        Surface(
            shape = RoundedCornerShape(28.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                content()
            }
        }
    }
}

/**
 * Media transport bar: REW / PLAY / PAUSE / STOP / FF, each emitting the matching
 * [RemoteKey].
 */
@Composable
private fun MediaRow(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FlatControl(
            icon = Icons.Rounded.FastRewind,
            contentDescription = stringResource(R.string.remote_cd_rew),
            tag = RemoteTestTags.REW,
            onClick = { onPress(KeyRew) },
        )
        FlatControl(
            icon = Icons.Rounded.PlayArrow,
            contentDescription = stringResource(R.string.remote_cd_play),
            tag = RemoteTestTags.PLAY,
            onClick = { onPress(KeyPlay) },
            content = MaterialTheme.colorScheme.primary,
        )
        FlatControl(
            icon = Icons.Rounded.Pause,
            contentDescription = stringResource(R.string.remote_cd_pause),
            tag = RemoteTestTags.PAUSE,
            onClick = { onPress(KeyPause) },
        )
        FlatControl(
            icon = Icons.Rounded.Stop,
            contentDescription = stringResource(R.string.remote_cd_stop),
            tag = RemoteTestTags.STOP,
            onClick = { onPress(KeyStop) },
        )
        FlatControl(
            icon = Icons.Rounded.FastForward,
            contentDescription = stringResource(R.string.remote_cd_ff),
            tag = RemoteTestTags.FF,
            onClick = { onPress(KeyFf) },
        )
    }
}

/**
 * Numeric keypad (`KEY_0`..`KEY_9`) for direct channel entry: the conventional
 * 3×3 grid (1–9) with 0 centered beneath.
 */
@Composable
private fun NumericKeypad(
    onPress: (RemoteKey) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        listOf(
            listOf(1, 2, 3),
            listOf(4, 5, 6),
            listOf(7, 8, 9),
            listOf(0),
        ).forEach { rowDigits ->
            Row(
                horizontalArrangement = Arrangement.spacedBy(20.dp),
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
 * Streaming app shortcuts as a 2×2 grid of tiles, each with a brand-colored
 * badge (the app initial) and its name — a cleaner, launcher-style layout than
 * a cramped single row.
 */
@Composable
private fun AppGrid(
    onLaunch: (AppShortcut) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AppTile(
                label = stringResource(R.string.remote_app_netflix),
                initial = "N",
                accent = NetflixColor,
                tag = RemoteTestTags.APP_NETFLIX,
                onClick = { onLaunch(AppNetflix) },
                modifier = Modifier.weight(1f),
            )
            AppTile(
                label = stringResource(R.string.remote_app_prime),
                initial = "P",
                accent = PrimeColor,
                tag = RemoteTestTags.APP_PRIME,
                onClick = { onLaunch(AppPrime) },
                modifier = Modifier.weight(1f),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            AppTile(
                label = stringResource(R.string.remote_app_disney),
                initial = "D",
                accent = DisneyColor,
                tag = RemoteTestTags.APP_DISNEY,
                onClick = { onLaunch(AppDisney) },
                modifier = Modifier.weight(1f),
            )
            AppTile(
                label = stringResource(R.string.remote_app_youtube),
                initial = "Y",
                accent = YouTubeColor,
                tag = RemoteTestTags.APP_YOUTUBE,
                onClick = { onLaunch(AppYouTube) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

/**
 * The full list of apps the TV reported as installed (ADR-0010), laid out as the
 * same launcher-style 2-column grid of [AppTile]s. Each tile launches the app by
 * the id the TV itself reported, so it is always correct for that model. Known
 * brands get their accent ([accentFor]); the rest get a neutral badge.
 */
@Composable
private fun InstalledAppGrid(
    apps: List<InstalledApp>,
    onLaunch: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        apps.chunked(2).forEach { rowApps ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                rowApps.forEach { app ->
                    AppTile(
                        label = app.name,
                        initial = app.name.take(1).uppercase(),
                        accent = accentFor(app),
                        tag = "remote_installed_${app.appId}",
                        onClick = { onLaunch(app.appId) },
                        modifier = Modifier.weight(1f),
                    )
                }
                // Keep a lone trailing tile at half width, aligned with the grid.
                if (rowApps.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

/**
 * Round icon control used across the screen (nav, power, send). Honors the
 * ≥ 48 dp touch target and carries [contentDescription] for TalkBack.
 */
@Composable
private fun CircleControl(
    icon: ImageVector,
    contentDescription: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 60.dp,
    container: Color = MaterialTheme.colorScheme.surfaceVariant,
    content: Color = MaterialTheme.colorScheme.onSurface,
) {
    val description = contentDescription
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = container,
        contentColor = content,
        modifier = modifier
            .size(size)
            .testTag(tag)
            .semantics { this.contentDescription = description },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(26.dp))
        }
    }
}

/**
 * Flat (transparent) icon control used inside the rocker pills and the media bar,
 * so the surrounding pill provides the background. ≥ 56 dp target, TalkBack desc.
 */
@Composable
private fun FlatControl(
    icon: ImageVector,
    contentDescription: String,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    content: Color = MaterialTheme.colorScheme.onSurface,
) {
    val description = contentDescription
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = Color.Transparent,
        contentColor = content,
        modifier = modifier
            .size(MinTouchTarget)
            .testTag(tag)
            .semantics { this.contentDescription = description },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(28.dp))
        }
    }
}

/**
 * A single numeric-keypad button: a circular tonal disc labeled with [digit],
 * tagged with [RemoteTestTags.digit] and carrying a "Digit N" TalkBack
 * description; ≥ 48 dp touch target.
 */
@Composable
private fun DigitButton(
    digit: Int,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = stringResource(R.string.remote_cd_digit, digit)
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurface,
        modifier = modifier
            .size(64.dp)
            .testTag(RemoteTestTags.digit(digit))
            .semantics { contentDescription = description },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(digit.toString(), fontSize = 22.sp, fontWeight = FontWeight.Medium)
        }
    }
}

/**
 * A streaming app tile: a rounded surface with a brand-colored circular badge
 * (the app's [initial]) and its [label]. Carries a "Launch <app>" TalkBack
 * description and a ≥ 48 dp target.
 */
@Composable
private fun AppTile(
    label: String,
    initial: String,
    accent: Color,
    tag: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val description = stringResource(R.string.remote_cd_app_launch, label)
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(18.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        contentColor = MaterialTheme.colorScheme.onSurface,
        modifier = modifier
            .sizeIn(minHeight = 64.dp)
            .testTag(tag)
            .semantics { contentDescription = description },
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .background(accent, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = initial,
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp,
                )
            }
            Spacer(Modifier.width(12.dp))
            Text(
                text = label,
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/**
 * A grouping card with a small caption header, used to separate the keypad,
 * media and apps sections into clear blocks.
 */
@Composable
private fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.surface,
        modifier = modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(Modifier.fillMaxWidth()) { Caption(title) }
            content()
        }
    }
}

/** Small uppercase section caption in the secondary text color. */
@Composable
private fun Caption(text: String) {
    Text(
        text = text.uppercase(),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.5.sp,
    )
}
