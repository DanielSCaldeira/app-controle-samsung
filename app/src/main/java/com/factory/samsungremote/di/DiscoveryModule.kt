package com.factory.samsungremote.di

import android.content.Context
import com.factory.samsungremote.network.discovery.DiscoveryService
import com.factory.samsungremote.network.discovery.MdnsCandidateSource
import com.factory.samsungremote.network.discovery.RestTvCandidateValidator
import com.factory.samsungremote.network.discovery.SsdpCandidateSource
import com.factory.samsungremote.network.discovery.TvCandidateSource
import com.factory.samsungremote.network.discovery.TvCandidateValidator
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Named
import javax.inject.Singleton

/**
 * Hilt wiring for the LAN discovery pipeline.
 *
 * Assembles the [DiscoveryService] from its SSDP and mDNS candidate sources and
 * the OkHttp-backed `/api/v2/` validator. The two [TvCandidateSource]s are
 * distinguished with `@Named` qualifiers so the service can treat SSDP as
 * primary and mDNS as fallback.
 *
 * The OkHttp client here is tuned for discovery: short connect/read timeouts so
 * probing unreachable candidates fails fast and stays within the discovery
 * budget.
 */
@Module
@InstallIn(SingletonComponent::class)
object DiscoveryModule {

    private const val SSDP_SOURCE = "ssdp"
    private const val MDNS_SOURCE = "mdns"

    private const val DISCOVERY_TIMEOUT_SECONDS = 2L

    @Provides
    @Singleton
    @DiscoveryHttpClient
    fun provideDiscoveryHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(DISCOVERY_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(DISCOVERY_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .build()

    @Provides
    @Singleton
    fun provideTvCandidateValidator(
        @DiscoveryHttpClient client: OkHttpClient,
    ): TvCandidateValidator = RestTvCandidateValidator(client)

    @Provides
    @Singleton
    @Named(SSDP_SOURCE)
    fun provideSsdpCandidateSource(): TvCandidateSource = SsdpCandidateSource()

    @Provides
    @Singleton
    @Named(MDNS_SOURCE)
    fun provideMdnsCandidateSource(
        @ApplicationContext context: Context,
    ): TvCandidateSource = MdnsCandidateSource(context)

    @Provides
    @Singleton
    fun provideDiscoveryService(
        @Named(SSDP_SOURCE) ssdpSource: TvCandidateSource,
        @Named(MDNS_SOURCE) mdnsSource: TvCandidateSource,
        validator: TvCandidateValidator,
    ): DiscoveryService = DiscoveryService(
        ssdpSource = ssdpSource,
        mdnsSource = mdnsSource,
        validator = validator,
    )
}
