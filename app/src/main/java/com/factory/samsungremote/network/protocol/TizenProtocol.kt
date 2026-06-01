package com.factory.samsungremote.network.protocol

import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.util.Base64

/**
 * Serializes/deserializes the JSON messages of the Samsung Tizen remote-control
 * WebSocket protocol.
 *
 * This is the single isolated point that knows the wire format (ADR-0003): the
 * rest of the app deals in [com.factory.samsungremote.data.registry.RemoteKey]
 * codes, app ids and plain text, while this object maps them to/from the exact
 * JSON the TV expects. Keeping the protocol here protects the app from the
 * (undocumented) protocol's future changes.
 *
 * All builders return a compact JSON [String] ready to be written to the socket.
 * Object keys are emitted in a deterministic insertion order so the output is
 * stable and unit-testable.
 */
object TizenProtocol {

    private const val METHOD_REMOTE_CONTROL = "ms.remote.control"
    private const val METHOD_EMIT = "ms.channel.emit"

    private const val TYPE_SEND_KEY = "SendRemoteKey"
    private const val TYPE_SEND_INPUT_STRING = "SendInputString"

    private const val EVENT_APPS_LAUNCH = "ed.apps.launch"

    /**
     * Builds a key-press message (`ms.remote.control` / `SendRemoteKey`).
     *
     * Example for `sendKey("KEY_VOLUP")`:
     * ```json
     * {"method":"ms.remote.control","params":{"Cmd":"Click",
     *  "DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}
     * ```
     *
     * @param keyCode Protocol key code, e.g. `KEY_VOLUP`, `KEY_ENTER`.
     * @param command Click/Press/Release variant; defaults to [TizenCommand.CLICK].
     */
    fun sendKey(keyCode: String, command: TizenCommand = TizenCommand.CLICK): String {
        require(keyCode.isNotEmpty()) { "keyCode must not be empty" }
        val params = orderedJson()
            .put("Cmd", command.wire)
            .put("DataOfCmd", keyCode)
            .put("Option", "false")
            .put("TypeOfRemote", TYPE_SEND_KEY)
        return orderedJson()
            .put("method", METHOD_REMOTE_CONTROL)
            .put("params", params)
            .toString()
    }

    /**
     * Builds an app-launch message (`ms.channel.emit` / `ed.apps.launch`).
     *
     * Example for `launchApp("11101200001")`:
     * ```json
     * {"method":"ms.channel.emit","params":{"event":"ed.apps.launch","to":"host",
     *  "data":{"action_type":"DEEP_LINK","appId":"11101200001"}}}
     * ```
     *
     * @param appId      Tizen application id (e.g. Netflix `11101200001`).
     * @param actionType Launch action; defaults to [LaunchActionType.DEEP_LINK].
     */
    fun launchApp(
        appId: String,
        actionType: LaunchActionType = LaunchActionType.DEEP_LINK,
    ): String {
        require(appId.isNotEmpty()) { "appId must not be empty" }
        val data = orderedJson()
            .put("action_type", actionType.wire)
            .put("appId", appId)
        val params = orderedJson()
            .put("event", EVENT_APPS_LAUNCH)
            .put("to", "host")
            .put("data", data)
        return orderedJson()
            .put("method", METHOD_EMIT)
            .put("params", params)
            .toString()
    }

    /**
     * Builds a text-input message (`ms.remote.control` / `SendInputString`).
     *
     * The TV expects the text Base64-encoded in the `Cmd` field. Example for
     * `sendText("hi")` (`"hi"` → `"aGk="`):
     * ```json
     * {"method":"ms.remote.control","params":{"Cmd":"aGk=",
     *  "DataOfCmd":"base64","TypeOfRemote":"SendInputString"}}
     * ```
     *
     * @param text Plain UTF-8 text to type into the focused field on the TV.
     */
    fun sendText(text: String): String {
        val encoded = Base64.getEncoder()
            .encodeToString(text.toByteArray(StandardCharsets.UTF_8))
        val params = orderedJson()
            .put("Cmd", encoded)
            .put("DataOfCmd", "base64")
            .put("TypeOfRemote", TYPE_SEND_INPUT_STRING)
        return orderedJson()
            .put("method", METHOD_REMOTE_CONTROL)
            .put("params", params)
            .toString()
    }

    /**
     * Parses an incoming message into a [TizenEvent].
     *
     * Reads the top-level `event` name and, when present, the authorization
     * token from `data.token`. Returns `null` if [json] is not a JSON object.
     */
    fun parseEvent(json: String): TizenEvent? {
        val root = json.toJsonObjectOrNull() ?: return null
        val event = root.optString("event", "")
        val token = root.optJSONObject("data")?.let { data ->
            if (data.has("token") && !data.isNull("token")) data.optString("token") else null
        }
        return TizenEvent(event = event, token = token?.takeIf { it.isNotEmpty() })
    }

    /**
     * Extracts the pairing token from a response containing `data.token`.
     *
     * @return the token string, or `null` when absent/blank or when [json] is
     *         not a valid JSON object.
     */
    fun parseToken(json: String): String? = parseEvent(json)?.token

    /** Fresh empty [JSONObject]; [org.json.JSONObject] preserves insertion order. */
    private fun orderedJson(): JSONObject = JSONObject()

    private fun String.toJsonObjectOrNull(): JSONObject? =
        try {
            JSONObject(this)
        } catch (_: Exception) {
            null
        }
}
