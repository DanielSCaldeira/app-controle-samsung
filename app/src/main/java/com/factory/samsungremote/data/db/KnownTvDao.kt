package com.factory.samsungremote.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * Data-access object for [KnownTv] records.
 *
 * Suspend functions perform one-shot reads/writes; [observeAll] exposes a
 * reactive stream for UI layers that need to react to changes.
 */
@Dao
interface KnownTvDao {

    /**
     * Inserts the TV, replacing any existing row with the same [KnownTv.id].
     * This makes it an idempotent "upsert" keyed on the primary key.
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(tv: KnownTv)

    /** Returns the TV with the given [id], or `null` if none is stored. */
    @Query("SELECT * FROM known_tv WHERE id = :id LIMIT 1")
    suspend fun getById(id: String): KnownTv?

    /** Returns all stored TVs ordered by most-recently-connected first. */
    @Query("SELECT * FROM known_tv ORDER BY last_connected_at DESC")
    suspend fun getAll(): List<KnownTv>

    /** Reactive stream of all stored TVs, ordered by most-recently-connected. */
    @Query("SELECT * FROM known_tv ORDER BY last_connected_at DESC")
    fun observeAll(): Flow<List<KnownTv>>

    /** Deletes the TV with the given [id]. No-op if it does not exist. */
    @Query("DELETE FROM known_tv WHERE id = :id")
    suspend fun delete(id: String)
}
