package com.factory.samsungremote.ui.theme

import android.content.Context
import android.os.Build
import android.util.Log
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private const val TAG = "SamsungRemoteTheme"

private val DarkColorScheme = darkColorScheme(
    primary = Purple80,
    secondary = PurpleGrey80,
    tertiary = Pink80,
)

private val LightColorScheme = lightColorScheme(
    primary = Purple40,
    secondary = PurpleGrey40,
    tertiary = Pink40,
)

@Composable
fun SamsungRemoteTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // Dynamic color is available on Android 12+.
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val staticScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    val context = LocalContext.current

    val colorScheme = if (dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        // Resolving the Material You palette runs synchronously on the main
        // thread during the very first composition. On some OEM builds
        // (e.g. Android 13+ on Motorola/One UI) this resolution can throw,
        // which would abort the first composition and leave the activity stuck
        // on the system starting window without ever drawing a frame. Falling
        // back to the static scheme guarantees a first frame in that case.
        dynamicColorSchemeOrFallback(context, darkTheme, staticScheme)
    } else {
        staticScheme
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content,
    )
}

/**
 * Resolves the device's dynamic (Material You) [ColorScheme], falling back to
 * [fallback] if dynamic-color resolution fails on this device/OS build.
 *
 * Dynamic color is best-effort decoration; it must never be allowed to break
 * startup. Any failure is swallowed (logged) so the UI always has a usable
 * theme and the first frame can render.
 */
private fun dynamicColorSchemeOrFallback(
    context: Context,
    darkTheme: Boolean,
    fallback: ColorScheme,
): ColorScheme = try {
    if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
} catch (error: Throwable) {
    Log.w(TAG, "Dynamic color unavailable; using static color scheme.", error)
    fallback
}
