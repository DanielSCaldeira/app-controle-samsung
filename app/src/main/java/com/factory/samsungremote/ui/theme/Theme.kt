package com.factory.samsungremote.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

/**
 * The remote's branded dark scheme. Dynamic (Material You) color is intentionally
 * **off**: a remote control should look the same on every phone, not inherit the
 * user's wallpaper palette. The layered slate surfaces give depth (background →
 * cards → controls) and the single blue accent keeps the primary action obvious.
 */
private val DarkColorScheme = darkColorScheme(
    primary = Accent,
    onPrimary = OnAccent,
    primaryContainer = AccentPressed,
    onPrimaryContainer = TextPrimary,
    secondary = AccentSoft,
    onSecondary = OnAccent,
    tertiary = AccentSoft,
    background = Background,
    onBackground = TextPrimary,
    surface = Surface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceHigh,
    onSurfaceVariant = TextSecondary,
    surfaceContainer = SurfaceElevated,
    surfaceContainerHigh = SurfaceHigh,
    outline = Outline,
    outlineVariant = Outline,
    error = PowerRed,
    onError = OnPowerRed,
)

private val LightColorScheme = lightColorScheme(
    primary = LightAccent,
    background = LightBackground,
    surface = LightSurface,
)

/**
 * App theme. Defaults to the branded dark scheme regardless of the system
 * setting (a remote reads best dark); [darkTheme] is kept as an override hook and
 * defaults to the system value only when explicitly requested.
 */
@Composable
fun SamsungRemoteTheme(
    darkTheme: Boolean = true,
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme || isSystemInDarkTheme()) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content,
    )
}
