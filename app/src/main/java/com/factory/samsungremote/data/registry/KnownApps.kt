package com.factory.samsungremote.data.registry

import com.factory.samsungremote.network.protocol.InstalledApp

/**
 * A streaming app and the **candidate** Tizen launch ids it is known to use across
 * models/years/regions. App ids change between TV generations (ADR-0010/0011), so
 * the initial setup ([com.factory.samsungremote.viewmodel.RemoteViewModel.runSetup])
 * probes each candidate against the TV (`GET /api/v2/applications/{id}` → 2xx means
 * installed) and keeps the first that exists, so the right id is found per TV.
 *
 * @property name         Display name.
 * @property candidateIds Launch ids to try, most-likely first.
 */
data class KnownApp(
    val name: String,
    val candidateIds: List<String>,
)

/**
 * Curated catalog of popular apps and their candidate ids (BR-focused, global
 * majors) compiled from community id databases. It is the single source of truth
 * for both the initial-setup probe (which id launches each app on a given model)
 * and the pre-detection fallback pick-list ([PopularApps]). Add ids here as new
 * models/apps are reported — while there is no central API, this fixed list is how
 * coverage grows (ADR-0011).
 */
object KnownApps {

    val list: List<KnownApp> = listOf(
        // --- Vídeo / streaming ---
        KnownApp("Netflix", listOf("3201907018807", "11101200001")),
        KnownApp("YouTube", listOf("111299001912")),
        KnownApp("YouTube Kids", listOf("3201611010983")),
        KnownApp("Prime Video", listOf("3201910019365", "3201512006785")),
        KnownApp("Disney+", listOf("3201901017640", "3202204027038", "3202009021709")),
        KnownApp("Max", listOf("3202301029760", "3201601007230", "3201706012478")),
        KnownApp("Apple TV", listOf("3201807016597")),
        KnownApp("Globoplay", listOf("3201908019022")),
        KnownApp("Telecine", listOf("3201604009182")),
        KnownApp("Paramount+", listOf("3202110025305", "3201710014981")),
        KnownApp("Pluto TV", listOf("3201808016802")),
        KnownApp("Tubi", listOf("3201504001965")),
        KnownApp("Discovery+", listOf("3201803015944")),
        KnownApp("DAZN", listOf("3201806016390")),
        KnownApp("Rakuten TV", listOf("3201511006428")),
        KnownApp("NOW", listOf("3201603008746")),
        KnownApp("Plex", listOf("3201512006963")),
        KnownApp("Twitch", listOf("3202203026841")),
        // --- Música ---
        KnownApp("Spotify", listOf("3201606009684")),
        KnownApp("Deezer", listOf("3201608010191")),
        KnownApp("Tidal", listOf("3201805016367")),
        KnownApp("Apple Music", listOf("3201908019041")),
        // --- Outros ---
        KnownApp("Steam Link", listOf("3201702011851")),
    )
}
