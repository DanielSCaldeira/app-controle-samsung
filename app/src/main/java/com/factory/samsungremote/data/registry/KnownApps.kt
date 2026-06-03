package com.factory.samsungremote.data.registry

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
 * Curated catalog of popular apps and their candidate ids (BR-focused). Used by the
 * initial-setup probe to discover which apps are installed on a given TV and which
 * id launches each — replacing the `ed.installedApp.get` discovery that 2020+
 * firmwares disable. Add ids here as new models are reported.
 */
object KnownApps {

    val list: List<KnownApp> = listOf(
        KnownApp("Netflix", listOf("3201907018807", "11101200001")),
        KnownApp("YouTube", listOf("111299001912")),
        KnownApp("Prime Video", listOf("3201910019365", "3201512006785")),
        KnownApp("Disney+", listOf("3201901017640", "3202204027038", "3202009021709")),
        KnownApp("Max", listOf("3202301029760", "3201601007230")),
        KnownApp("Globoplay", listOf("3201908019022")),
        KnownApp("Telecine", listOf("3201604009182")),
        KnownApp("Paramount+", listOf("3202110025305", "3201710014981")),
        KnownApp("Apple TV", listOf("3201807016597")),
        KnownApp("Spotify", listOf("3201606009684")),
        KnownApp("YouTube Kids", listOf("3201611010983")),
        KnownApp("Twitch", listOf("3202203026841")),
        KnownApp("Deezer", listOf("3201608010191")),
        KnownApp("Plex", listOf("3201512006963")),
        KnownApp("Pluto TV", listOf("3201808016802")),
    )
}
