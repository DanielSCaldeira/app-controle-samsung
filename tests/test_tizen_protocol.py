"""Tests for task d80f0027 â€” Modelo de mensagens do protocolo Tizen.

Acceptance criteria verified here (behaviourally):
  1. sendKey serializes ms.remote.control / SendRemoteKey with Click/Press/Release
     producing the exact expected JSON.
  2. launchApp serializes ms.channel.emit / ed.apps.launch with the expected JSON
     (DEEP_LINK and NATIVE_LAUNCH).
  3. sendText Base64-encodes the text into SendInputString with the expected JSON.
  4. parseEvent / parseToken extract data.token from a TV response, returning the
     correct token (and null when absent / null / not JSON).

Strategy
--------
TizenProtocol is Kotlin and depends on ``org.json`` (provided by Android at
runtime, absent from a desktop JVM). To exercise the *real* protocol code we
compile ``TizenProtocol.kt`` together with a tiny, behaviour-compatible
``org.json`` shim (insertion-ordered objects, compact ``toString()``, JSON null
sentinel â€” identical semantics to Android's org.json for the operations used)
and a small harness, then run it and assert on the produced output.

This mirrors the repository convention (pytest is the test runner) while
genuinely executing the serializer/parser instead of only inspecting sources.

If no Kotlin toolchain can be located in the Gradle caches (or no JDK is
available) the behavioural tests ``skip`` rather than fail; the structural
fallbacks always run.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory"
    / "samsungremote" / "network" / "protocol"
)
PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


# --------------------------------------------------------------------------- #
# Embedded org.json shim + Kotlin harness
# --------------------------------------------------------------------------- #
ORG_JSON_SHIM = r'''package org.json

class JSONException(message: String) : RuntimeException(message)

object NULL { override fun toString(): String = "null" }

private fun escape(s: String): String {
    val sb = StringBuilder()
    for (c in s) {
        when (c) {
            '"' -> sb.append("\\\"")
            '\\' -> sb.append("\\\\")
            '\n' -> sb.append("\\n")
            '\r' -> sb.append("\\r")
            '\t' -> sb.append("\\t")
            else -> sb.append(c)
        }
    }
    return sb.toString()
}

internal fun writeValue(sb: StringBuilder, value: Any?) {
    when (value) {
        null, NULL -> sb.append("null")
        is JSONObject -> sb.append(value.toString())
        is JSONArray -> sb.append(value.toString())
        is String -> sb.append('"').append(escape(value)).append('"')
        is Boolean, is Int, is Long, is Double -> sb.append(value.toString())
        else -> sb.append('"').append(escape(value.toString())).append('"')
    }
}

class JSONArray {
    val items = ArrayList<Any?>()
    fun put(value: Any?): JSONArray { items.add(value); return this }
    fun length(): Int = items.size
    fun optJSONObject(index: Int): JSONObject? = items.getOrNull(index) as? JSONObject
    override fun toString(): String {
        val sb = StringBuilder("[")
        for ((i, v) in items.withIndex()) { if (i > 0) sb.append(','); writeValue(sb, v) }
        sb.append(']'); return sb.toString()
    }
}

class JSONObject {
    private val map = LinkedHashMap<String, Any?>()
    constructor()
    constructor(source: String) {
        val parser = JSONParser(source)
        val v = parser.parseValue()
        parser.skipWhitespace()
        if (!parser.atEnd()) throw JSONException("Unterminated near ${parser.pos}")
        if (v !is JSONObject) throw JSONException("Not a JSON object")
        this.map.putAll(v.map)
    }
    fun put(name: String, value: Any?): JSONObject { map[name] = value; return this }
    fun has(name: String): Boolean = map.containsKey(name)
    fun isNull(name: String): Boolean { val v = map[name]; return v == null || v === NULL }
    fun opt(name: String): Any? = map[name]
    fun optString(name: String, fallback: String = ""): String {
        val v = map[name] ?: return fallback
        if (v === NULL) return fallback
        return v.toString()
    }
    fun optJSONObject(name: String): JSONObject? = map[name] as? JSONObject
    fun optJSONArray(name: String): JSONArray? = map[name] as? JSONArray
    fun optInt(name: String, fallback: Int = 0): Int = (map[name] as? Int) ?: fallback
    internal fun putRaw(name: String, value: Any?) { map[name] = value }
    override fun toString(): String {
        val sb = StringBuilder("{")
        var first = true
        for ((k, v) in map) {
            if (!first) sb.append(','); first = false
            sb.append('"').append(escape(k)).append("\":"); writeValue(sb, v)
        }
        sb.append('}'); return sb.toString()
    }
}

class JSONParser(private val s: String) {
    var pos = 0
    fun atEnd(): Boolean = pos >= s.length
    fun skipWhitespace() { while (pos < s.length && s[pos].isWhitespace()) pos++ }
    fun parseValue(): Any? {
        skipWhitespace()
        if (atEnd()) throw JSONException("Unexpected end of input")
        return when (s[pos]) {
            '{' -> parseObject()
            '[' -> parseArray()
            '"' -> parseString()
            't', 'f' -> parseBoolean()
            'n' -> parseNull()
            else -> parseNumber()
        }
    }
    private fun parseObject(): JSONObject {
        val obj = JSONObject(); pos++; skipWhitespace()
        if (s[pos] == '}') { pos++; return obj }
        while (true) {
            skipWhitespace(); val key = parseString(); skipWhitespace()
            if (s[pos] != ':') throw JSONException("Expected ':' at $pos")
            pos++; val value = parseValue(); obj.putRaw(key, value); skipWhitespace()
            when (s[pos]) {
                ',' -> { pos++; continue }
                '}' -> { pos++; return obj }
                else -> throw JSONException("Expected ',' or '}' at $pos")
            }
        }
    }
    private fun parseArray(): JSONArray {
        val arr = JSONArray(); pos++; skipWhitespace()
        if (s[pos] == ']') { pos++; return arr }
        while (true) {
            arr.put(parseValue()); skipWhitespace()
            when (s[pos]) {
                ',' -> { pos++; continue }
                ']' -> { pos++; return arr }
                else -> throw JSONException("Expected ',' or ']' at $pos")
            }
        }
    }
    private fun parseString(): String {
        if (s[pos] != '"') throw JSONException("Expected string at $pos")
        pos++; val sb = StringBuilder()
        while (pos < s.length) {
            val c = s[pos++]
            when (c) {
                '"' -> return sb.toString()
                '\\' -> {
                    val e = s[pos++]
                    when (e) {
                        '"' -> sb.append('"'); '\\' -> sb.append('\\'); '/' -> sb.append('/')
                        'n' -> sb.append('\n'); 'r' -> sb.append('\r'); 't' -> sb.append('\t')
                        'b' -> sb.append('\b')
                        'u' -> { val hex = s.substring(pos, pos + 4); pos += 4; sb.append(hex.toInt(16).toChar()) }
                        else -> sb.append(e)
                    }
                }
                else -> sb.append(c)
            }
        }
        throw JSONException("Unterminated string")
    }
    private fun parseBoolean(): Boolean = when {
        s.startsWith("true", pos) -> { pos += 4; true }
        s.startsWith("false", pos) -> { pos += 5; false }
        else -> throw JSONException("Invalid literal at $pos")
    }
    private fun parseNull(): Any {
        if (s.startsWith("null", pos)) { pos += 4; return NULL }
        throw JSONException("Invalid literal at $pos")
    }
    private fun parseNumber(): Any {
        val start = pos
        while (pos < s.length && (s[pos].isDigit() || s[pos] in "+-.eE")) pos++
        val token = s.substring(start, pos)
        return token.toLongOrNull() ?: token.toDouble()
    }
}
'''

HARNESS_KT = r'''import com.factory.samsungremote.network.protocol.TizenProtocol
import com.factory.samsungremote.network.protocol.TizenCommand
import com.factory.samsungremote.network.protocol.LaunchActionType

fun main() {
    println("sendKey_click=" + TizenProtocol.sendKey("KEY_VOLUP"))
    println("sendKey_press=" + TizenProtocol.sendKey("KEY_VOLUP", TizenCommand.PRESS))
    println("sendKey_release=" + TizenProtocol.sendKey("KEY_VOLUP", TizenCommand.RELEASE))
    println("launchApp_default=" + TizenProtocol.launchApp("11101200001"))
    println("launchApp_native=" + TizenProtocol.launchApp("3201907018807", LaunchActionType.NATIVE_LAUNCH))
    println("sendText=" + TizenProtocol.sendText("hi"))
    println("sendText_hello=" + TizenProtocol.sendText("Hello, World!"))
    val tokenMsg = """{"event":"ms.channel.connect","data":{"clients":[{"id":"x","isHost":true}],"id":"abc","token":"45784122"}}"""
    println("parseToken=" + TizenProtocol.parseToken(tokenMsg))
    println("parseToken_absent=" + TizenProtocol.parseToken("""{"event":"ms.channel.connect","data":{"id":"abc"}}"""))
    println("parseToken_null=" + TizenProtocol.parseToken("""{"event":"ms.channel.connect","data":{"token":null}}"""))
    println("parseToken_notjson=" + TizenProtocol.parseToken("not-a-json"))
    val ev = TizenProtocol.parseEvent(tokenMsg)
    println("parseEvent_event=" + (ev?.event ?: "<null>"))
    println("parseEvent_token=" + (ev?.token ?: "<null>"))
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery
# --------------------------------------------------------------------------- #
def _java_exe():
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin" / "java")
    candidates.append(Path("C:/Program Files/Android/Android Studio/jbr/bin/java"))
    for c in candidates:
        for exe in (c, c.with_suffix(".exe")):
            if exe.is_file():
                return str(exe)
    from shutil import which
    return which("java")


def _find_jar(*patterns, exclude=("sources", "javadoc")):
    """Return the newest matching jar from the Gradle caches, or None."""
    matches = []
    if not GRADLE_CACHES.is_dir():
        return None
    for pat in patterns:
        for p in GRADLE_CACHES.rglob(pat):
            name = p.name.lower()
            if any(x in name for x in exclude):
                continue
            matches.append(p)
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name)[-1]


def _toolchain():
    java = _java_exe()
    emb = _find_jar("kotlin-compiler-embeddable-*.jar")
    stdlib = _find_jar("kotlin-stdlib-1*.jar", "kotlin-stdlib-2*.jar")
    scrt = _find_jar("kotlin-script-runtime-*.jar")
    refl = _find_jar("kotlin-reflect-*.jar")
    trove = _find_jar("trove4j-*.jar")
    annot = _find_jar("annotations-13*.jar")
    corout = _find_jar("kotlinx-coroutines-core-jvm-*.jar")
    missing = [n for n, v in {
        "java": java, "kotlin-compiler-embeddable": emb, "kotlin-stdlib": stdlib,
        "kotlin-script-runtime": scrt, "kotlin-reflect": refl, "trove4j": trove,
        "annotations": annot, "kotlinx-coroutines": corout,
    }.items() if not v]
    return {
        "java": java, "emb": emb, "stdlib": stdlib, "scrt": scrt, "refl": refl,
        "trove": trove, "annot": annot, "corout": corout, "missing": missing,
    }


def _compile_and_run(tmp_path):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("Kotlin/JDK toolchain unavailable: missing " + ", ".join(tc["missing"]))
    if not PROTOCOL_KT.is_file() or not MESSAGE_KT.is_file():
        pytest.fail(f"fontes do protocolo ausentes em {PROTO_DIR}")

    src = tmp_path / "src"
    (src / "org" / "json").mkdir(parents=True)
    (src / "org" / "json" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    (src / "Harness.kt").write_text(HARNESS_KT, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    sep = os.pathsep
    compiler_cp = sep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"], tc["annot"], tc["corout"],
    ))
    compile_cmd = [
        tc["java"], "-cp", compiler_cp,
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", str(tc["stdlib"]),
        "-d", str(out),
        str(PROTOCOL_KT), str(MESSAGE_KT),
        str(src / "org" / "json" / "json_shim.kt"), str(src / "Harness.kt"),
    ]
    cr = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilaÃ§Ã£o do TizenProtocol falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cmd = [tc["java"], "-cp", sep.join([str(out), str(tc["stdlib"])]), "HarnessKt"]
    rr = subprocess.run(run_cmd, capture_output=True, text=True, timeout=120)
    assert rr.returncode == 0, "execuÃ§Ã£o do harness falhou:\n" + (rr.stdout or "") + (rr.stderr or "")

    result = {}
    for line in rr.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v
    return result


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    return _compile_and_run(tmp_path_factory.mktemp("proto"))


# --------------------------------------------------------------------------- #
# Criterion 1 â€” sendKey (Click / Press / Release)
# --------------------------------------------------------------------------- #
def test_send_key_click(outputs):
    assert outputs["sendKey_click"] == (
        '{"method":"ms.remote.control","params":{"Cmd":"Click",'
        '"DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}'
    )


def test_send_key_press(outputs):
    assert outputs["sendKey_press"] == (
        '{"method":"ms.remote.control","params":{"Cmd":"Press",'
        '"DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}'
    )


def test_send_key_release(outputs):
    assert outputs["sendKey_release"] == (
        '{"method":"ms.remote.control","params":{"Cmd":"Release",'
        '"DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}'
    )


# --------------------------------------------------------------------------- #
# Criterion 2 â€” launchApp (ed.apps.launch)
# --------------------------------------------------------------------------- #
def test_launch_app_deep_link(outputs):
    assert outputs["launchApp_default"] == (
        '{"method":"ms.channel.emit","params":{"event":"ed.apps.launch","to":"host",'
        '"data":{"action_type":"DEEP_LINK","appId":"11101200001"}}}'
    )


def test_launch_app_native(outputs):
    assert outputs["launchApp_native"] == (
        '{"method":"ms.channel.emit","params":{"event":"ed.apps.launch","to":"host",'
        '"data":{"action_type":"NATIVE_LAUNCH","appId":"3201907018807"}}}'
    )


# --------------------------------------------------------------------------- #
# Criterion 3 â€” sendText (Base64 / SendInputString)
# --------------------------------------------------------------------------- #
def test_send_text_base64(outputs):
    # "hi" -> base64 "aGk="
    assert outputs["sendText"] == (
        '{"method":"ms.remote.control","params":{"Cmd":"aGk=",'
        '"DataOfCmd":"base64","TypeOfRemote":"SendInputString"}}'
    )


def test_send_text_base64_longer(outputs):
    # "Hello, World!" -> base64 "SGVsbG8sIFdvcmxkIQ=="
    assert outputs["sendText_hello"] == (
        '{"method":"ms.remote.control","params":{"Cmd":"SGVsbG8sIFdvcmxkIQ==",'
        '"DataOfCmd":"base64","TypeOfRemote":"SendInputString"}}'
    )


# --------------------------------------------------------------------------- #
# Criterion 4 â€” parsing data.token
# --------------------------------------------------------------------------- #
def test_parse_token_happy_path(outputs):
    assert outputs["parseToken"] == "45784122"


def test_parse_token_absent_returns_null(outputs):
    assert outputs["parseToken_absent"] == "null"


def test_parse_token_explicit_null_returns_null(outputs):
    assert outputs["parseToken_null"] == "null"


def test_parse_token_invalid_json_returns_null(outputs):
    assert outputs["parseToken_notjson"] == "null"


def test_parse_event_extracts_event_and_token(outputs):
    assert outputs["parseEvent_event"] == "ms.channel.connect"
    assert outputs["parseEvent_token"] == "45784122"


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required)
# --------------------------------------------------------------------------- #
def test_protocol_sources_present():
    assert PROTOCOL_KT.is_file(), f"TizenProtocol.kt ausente em {PROTO_DIR}"
    assert MESSAGE_KT.is_file(), f"TizenMessage.kt ausente em {PROTO_DIR}"


def test_protocol_declares_expected_api():
    text = PROTOCOL_KT.read_text(encoding="utf-8")
    for fn in ("fun sendKey", "fun launchApp", "fun sendText", "fun parseEvent", "fun parseToken"):
        assert fn in text, f"API ausente em TizenProtocol: {fn}"
    for marker in ("ms.remote.control", "ed.apps.launch", "SendRemoteKey", "SendInputString"):
        assert marker in text, f"marcador de protocolo ausente: {marker}"
