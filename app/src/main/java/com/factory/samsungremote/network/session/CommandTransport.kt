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

    /**
     * Launches the Tizen app [appId] on the connected TV.
     *
     * The default simply writes [fallbackFrame] (the legacy `ed.apps.launch`
     * WebSocket emit the caller built via `TizenProtocol`), preserving the
     * original behavior for fakes and older firmware. The production
     * [RemoteSession] overrides this to prefer the REST endpoint
     * (`POST /api/v2/applications/{appId}`), which 2020+ Tizen firmware honors
     * when the WebSocket emit is silently dropped, falling back to
     * [fallbackFrame] only if REST is unavailable (ADR-0010).
     *
     * @param appId         Tizen application id, used by the REST launch.
     * @param fallbackFrame Pre-serialized WebSocket emit to use as the fallback.
     * @return `true` if the launch was handed to a reachable channel.
     */
    fun launchApp(appId: String, fallbackFrame: String): Boolean = send(fallbackFrame)

    /**
     * Types [text] into the focused field on the connected TV.
     *
     * The default writes [fallbackFrame] (the legacy `SendInputString` frame).
     * The production [RemoteSession] overrides this to prefer the REST IME
     * endpoint, falling back to [fallbackFrame] when REST is unavailable
     * (ADR-0010).
     *
     * @param text          Plain text to type, used by the REST IME call.
     * @param fallbackFrame Pre-serialized WebSocket frame to use as the fallback.
     * @return `true` if the text was handed to a reachable channel.
     */
    fun sendText(text: String, fallbackFrame: String): Boolean = send(fallbackFrame)
}
