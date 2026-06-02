package com.factory.samsungremote.data.db

import androidx.room.migration.Migration

/**
 * Registry of Room schema migrations.
 *
 * Version 1 is the initial schema, so there are no migrations yet. When the
 * schema changes, bump [AppDatabase.DATABASE_VERSION], export the new schema,
 * and append a [Migration] (e.g. `MIGRATION_1_2`) to [ALL].
 *
 * Apply them when building the database, e.g.:
 * ```
 * Room.databaseBuilder(context, AppDatabase::class.java, AppDatabase.DATABASE_NAME)
 *     .addMigrations(*AppDatabaseMigrations.ALL)
 *     .build()
 * ```
 */
object AppDatabaseMigrations {

    /** All declared migrations, in ascending version order. */
    val ALL: Array<Migration> = emptyArray()
}
