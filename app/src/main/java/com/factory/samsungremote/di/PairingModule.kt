package com.factory.samsungremote.di

import com.factory.samsungremote.data.registry.TvRegistry
import com.factory.samsungremote.network.pairing.LanTrustManager
import com.factory.samsungremote.network.pairing.PairingManager
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * Hilt wiring for the pairing handshake.
 *
 * Builds the [WebSocket.Factory] the [PairingManager] connects through: an
 * OkHttp client that trusts the TV's self-signed LAN certificate via
 * [LanTrustManager]. A generous read timeout is used because the handshake waits
 * on the user accepting the on-screen authorization prompt on the TV.
 */
@Module
@InstallIn(SingletonComponent::class)
object PairingModule {

    private const val CONNECT_TIMEOUT_SECONDS = 5L

    @Provides
    @Singleton
    @PairingWebSocketClient
    fun providePairingWebSocketClient(): OkHttpClient = LanTrustManager.trustingClient(
        OkHttpClient.Builder()
            .connectTimeout(CONNECT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            // No read timeout: the TV only answers after the user authorizes.
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .build(),
    )

    @Provides
    @Singleton
    fun providePairingManager(
        registry: TvRegistry,
        @PairingWebSocketClient client: OkHttpClient,
    ): PairingManager = PairingManager(
        registry = registry,
        // OkHttpClient implements WebSocket.Factory.
        socketFactory = client,
    )
}
