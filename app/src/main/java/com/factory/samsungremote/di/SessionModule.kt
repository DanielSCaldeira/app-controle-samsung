package com.factory.samsungremote.di

import com.factory.samsungremote.network.pairing.LanTrustManager
import com.factory.samsungremote.network.session.CommandTransport
import com.factory.samsungremote.network.session.RemoteSession
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Qualifier
import javax.inject.Singleton

/**
 * Hilt wiring for the runtime [RemoteSession].
 *
 * Provides the OkHttp client the session connects through — trusting the TV's
 * self-signed LAN certificate (via [LanTrustManager]) and pinging periodically so
 * a silently dropped link is noticed and reconnection kicks in — plus the
 * application-scoped [CoroutineScope] the connection loop lives in.
 */
@Module
@InstallIn(SingletonComponent::class)
object SessionModule {

    private const val CONNECT_TIMEOUT_SECONDS = 5L
    private const val PING_INTERVAL_SECONDS = 10L

    /** Qualifies the application-lifetime scope the session's loop runs in. */
    @Qualifier
    @Retention(AnnotationRetention.BINARY)
    annotation class SessionScope

    @Provides
    @Singleton
    @SessionWebSocketClient
    fun provideSessionWebSocketClient(): OkHttpClient = LanTrustManager.trustingClient(
        OkHttpClient.Builder()
            .connectTimeout(CONNECT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            // No read timeout: the session waits indefinitely for TV events.
            .readTimeout(0, TimeUnit.MILLISECONDS)
            // Detect a half-open / dropped link so reconnection can fire.
            .pingInterval(PING_INTERVAL_SECONDS, TimeUnit.SECONDS)
            .build(),
    )

    @Provides
    @Singleton
    @SessionScope
    fun provideSessionScope(): CoroutineScope =
        CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Provides
    @Singleton
    fun provideRemoteSession(
        @SessionWebSocketClient client: OkHttpClient,
        @SessionScope scope: CoroutineScope,
    ): RemoteSession = RemoteSession(
        // OkHttpClient implements WebSocket.Factory.
        socketFactory = client,
        scope = scope,
    )

    /**
     * Exposes the live [RemoteSession] as the [CommandTransport] the domain
     * [com.factory.samsungremote.data.repository.CommandRepository] writes
     * protocol frames through.
     */
    @Provides
    @Singleton
    fun provideCommandTransport(session: RemoteSession): CommandTransport = session
}
