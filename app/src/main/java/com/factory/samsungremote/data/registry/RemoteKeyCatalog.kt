package com.factory.samsungremote.data.registry

/**
 * Static catalog of the keys supported by a standard Samsung TV remote control.
 *
 * The catalog is exposed as an immutable list and indexed by [code] for quick
 * lookup. Codes match the values expected by the Samsung remote WebSocket
 * protocol (the `KEY_*` constants).
 */
object RemoteKeyCatalog {

    /** All keys known to the catalog, in display-friendly order. */
    val keys: List<RemoteKey> = listOf(
        // --- Power ---
        RemoteKey("KEY_POWER", KeyCategory.POWER, "Power"),

        // --- Volume ---
        RemoteKey("KEY_VOLUP", KeyCategory.VOLUME, "Volume Up"),
        RemoteKey("KEY_VOLDOWN", KeyCategory.VOLUME, "Volume Down"),
        RemoteKey("KEY_MUTE", KeyCategory.VOLUME, "Mute"),

        // --- Navigation ---
        RemoteKey("KEY_UP", KeyCategory.NAV, "Up"),
        RemoteKey("KEY_DOWN", KeyCategory.NAV, "Down"),
        RemoteKey("KEY_LEFT", KeyCategory.NAV, "Left"),
        RemoteKey("KEY_RIGHT", KeyCategory.NAV, "Right"),
        RemoteKey("KEY_ENTER", KeyCategory.NAV, "Enter"),
        RemoteKey("KEY_HOME", KeyCategory.NAV, "Home"),
        RemoteKey("KEY_RETURN", KeyCategory.NAV, "Return"),
        RemoteKey("KEY_MENU", KeyCategory.NAV, "Menu"),

        // --- Media transport ---
        RemoteKey("KEY_PLAY", KeyCategory.MEDIA, "Play"),
        RemoteKey("KEY_PAUSE", KeyCategory.MEDIA, "Pause"),
        RemoteKey("KEY_STOP", KeyCategory.MEDIA, "Stop"),
        RemoteKey("KEY_REW", KeyCategory.MEDIA, "Rewind"),
        RemoteKey("KEY_FF", KeyCategory.MEDIA, "Fast Forward"),

        // --- Numeric keypad ---
        RemoteKey("KEY_0", KeyCategory.NUMERIC, "0"),
        RemoteKey("KEY_1", KeyCategory.NUMERIC, "1"),
        RemoteKey("KEY_2", KeyCategory.NUMERIC, "2"),
        RemoteKey("KEY_3", KeyCategory.NUMERIC, "3"),
        RemoteKey("KEY_4", KeyCategory.NUMERIC, "4"),
        RemoteKey("KEY_5", KeyCategory.NUMERIC, "5"),
        RemoteKey("KEY_6", KeyCategory.NUMERIC, "6"),
        RemoteKey("KEY_7", KeyCategory.NUMERIC, "7"),
        RemoteKey("KEY_8", KeyCategory.NUMERIC, "8"),
        RemoteKey("KEY_9", KeyCategory.NUMERIC, "9"),

        // --- Shortcuts ---
        RemoteKey("KEY_CHUP", KeyCategory.SHORTCUT, "Channel Up"),
        RemoteKey("KEY_CHDOWN", KeyCategory.SHORTCUT, "Channel Down"),
        RemoteKey("KEY_SOURCE", KeyCategory.SHORTCUT, "Source"),
        RemoteKey("KEY_INFO", KeyCategory.SHORTCUT, "Info"),
    )

    /** Index of every key by its protocol [RemoteKey.code]. */
    private val byCode: Map<String, RemoteKey> = keys.associateBy(RemoteKey::code)

    /** Returns the [RemoteKey] for [code], or `null` if it is not in the catalog. */
    fun findByCode(code: String): RemoteKey? = byCode[code]

    /** Returns all keys belonging to [category]. */
    fun byCategory(category: KeyCategory): List<RemoteKey> =
        keys.filter { it.category == category }
}
