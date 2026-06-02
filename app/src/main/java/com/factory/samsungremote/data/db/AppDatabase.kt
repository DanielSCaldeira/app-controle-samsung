package com.factory.samsungremote.data.db

import androidx.room.Database
import androidx.room.RoomDatabase

/**
 * Room database for the application.
 *
 * Schema versioning: bump [DATABASE_VERSION] and register a [androidx.room.migration.Migration]
 * in [AppDatabaseMigrations] whenever the schema changes. Version 1 is the
 * initial schema and therefore has no migrations.
 */
@Database(
    entities = [KnownTv::class],
    version = AppDatabase.DATABASE_VERSION,
    exportSchema = true,
)
abstract class AppDatabase : RoomDatabase() {

    abstract fun knownTvDao(): KnownTvDao

    companion object {
        const val DATABASE_NAME = "samsung_remote.db"
        const val DATABASE_VERSION = 1
    }
}
