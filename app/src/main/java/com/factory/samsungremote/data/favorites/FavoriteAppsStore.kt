package com.factory.samsungremote.data.favorites

import com.factory.samsungremote.network.protocol.InstalledApp
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persists the apps the user pinned to the home screen ("Meus apps"), so the
 * choice survives restarts. Apps are pinned from the discovered installed-app
 * list (ADR-0011) and identified by their TV [InstalledApp.appId]; the [name] is
 * stored too so a pinned app still renders before discovery completes.
 *
 * Backed by a [KeyValueStore] (SharedPreferences in production), serialized as a
 * compact JSON array of `{appId,name}`. Exposes the current list as a
 * [StateFlow] the UI observes; mutations write through synchronously and update
 * the flow.
 */
@Singleton
class FavoriteAppsStore @Inject constructor(
    private val store: KeyValueStore,
) {
    private val _favorites = MutableStateFlow(load())

    /** The pinned apps, in insertion order; observed by the remote screen. */
    val favorites: StateFlow<List<InstalledApp>> = _favorites.asStateFlow()

    /** Whether [appId] is currently pinned. */
    fun isFavorite(appId: String): Boolean = _favorites.value.any { it.appId == appId }

    /**
     * Pins [app] if absent, or unpins it if already pinned. No-op for a blank id.
     * Persists the new list and publishes it on [favorites].
     */
    fun toggle(app: InstalledApp) {
        if (app.appId.isEmpty()) return
        val current = _favorites.value
        val next = if (current.any { it.appId == app.appId }) {
            current.filterNot { it.appId == app.appId }
        } else {
            current + InstalledApp(appId = app.appId, name = app.name)
        }
        _favorites.value = next
        store.putString(KEY, serialize(next))
    }

    private fun load(): List<InstalledApp> {
        val raw = store.getString(KEY) ?: return emptyList()
        return try {
            val array = JSONArray(raw)
            (0 until array.length()).mapNotNull { i ->
                val o = array.optJSONObject(i) ?: return@mapNotNull null
                val appId = o.optString("appId").takeIf { it.isNotEmpty() } ?: return@mapNotNull null
                InstalledApp(appId = appId, name = o.optString("name").ifEmpty { appId })
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun serialize(apps: List<InstalledApp>): String {
        val array = JSONArray()
        apps.forEach { app ->
            array.put(JSONObject().put("appId", app.appId).put("name", app.name))
        }
        return array.toString()
    }

    private companion object {
        const val KEY = "pinned_apps"
    }
}
