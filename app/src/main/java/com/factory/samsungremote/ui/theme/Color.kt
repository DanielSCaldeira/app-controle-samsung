package com.factory.samsungremote.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Deliberate, branded palette for the remote — a premium dark "control surface"
 * look (deep navy background, layered slate surfaces, a single bright-blue
 * accent and a warm red reserved for Power), rather than the wallpaper-derived
 * Material You colors. Kept here as named tokens so [SamsungRemoteTheme] and the
 * screens reference intent, not hex.
 */

// Backgrounds & layered surfaces (darkest → most elevated).
val Background = Color(0xFF0B0E14)
val Surface = Color(0xFF12161F)
val SurfaceElevated = Color(0xFF1B212C)
val SurfaceHigh = Color(0xFF252D3A)
val Outline = Color(0xFF333D4D)

// Accent (primary actions, OK, focus) and its on-color.
val Accent = Color(0xFF4DA3FF)
val AccentPressed = Color(0xFF2C7BE5)
val OnAccent = Color(0xFF04101F)

// Secondary accent for subtler highlights (status dot, secondary chips).
val AccentSoft = Color(0xFF8FBCFF)

// Power / destructive.
val PowerRed = Color(0xFFFF5C63)
val OnPowerRed = Color(0xFF2A0608)

// Text.
val TextPrimary = Color(0xFFEAEFF6)
val TextSecondary = Color(0xFFA7B2C2)

// Light scheme fallback (rarely used — the app defaults to dark) kept tasteful.
val LightAccent = Color(0xFF1769D6)
val LightBackground = Color(0xFFF6F8FC)
val LightSurface = Color(0xFFFFFFFF)
