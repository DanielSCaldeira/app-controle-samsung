package com.factory.samsungremote.network.session

/**
 * Transport seam for sending already-serialized protocol frames to the TV
 * (architecture §2.3, §3 — "UI → ViewModel → Repository → Transport").
 *
 * Domain code (the
 * [com.factory.samsungremote.data.repository.CommandRepository]) maps remote
 * keys, text and app launches to the JSON of the
 * [com.factory.samsungremote.network.protocol.TizenProtocol] layer and writes
 * the resulting frame through this interface. The production implementation is
 * [RemoteSession] (the single live WebSocket); unit tests substitute a fake so
 * the transport is mockable in isolation.
 */
interface CommandTransport {

    /**
     * Writes [frame] (a compact protocol JSON string) to the live connection.
     *
     * @return `true` if the frame was handed to an open socket, `false` when no
     *         connection is currently available (callers may observe
     *         [RemoteSession.state] instead of treating this as a hard error).
     */
    fun send(frame: String): Boolean
}
