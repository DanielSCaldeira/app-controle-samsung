package com.factory.samsungremote.di

import com.factory.samsungremote.data.crypto.KeystoreTokenCipher
import com.factory.samsungremote.data.crypto.TokenCipher
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
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
     * Provides the [TokenCipher] used to encrypt the pairing token before it is
     * persisted. The Keystore-backed implementation needs no external state, so
     * a single application-wide instance is shared.
     */
    @Provides
    @Singleton
    fun provideTokenCipher(): TokenCipher = KeystoreTokenCipher()
}
