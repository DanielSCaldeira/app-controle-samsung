package com.factory.samsungremote.data.repository

import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.network.protocol.TizenProtocol
import com.factory.samsungremote.network.session.CommandTransport
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Domain API for controlling the TV (architecture §3 — "CommandRepository").
 *
 * Sits between the ViewModels and the transport: it turns domain actions —
 * pressing a [RemoteKey], typing text, launching an app — into the JSON
 * messages of the [TizenProtocol] layer and writes them through a
 * [CommandTransport] (the live [com.factory.samsungremote.network.session.RemoteSession]
 * in production). The protocol's wire format stays isolated in [TizenProtocol];
 * callers above this layer never see JSON.
 *
 * Every method returns whether the frame reached an open connection so a
 * ViewModel can react (e.g. surface "not connected") without handling
 * exceptions on the hot control path.
 *
 * @param transport The seam frames are written through; mockable in tests.
 */
@Singleton
class CommandRepository @Inject constructor(
    private val transport: CommandTransport,
) {

    /**
     * Sends a single key press (e.g. volume up, navigation, enter).
     *
     * Maps to a `ms.remote.control` / `SendRemoteKey` message built from
     * [RemoteKey.code].
     */
    fun sendKey(key: RemoteKey): Boolean =
        transport.send(TizenProtocol.sendKey(key.code))

    /**
     * Types [text] into the focused field on the TV.
     *
     * Maps to a `ms.remote.control` / `SendInputString` message (the text is
     * Base64-encoded by the protocol layer).
     */
    fun sendText(text: String): Boolean =
        transport.sendText(text, TizenProtocol.sendText(text))

    /**
     * Launches the Tizen app identified by [appId] (e.g. Netflix `11101200001`).
     *
     * Maps to a `ms.channel.emit` / `ed.apps.launch` message.
     */
    fun launchApp(appId: String): Boolean =
        transport.launchApp(appId, TizenProtocol.launchApp(appId))
}
