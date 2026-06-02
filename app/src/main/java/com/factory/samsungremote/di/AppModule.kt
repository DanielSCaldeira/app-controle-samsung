package com.factory.samsungremote.di

import android.content.Context
import androidx.room.Room
import com.factory.samsungremote.data.crypto.KeystoreTokenCipher
import com.factory.samsungremote.data.crypto.TokenCipher
import com.factory.samsungremote.data.db.AppDatabase
import com.factory.samsungremote.data.db.AppDatabaseMigrations
import com.factory.samsungremote.data.db.KnownTvDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Application-scoped Hilt module. Providers for network, persistence and crypto
 * dependencies are added here (and/or in dedicated modules) by later tasks.
 */
@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    /**
     * Provides the singleton Room database used by the app.
     */
    @Provides
    @Singleton
    fun provideAppDatabase(
        @ApplicationContext context: Context,
    ): AppDatabase = Room.databaseBuilder(
        context,
        AppDatabase::class.java,
        AppDatabase.DATABASE_NAME,
    )
        .addMigrations(*AppDatabaseMigrations.ALL)
        .build()

    /**
     * Provides the DAO used to persist and query known TVs.
     */
    @Provides
    fun provideKnownTvDao(database: AppDatabase): KnownTvDao = database.knownTvDao()

    /**
     * Provides the [TokenCipher] used to encrypt the pairing token before it is
     * persisted. The Keystore-backed implementation needs no external state, so
     * a single application-wide instance is shared.
     */
    @Provides
    @Singleton
    fun provideTokenCipher(): TokenCipher = KeystoreTokenCipher()
}
