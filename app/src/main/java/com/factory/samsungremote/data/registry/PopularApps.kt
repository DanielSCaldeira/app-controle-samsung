package com.factory.samsungremote.data.registry

import com.factory.samsungremote.network.protocol.InstalledApp

/**
 * Pre-detection fallback pick-list shown when the TV does not push its installed
 * apps and the user hasn't run the detection probe yet (ADR-0011). Derived from
 * [KnownApps] (the single source of truth) using each app's most-likely candidate
 * id, so the curated list and the probe never drift apart. Launching goes through
 * the REST endpoint; once the user runs "Detectar apps da TV", the detected list
 * (with ids confirmed for that model) replaces this one.
 */
object PopularApps {

    /** Popular apps as {most-likely id, name}, derived from [KnownApps]. */
    val list: List<InstalledApp> = KnownApps.list.map { app ->
        InstalledApp(appId = app.candidateIds.first(), name = app.name)
    }
}
