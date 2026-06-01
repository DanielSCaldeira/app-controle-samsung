package com.factory.samsungremote.data.registry

/**
 * Logical grouping of a [RemoteKey], used by the UI to lay out the virtual
 * remote and to filter the available commands.
 */
enum class KeyCategory {
    /** Directional / navigation keys (arrows, enter, home, return, menu). */
    NAV,

    /** Media transport keys (play, pause, stop, rewind, fast-forward). */
    MEDIA,

    /** Volume keys (volume up/down, mute). */
    VOLUME,

    /** Power key. */
    POWER,

    /** Numeric keypad (0-9). */
    NUMERIC,

    /** Misc. shortcut keys (channel up/down, source, info). */
    SHORTCUT,
}

/**
 * Immutable description of a single key that can be sent to a Samsung TV.
 *
 * @property code   Protocol key code (e.g. `KEY_VOLUP`) sent over the wire.
 * @property category Logical [KeyCategory] this key belongs to.
 * @property label   Human-readable label for UI display.
 */
data class RemoteKey(
    val code: String,
    val category: KeyCategory,
    val label: String,
)
