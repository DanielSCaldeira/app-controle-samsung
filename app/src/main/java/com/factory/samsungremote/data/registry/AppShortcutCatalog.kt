package com.factory.samsungremote.data.registry

/**
 * Static catalog of the Smart TV applications that can be launched as
 * shortcuts from the remote.
 *
 * The catalog is intentionally a single, immutable list ([shortcuts]) so it is
 * trivial to extend: add a new [AppShortcut] entry to the list and it becomes
 * available everywhere. Entries are indexed by [AppShortcut.appId] for quick
 * lookup, and a configurable [fallback] is returned when a requested app is not
 * present in the catalog.
 */
object AppShortcutCatalog {

    /** All applications known to the catalog, in display-friendly order. */
    val shortcuts: List<AppShortcut> = listOf(
        // 2020+ Tizen (validado em campo, QN70Q65DAGXZD/2024): o appId Netflix é
        // 3201907018807; o antigo 11101200001 retorna 404 em /api/v2/applications.
        AppShortcut(appId = "3201907018807", name = "Netflix"),
        AppShortcut(appId = "3201910019365", name = "Prime Video"),
        AppShortcut(appId = "3201901017640", name = "Disney+"),
        AppShortcut(appId = "111299001912", name = "YouTube"),
    )

    /** Index of every shortcut by its Tizen [AppShortcut.appId]. */
    private val byAppId: Map<String, AppShortcut> = shortcuts.associateBy(AppShortcut::appId)

    /**
     * Default shortcut returned by [findByAppIdOrFallback] when the requested
     * app id is unknown. Defaults to the first catalog entry (Netflix) but can
     * be overridden per lookup.
     */
    val fallback: AppShortcut = shortcuts.first()

    /** Returns the [AppShortcut] for [appId], or `null` if it is not in the catalog. */
    fun findByAppId(appId: String): AppShortcut? = byAppId[appId]

    /**
     * Returns the [AppShortcut] for [appId], or [fallbackShortcut] when the id
     * is not present in the catalog. The fallback is configurable per call and
     * defaults to [fallback].
     */
    fun findByAppIdOrFallback(
        appId: String,
        fallbackShortcut: AppShortcut = fallback,
    ): AppShortcut = byAppId[appId] ?: fallbackShortcut

    /** Returns the shortcut matching [name] (case-insensitive), or `null`. */
    fun findByName(name: String): AppShortcut? =
        shortcuts.firstOrNull { it.name.equals(name, ignoreCase = true) }
}
