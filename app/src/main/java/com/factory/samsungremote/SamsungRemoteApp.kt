package com.factory.samsungremote

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * Application entry point. Annotated with [HiltAndroidApp] so Hilt can generate
 * the application-level dependency container that all other components attach to.
 */
@HiltAndroidApp
class SamsungRemoteApp : Application()
