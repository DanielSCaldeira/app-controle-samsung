package com.factory.samsungremote.viewmodel

import androidx.lifecycle.ViewModel
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.session.ConnectionState
import com.factory.samsungremote.network.session.RemoteSession
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.StateFlow
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
 */
@HiltViewModel
class RemoteViewModel @Inject constructor(
    private val commandRepository: CommandRepository,
    private val session: RemoteSession,
) : ViewModel() {

    /**
     * Observable connection lifecycle the screen renders directly.
     *
     * This is the session's own [StateFlow], so any state change the session makes
     * (Connecting → Connected → Reconnecting → Error → Disconnected) is reflected
     * here without re-collection.
     */
    val connectionState: StateFlow<ConnectionState> = session.state

    /**
     * Routes a touch-derived [intent] to the matching domain action.
     *
     * @return `true` when the resulting frame reached an open connection, `false`
     *         when no socket is currently connected (propagated from the transport
     *         via [CommandRepository]).
     */
    fun onIntent(intent: RemoteIntent): Boolean = when (intent) {
        is RemoteIntent.PressKey -> commandRepository.sendKey(intent.key)
        is RemoteIntent.TypeText -> commandRepository.sendText(intent.text)
        is RemoteIntent.LaunchApp -> commandRepository.launchApp(intent.appId)
    }

    /** Convenience for the common case: press a single [key]. */
    fun pressKey(key: RemoteKey): Boolean = onIntent(RemoteIntent.PressKey(key))

    /**
     * Opens (or re-targets) the control connection to [tv], replaying the pairing
     * [token] so an authorized device is not re-prompted. Observe [connectionState]
     * for progress.
     */
    fun connect(tv: DiscoveredTv, token: String?) = session.connect(tv, token)

    /** Tears the connection down and stops reconnecting. */
    fun disconnect() = session.disconnect()
}
