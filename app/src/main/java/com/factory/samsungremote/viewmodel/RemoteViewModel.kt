package com.factory.samsungremote.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.favorites.FavoriteAppsStore
import com.factory.samsungremote.data.registry.KnownApps
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.protocol.InstalledApp
import com.factory.samsungremote.network.session.ConnectionState
import com.factory.samsungremote.network.session.RemoteSession
import com.factory.samsungremote.network.wol.WakeOnLan
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * A user action on the virtual remote, decoupled from how the screen produced it
 * (a tap, a long-press, a typed string).
 *
 * The UI translates a touch into one of these and hands it to
 * [RemoteViewModel.onIntent]; the ViewModel maps each to the matching domain call
 * on [CommandRepository]. Keeping the surface as a single sealed type means new
 * controls (e.g. a touchpad gesture) extend the `when` exhaustively rather than
 * adding ad-hoc methods the screen has to know about.
 */
sealed interface RemoteIntent {

    /** Press a single remote key (navigation, volume, media, numeric, …). */
    data class PressKey(val key: RemoteKey) : RemoteIntent

    /** Type [text] into the focused field on the TV. */
    data class TypeText(val text: String) : RemoteIntent

    /** Launch the Tizen app identified by [appId] (e.g. Netflix `11101200001`). */
    data class LaunchApp(val appId: String) : RemoteIntent
}

/**
 * State of the one-tap "initial setup" that probes which known apps are installed
 * on the connected TV and which id launches each (ADR-0011).
 */
sealed interface SetupState {
    /** Not started yet. */
    data object Idle : SetupState

    /** Probing in progress: [done] of [total] apps checked. */
    data class Running(val done: Int, val total: Int) : SetupState

    /**
     * Finished: [detected] apps (with the id that exists on this TV), [notFound]
     * app names whose candidate ids all returned 404, and the TV [model] (for the
     * not-found report).
     */
    data class Done(
        val detected: List<InstalledApp>,
        val notFound: List<String>,
        val model: String?,
    ) : SetupState
}

/**
 * Drives the virtual-remote screen (architecture §3 — control ViewModel).
 *
 * Two responsibilities, both thin:
 *
 *  - **Touches → commands.** Each [RemoteIntent] the screen emits is mapped to the
 *    matching [CommandRepository] action ([CommandRepository.sendKey] for a key,
 *    [CommandRepository.sendText] for typed input, [CommandRepository.launchApp]
 *    for a deep link). The repository owns the protocol mapping, so this ViewModel
 *    never touches JSON — it only routes intents.
 *  - **Session state → UI.** [connectionState] re-exposes the [RemoteSession]'s
 *    [ConnectionState] (the single source of truth, ADR-0003), so the screen can
 *    render connected / reconnecting / error without owning the connection
 *    lifecycle. Because it is the session's own [StateFlow], every transition the
 *    session makes is reflected to observers with no extra plumbing.
 *
 * [connect]/[disconnect] are thin lifecycle delegations the hosting screen calls
 * when it opens (replaying the pairing token) and leaves; the session serializes
 * them internally so only one socket is ever live.
 *
 * Commands return whether the frame reached an open connection (propagated from
 * the transport), letting the screen react to a not-connected tap without
 * exceptions on the hot control path.
 *
 * @param commandRepository Domain API the intents are routed through; injected so
 *                          tests can drive it with a recording transport.
 * @param session           The live connection whose [ConnectionState] is exposed
 *                          and whose lifecycle [connect]/[disconnect] delegate to.
 * @param wakeOnLan         Wake-on-LAN sender used to power on a fully-off TV when
 *                          a POWER press cannot reach an open connection.
 */
@HiltViewModel
class RemoteViewModel @Inject constructor(
    private val commandRepository: CommandRepository,
    private val session: RemoteSession,
    private val wakeOnLan: WakeOnLan,
    private val favoriteAppsStore: FavoriteAppsStore,
) : ViewModel() {

    /**
     * MAC address of the currently targeted TV (from the persisted
     * [com.factory.samsungremote.data.db.KnownTv.macAddress]), captured on
     * [connect]. Used to send a Wake-on-LAN magic packet when a POWER press finds
     * the session offline. `null` when unknown, in which case WoL is skipped.
     */
    @Volatile
    private var macAddress: String? = null

    /**
     * Observable connection lifecycle the screen renders directly.
     *
     * This is the session's own [StateFlow], so any state change the session makes
     * (Connecting → Connected → Reconnecting → Error → Disconnected) is reflected
     * here without re-collection.
     */
    val connectionState: StateFlow<ConnectionState> = session.state

    /**
     * Apps installed on the connected TV, discovered at runtime (ADR-0010). The
     * screen renders these as the full "all apps" list and uses them to resolve
     * the curated shortcuts' real app ids, so the remote adapts to each TV model
     * instead of relying on hard-coded ids.
     */
    val installedApps: StateFlow<List<InstalledApp>> = session.installedApps

    /**
     * Apps the user pinned to the home screen (ADR-0011), persisted across
     * restarts. The screen renders these under "Meus apps" and offers a pin/unpin
     * toggle on the full app list.
     */
    val favoriteApps: StateFlow<List<InstalledApp>> = favoriteAppsStore.favorites

    /** Pins [app] to the home screen, or unpins it if already pinned. */
    fun toggleFavorite(app: InstalledApp) = favoriteAppsStore.toggle(app)

    /** Asks the TV again for its installed-app list (manual refresh). */
    fun refreshApps() {
        session.refreshInstalledApps()
    }

    private val _setupState = MutableStateFlow<SetupState>(SetupState.Idle)

    /**
     * Progress/result of [runSetup] — the initial app-detection probe the screen
     * renders (button → progress → detected apps + not-found report).
     */
    val setupState: StateFlow<SetupState> = _setupState.asStateFlow()

    /**
     * Detects which [KnownApps] are installed on the connected TV by probing each
     * candidate id over REST ([RemoteSession.isAppInstalled]) and keeping the first
     * that exists, so app ids are correct per model (ADR-0011). Apps whose
     * candidates all fail are reported as not-found (logged with the TV model so
     * missing ids can be added). Re-runnable; ignored while already running.
     */
    fun runSetup() {
        if (_setupState.value is SetupState.Running) return
        viewModelScope.launch {
            val apps = KnownApps.list
            _setupState.value = SetupState.Running(done = 0, total = apps.size)
            val model = session.fetchModel()
            val detected = mutableListOf<InstalledApp>()
            val notFound = mutableListOf<String>()
            apps.forEachIndexed { index, app ->
                var foundId: String? = null
                for (candidate in app.candidateIds) {
                    if (session.isAppInstalled(candidate)) {
                        foundId = candidate
                        break
                    }
                }
                if (foundId != null) {
                    detected.add(InstalledApp(appId = foundId, name = app.name))
                } else {
                    notFound.add(app.name)
                }
                _setupState.value = SetupState.Running(done = index + 1, total = apps.size)
            }
            if (notFound.isNotEmpty()) {
                // Não distinguível por 404: pode ser app ausente OU id desconhecido.
                android.util.Log.w(
                    "SamsungRemote",
                    "Apps não detectados na TV ${model ?: "desconhecida"} " +
                        "(não instalados ou id desconhecido): ${notFound.joinToString()}",
                )
            }
            _setupState.value = SetupState.Done(detected = detected, notFound = notFound, model = model)
        }
    }

    /**
     * Routes a touch-derived [intent] to the matching domain action.
     *
     * When a [RemoteIntent.PressKey] on the POWER key does not reach an open
     * connection (the TV is off / unreachable), this falls back to a Wake-on-LAN
     * broadcast to the last-known [macAddress] so the press still turns the TV on.
     * The WoL send is fire-and-forget on [viewModelScope]; this method still
     * returns the transport result synchronously.
     *
     * @return `true` when the resulting frame reached an open connection, `false`
     *         when no socket is currently connected (propagated from the transport
     *         via [CommandRepository]).
     */
    fun onIntent(intent: RemoteIntent): Boolean {
        val reached = when (intent) {
            is RemoteIntent.PressKey -> commandRepository.sendKey(intent.key)
            is RemoteIntent.TypeText -> commandRepository.sendText(intent.text)
            is RemoteIntent.LaunchApp -> commandRepository.launchApp(intent.appId)
        }
        if (!reached && intent is RemoteIntent.PressKey &&
            intent.key.category == KeyCategory.POWER
        ) {
            attemptWakeOnLan()
        }
        return reached
    }

    /**
     * Fires a Wake-on-LAN magic packet to the current TV's [macAddress] when one
     * is known. No-op (and does not crash the hot control path) when the MAC was
     * never captured.
     */
    private fun attemptWakeOnLan() {
        val mac = macAddress ?: return
        viewModelScope.launch { wakeOnLan.wake(mac) }
    }

    /** Convenience for the common case: press a single [key]. */
    fun pressKey(key: RemoteKey): Boolean = onIntent(RemoteIntent.PressKey(key))

    /**
     * Opens (or re-targets) the control connection to [tv], replaying the pairing
     * [token] so an authorized device is not re-prompted. Observe [connectionState]
     * for progress.
     *
     * [macAddress] (from the persisted
     * [com.factory.samsungremote.data.db.KnownTv.macAddress]) is remembered so a
     * later POWER press can wake the TV over Wake-on-LAN if it is found powered
     * off. Pass `null` when the MAC is unknown — WoL is then simply skipped.
     */
    fun connect(tv: DiscoveredTv, token: String?, macAddress: String? = null) {
        this.macAddress = macAddress
        session.connect(tv, token)
    }

    /** Tears the connection down and stops reconnecting. */
    fun disconnect() = session.disconnect()
}
