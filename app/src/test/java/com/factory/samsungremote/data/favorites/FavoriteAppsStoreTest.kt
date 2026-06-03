package com.factory.samsungremote.data.favorites

import com.factory.samsungremote.network.protocol.InstalledApp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for [FavoriteAppsStore] (ADR-0011 — pinning apps to the home screen):
 * toggling pins/unpins, the list is observable, and choices persist (a new store
 * over the same [KeyValueStore] reloads them).
 */
class FavoriteAppsStoreTest {

    private class InMemoryKeyValueStore : KeyValueStore {
        val map = mutableMapOf<String, String>()
        override fun getString(key: String): String? = map[key]
        override fun putString(key: String, value: String) { map[key] = value }
    }

    private fun app(id: String, name: String) = InstalledApp(appId = id, name = name)

    @Test
    fun toggle_pinsThenUnpins() {
        val store = FavoriteAppsStore(InMemoryKeyValueStore())
        val netflix = app("3201907018807", "Netflix")

        assertFalse(store.isFavorite(netflix.appId))
        store.toggle(netflix)
        assertTrue(store.isFavorite(netflix.appId))
        assertEquals(listOf(netflix.appId), store.favorites.value.map { it.appId })

        store.toggle(netflix)
        assertFalse(store.isFavorite(netflix.appId))
        assertTrue(store.favorites.value.isEmpty())
    }

    @Test
    fun toggle_keepsInsertionOrder_andIgnoresBlankId() {
        val store = FavoriteAppsStore(InMemoryKeyValueStore())
        store.toggle(app("1", "A"))
        store.toggle(app("2", "B"))
        store.toggle(app("", "blank"))

        assertEquals(listOf("1", "2"), store.favorites.value.map { it.appId })
    }

    @Test
    fun favorites_persistAcrossStoreInstances() {
        val kv = InMemoryKeyValueStore()
        FavoriteAppsStore(kv).toggle(app("111299001912", "YouTube"))

        val reloaded = FavoriteAppsStore(kv)

        assertEquals(1, reloaded.favorites.value.size)
        assertEquals("111299001912", reloaded.favorites.value[0].appId)
        assertEquals("YouTube", reloaded.favorites.value[0].name)
        assertTrue(reloaded.isFavorite("111299001912"))
    }

    @Test
    fun load_toleratesCorruptData() {
        val kv = InMemoryKeyValueStore().apply { map["pinned_apps"] = "not json" }
        assertTrue(FavoriteAppsStore(kv).favorites.value.isEmpty())
    }
}
