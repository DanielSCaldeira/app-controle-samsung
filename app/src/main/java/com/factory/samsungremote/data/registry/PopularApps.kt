package com.factory.samsungremote.data.registry

import com.factory.samsungremote.network.protocol.InstalledApp

/**
 * Curated fallback list of popular streaming apps and their Tizen launch ids,
 * used when the TV does not answer the runtime app-discovery request
 * (`ed.installedApp.get` is disabled on many 2020+ firmwares — see ADR-0011). The
 * user can pin any of these to the home screen; launching goes through the REST
 * endpoint (`POST /api/v2/applications/{appId}`), which works on modern sets.
 *
 * App ids vary by model/year, so some may be wrong for a given TV — a pinned app
 * that does not open just needs its id corrected (as Netflix did, ADR-0010). The
 * list reuses [InstalledApp] so the UI treats curated and discovered apps the same.
 */
object PopularApps {

    /** Popular apps offered as a pick-list, in display order (BR-focused). */
    val list: List<InstalledApp> = listOf(
        InstalledApp(appId = "3201907018807", name = "Netflix"),
        InstalledApp(appId = "111299001912", name = "YouTube"),
        InstalledApp(appId = "3201910019365", name = "Prime Video"),
        InstalledApp(appId = "3201901017640", name = "Disney+"),
        InstalledApp(appId = "3202301029760", name = "Max"),
        InstalledApp(appId = "3201908019022", name = "Globoplay"),
        InstalledApp(appId = "3201604009182", name = "Telecine"),
        InstalledApp(appId = "3202110025305", name = "Paramount+"),
        InstalledApp(appId = "3201807016597", name = "Apple TV"),
        InstalledApp(appId = "3201606009684", name = "Spotify"),
        InstalledApp(appId = "3201611010983", name = "YouTube Kids"),
        InstalledApp(appId = "3202203026841", name = "Twitch"),
        InstalledApp(appId = "3201608010191", name = "Deezer"),
        InstalledApp(appId = "3201512006963", name = "Plex"),
    )
}
