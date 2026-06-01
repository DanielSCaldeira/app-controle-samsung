package com.factory.samsungremote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
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
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    PlaceholderScreen(modifier = Modifier.padding(innerPadding))
                }
            }
        }
    }
}

@Composable
private fun PlaceholderScreen(modifier: Modifier = Modifier) {
    Text(
        text = "Samsung Remote",
        modifier = modifier
            .fillMaxSize()
            .wrapContentSize(),
    )
}

@Preview(showBackground = true)
@Composable
private fun PlaceholderScreenPreview() {
    SamsungRemoteTheme {
        PlaceholderScreen()
    }
}
