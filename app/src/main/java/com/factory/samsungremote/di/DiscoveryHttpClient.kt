package com.factory.samsungremote.di

import javax.inject.Qualifier

/**
 * Qualifies the [okhttp3.OkHttpClient] tuned for LAN discovery (short timeouts),
 * so it is kept distinct from any other OkHttp client the app may provide later
 * (e.g. the long-lived WebSocket client used by the remote session).
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class DiscoveryHttpClient
