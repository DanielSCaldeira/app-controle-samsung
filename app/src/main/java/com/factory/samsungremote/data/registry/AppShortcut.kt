package com.factory.samsungremote.data.registry

/**
 * Immutable description of a launchable Smart TV application shortcut.
 *
 * @property appId       Tizen application id used to launch the app on the TV
 *                       (e.g. Netflix is `11101200001`). Must be non-empty.
 * @property name        Human-readable application name for UI display.
 * @property deepLinkKey Optional deep-link / payload key used to open a specific
 *                       section or content inside the app. `null` when the app
 *                       only supports a plain launch.
 */
data class AppShortcut(
    val appId: String,
    val name: String,
    val deepLinkKey: String? = null,
)
