package com.factory.samsungremote.network.protocol

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Unit tests for the installed-app discovery messages of [TizenProtocol]
 * (`ed.installedApp.get`), which let the remote adapt to each TV's real app ids
 * instead of a fixed catalog (ADR-0010).
 */
class TizenProtocolInstalledAppsTest {

    // --- requestInstalledApps ----------------------------------------------- #
    @Test
    fun requestInstalledApps_buildsChannelEmitForTheEvent() {
        val frame = TizenProtocol.requestInstalledApps()

        val root = JSONObject(frame)
        assertEquals("ms.channel.emit", root.getString("method"))
        val params = root.getJSONObject("params")
        assertEquals("ed.installedApp.get", params.getString("event"))
        assertEquals("host", params.getString("to"))
    }

    // --- parseInstalledApps ------------------------------------------------- #
    @Test
    fun parseInstalledApps_extractsAppsFromDataData() {
        val reply = """
            {"event":"ed.installedApp.get","from":"host","data":{"data":[
              {"appId":"3201907018807","app_type":2,"icon":"/opt/share/n.png","is_lock":0,"name":"Netflix"},
              {"appId":"111299001912","app_type":2,"name":"YouTube"}
            ]}}
        """.trimIndent()

        val apps = TizenProtocol.parseInstalledApps(reply)

        requireNotNull(apps)
        assertEquals(2, apps.size)
        assertEquals("3201907018807", apps[0].appId)
        assertEquals("Netflix", apps[0].name)
        assertEquals(2, apps[0].appType)
        assertEquals("/opt/share/n.png", apps[0].iconPath)
        assertEquals("YouTube", apps[1].name)
        assertNull("icon absent -> null", apps[1].iconPath)
    }

    @Test
    fun parseInstalledApps_skipsEntriesWithoutAppId_andFallsBackName() {
        val reply = """
            {"event":"ed.installedApp.get","data":{"data":[
              {"app_type":2,"name":"NoId"},
              {"appId":"42"}
            ]}}
        """.trimIndent()

        val apps = requireNotNull(TizenProtocol.parseInstalledApps(reply))

        assertEquals("entry without appId is skipped", 1, apps.size)
        assertEquals("42", apps[0].appId)
        assertEquals("name falls back to appId", "42", apps[0].name)
    }

    @Test
    fun parseInstalledApps_returnsEmptyWhenEventHasNoData() {
        val apps = TizenProtocol.parseInstalledApps("""{"event":"ed.installedApp.get"}""")
        assertTrue(requireNotNull(apps).isEmpty())
    }

    @Test
    fun parseInstalledApps_returnsNullForUnrelatedOrInvalidMessages() {
        assertNull(TizenProtocol.parseInstalledApps("""{"event":"ms.channel.connect"}"""))
        assertNull(TizenProtocol.parseInstalledApps("not json"))
    }
}
