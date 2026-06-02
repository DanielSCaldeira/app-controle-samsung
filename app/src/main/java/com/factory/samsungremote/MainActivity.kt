package com.factory.samsungremote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.ui.discovery.DiscoveryRoute
import com.factory.samsungremote.ui.pairing.PairingRoute
import com.factory.samsungremote.ui.remote.RemoteRoute
import com.factory.samsungremote.ui.theme.SamsungRemoteTheme
import dagger.hilt.android.AndroidEntryPoint

/**
 * Single-activity host for the Compose UI. Marked [AndroidEntryPoint] so Hilt can
 * inject dependencies into this activity (and the composables/ViewModels it hosts).
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SamsungRemoteTheme {
                SamsungRemoteNavigation()
            }
        }
    }
}

/**
 * The destinations of the discovery → pairing → remote flow.
 *
 * Modeled as a small sealed hierarchy so the selected [DiscoveredTv] and the
 * pairing token are carried forward to the next screen as part of the navigation
 * state itself (rather than through a side channel). Each screen renders its own
 * [androidx.compose.material3.Scaffold], so the host only swaps the current
 * destination.
 */
private sealed interface Screen {
    /** Initial destination: scan for and choose a TV. */
    data object Discovery : Screen

    /** Pairing handshake for the [tv] picked on discovery. */
    data class Pairing(val tv: DiscoveredTv) : Screen

    /** Live remote control for the paired [tv], authorized with [token]. */
    data class Remote(val tv: DiscoveredTv, val token: String?) : Screen
}

/**
 * Hosts the app's screen flow: discovery (choose a TV) → pairing (accept on the
 * TV) → remote (send commands).
 *
 * The current [Screen] is the navigation state; selecting a TV advances to
 * [Screen.Pairing] carrying that TV, and a successful pairing advances to
 * [Screen.Remote] carrying both the TV and the authorization token. The remote
 * screen replays that token to connect the session so the controls reach the TV.
 */
@Composable
private fun SamsungRemoteNavigation() {
    var screen by remember { mutableStateOf<Screen>(Screen.Discovery) }

    when (val current = screen) {
        Screen.Discovery -> DiscoveryRoute(
            onTvSelected = { tv -> screen = Screen.Pairing(tv) },
        )

        is Screen.Pairing -> PairingRoute(
            tv = current.tv,
            onPaired = { token -> screen = Screen.Remote(current.tv, token) },
        )

        is Screen.Remote -> RemoteRoute(
            tv = current.tv,
            token = current.token,
        )
    }
}
