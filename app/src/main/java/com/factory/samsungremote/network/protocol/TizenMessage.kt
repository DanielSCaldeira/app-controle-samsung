package com.factory.samsungremote.network.protocol

/**
 * Type of remote-key command understood by the Samsung Tizen WebSocket API.
 *
 * A `Click` is a single press-and-release; `Press`/`Release` model a long press
 * (press then later release the same key).
 *
 * @property wire Exact string sent in the `Cmd` field of a `ms.remote.control`
 *               message.
 */
enum class TizenCommand(val wire: String) {
    /** Single press-and-release of a key. */
    CLICK("Click"),

    /** Begin a long press (key held down). */
    PRESS("Press"),

    /** End a long press (key released). */
    RELEASE("Release"),
}

/**
 * Action used when launching a Tizen application via `ed.apps.launch`.
 *
 * @property wire Exact string sent in the `action_type` field.
 */
enum class LaunchActionType(val wire: String) {
    /** Open the app and navigate to a deep-linked section/content. */
    DEEP_LINK("DEEP_LINK"),

    /** Plain native launch of the application. */
    NATIVE_LAUNCH("NATIVE_LAUNCH"),
}

/**
 * Immutable representation of an event message received from the TV over the
 * WebSocket (e.g. `ms.channel.connect`, `ms.channel.clientConnect`,
 * `ed.installedApp.get`).
 *
 * @property event Name of the event (`event` field of the JSON message). Empty
 *                when the incoming payload carried no event name.
 * @property token Authorization token extracted from `data.token`, when present.
 *                The TV sends this once during the pairing handshake.
 */
data class TizenEvent(
    val event: String,
    val token: String? = null,
)
