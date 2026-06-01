package com.factory.samsungremote.di

import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

/**
 * Application-scoped Hilt module. Providers for network, persistence and crypto
 * dependencies are added here (and/or in dedicated modules) by later tasks.
 */
@Module
@InstallIn(SingletonComponent::class)
object AppModule
