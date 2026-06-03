package com.factory.samsungremote.data.favorites

import android.content.SharedPreferences

/**
 * Tiny string key/value persistence seam, so [FavoriteAppsStore] can be unit
 * tested on the JVM with an in-memory fake instead of a real
 * [android.content.SharedPreferences].
 */
interface KeyValueStore {
    /** Returns the stored value for [key], or `null` when absent. */
    fun getString(key: String): String?

    /** Persists [value] under [key]. */
    fun putString(key: String, value: String)
}

/** [KeyValueStore] backed by [SharedPreferences] (production implementation). */
class SharedPrefsKeyValueStore(
    private val prefs: SharedPreferences,
) : KeyValueStore {
    override fun getString(key: String): String? = prefs.getString(key, null)

    override fun putString(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }
}
