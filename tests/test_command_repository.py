"""Tests for task 4211c776 â€” CommandRepository: API de domÃ­nio.

Acceptance criteria verified here (behaviourally):
  **Teste unitÃ¡rio com RemoteSession mockado confirma que sendKey/launchApp/
  sendText invocam o transporte com a mensagem JSON correta para cada caso.**

``CommandRepository`` depende apenas da costura ``CommandTransport`` (que o
``RemoteSession`` de produÃ§Ã£o implementa â€” ver ``RemoteSession : CommandTransport``).
SubstituÃ­mos o transporte por um *fake* que registra exatamente os frames
recebidos. Assim provamos, sem rede, que:

  * ``sendKey(RemoteKey)``   -> ``ms.remote.control`` / ``SendRemoteKey`` com o
    ``DataOfCmd`` igual ao ``code`` da tecla;
  * ``sendText(String)``     -> ``ms.remote.control`` / ``SendInputString`` com o
    texto Base64-encodado no ``Cmd``;
  * ``launchApp(appId)``     -> ``ms.channel.emit`` / ``ed.apps.launch`` com o
    ``appId`` no ``data``.

E que o repositÃ³rio **propaga** o booleano do transporte (ex.: ``false`` quando
nÃ£o hÃ¡ conexÃ£o) sem engolir o frame.

Strategy
--------
Seguindo a convenÃ§Ã£o do repositÃ³rio (executar o **cÃ³digo real** numa JVM desktop
em vez de sÃ³ inspecionar fontes), compilamos os fontes Kotlin reais
(``CommandRepository`` + ``CommandTransport`` + ``TizenProtocol`` + ``TizenMessage``
+ ``RemoteKey``) contra *shims* puros de ``javax.inject`` e ``org.json`` (mesma
semÃ¢ntica do serializador: ``toString()`` compacto, ordem de inserÃ§Ã£o). O
``java.util.Base64`` usado por ``TizenProtocol.sendText`` Ã© o real da JDK.

Um ``CommandTransport`` *fake* (no papel do ``RemoteSession`` mockado) captura os
frames enviados e o booleano de retorno Ã© controlado por construÃ§Ã£o.

Se o toolchain Kotlin/JDK nÃ£o for localizado nos caches do Gradle, os testes
comportamentais dÃ£o ``skip``; as asserÃ§Ãµes estruturais sempre rodam.
"""

import base64
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

REPO_KT = PKG / "data" / "repository" / "CommandRepository.kt"
TRANSPORT_KT = PKG / "network" / "session" / "CommandTransport.kt"
TIZEN_PROTOCOL_KT = PKG / "network" / "protocol" / "TizenProtocol.kt"
TIZEN_MESSAGE_KT = PKG / "network" / "protocol" / "TizenMessage.kt"
REMOTE_KEY_KT = PKG / "data" / "registry" / "RemoteKey.kt"

REAL_SOURCES = [
    REPO_KT, TRANSPORT_KT, TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT, REMOTE_KEY_KT,
]

GRADLE_CACHES = Path.home() / ".gradle" / "caches"

# ---- Expected wire frames (compact JSON, insertion order). -----------------
EXPECTED_KEY_FRAME = (
    '{"method":"ms.remote.control","params":{"Cmd":"Click",'
    '"DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}'
)

TEXT_INPUT = "hello"
TEXT_B64 = base64.b64encode(TEXT_INPUT.encode("utf-8")).decode("ascii")
EXPECTED_TEXT_FRAME = (
    '{"method":"ms.remote.control","params":{"Cmd":"' + TEXT_B64 + '",'
    '"DataOfCmd":"base64","TypeOfRemote":"SendInputString"}}'
)

APP_ID = "11101200001"
EXPECTED_APP_FRAME = (
    '{"method":"ms.channel.emit","params":{"event":"ed.apps.launch","to":"host",'
    '"data":{"action_type":"DEEP_LINK","appId":"' + APP_ID + '"}}}'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Shims â€” pure annotations + org.json (compact toString, insertion order).
# --------------------------------------------------------------------------- #
INJECT_SHIM = r'''package javax.inject

annotation class Inject
annotation class Singleton
annotation class Qualifier
'''

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

# --------------------------------------------------------------------------- #
# Harness â€” drives the REAL CommandRepository through a fake transport.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.session.CommandTransport

fun p(k: String, v: Any?) = println("$k=$v")

/**
 * Mock transport standing in for the production RemoteSession
 * (which is `RemoteSession : CommandTransport`). Records every frame and
 * returns a configurable boolean so we can exercise the "not connected" path.
 */
class FakeTransport(private val result: Boolean) : CommandTransport {
    val sent = ArrayList<String>()
    override fun send(frame: String): Boolean { sent.add(frame); return result }
}

fun main() {
    // ---- happy path: transport accepts each frame ----
    run {
        val t = FakeTransport(result = true)
        val repo = CommandRepository(t)
        val volUp = RemoteKey("KEY_VOLUP", KeyCategory.VOLUME, "Vol+")

        val rk = repo.sendKey(volUp)
        p("KEY_ret", rk)
        p("KEY_frame", t.sent[t.sent.size - 1])

        val rt = repo.sendText("hello")
        p("TEXT_ret", rt)
        p("TEXT_frame", t.sent[t.sent.size - 1])

        val rl = repo.launchApp("11101200001")
        p("APP_ret", rl)
        p("APP_frame", t.sent[t.sent.size - 1])

        p("TOTAL_count", t.sent.size)
    }

    // ---- edge: transport reports "not connected" -> repository propagates false ----
    run {
        val t = FakeTransport(result = false)
        val repo = CommandRepository(t)
        val volDown = RemoteKey("KEY_VOLDOWN", KeyCategory.VOLUME, "Vol-")

        p("DISC_ret", repo.sendKey(volDown))
        p("DISC_count", t.sent.size)        // frame still forwarded to transport
        p("DISC_frame", t.sent[t.sent.size - 1])
    }
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_remote_session.py).
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
    matches = []
    if not GRADLE_CACHES.is_dir():
        return None
    for pat in patterns:
        for p in GRADLE_CACHES.rglob(pat):
            if any(x in p.name.lower() for x in exclude):
                continue
            matches.append(p)
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name)[-1]


def _toolchain():
    tc = {
        "java": _java_exe(),
        "emb": _find_jar("kotlin-compiler-embeddable-*.jar"),
        "stdlib": _find_jar("kotlin-stdlib-2*.jar", "kotlin-stdlib-1*.jar"),
        "scrt": _find_jar("kotlin-script-runtime-*.jar"),
        "refl": _find_jar("kotlin-reflect-*.jar"),
        "trove": _find_jar("trove4j-*.jar"),
        "annot": _find_jar("annotations-13*.jar"),
        # The kotlin-compiler-embeddable runtime itself needs coroutines on its
        # classpath to start (see test_remote_session.py); CommandRepository
        # does not depend on it directly.
        "corout": _find_jar("kotlinx-coroutines-core-jvm-*.jar"),
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"], tc["annot"],
        tc["corout"],
    ))


def _parse_kv(stdout):
    out = {}
    for line in stdout.splitlines():
        line = line.rstrip("\r")
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v
    return out


# --------------------------------------------------------------------------- #
# Behavioural fixture â€” compile real sources + harness, run once.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def out(tmp_path_factory):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("toolchain/jars indisponÃ­veis: " + ", ".join(tc["missing"]))
    for s in REAL_SOURCES:
        if not s.is_file():
            pytest.fail(f"fonte ausente: {s}")

    tmp = tmp_path_factory.mktemp("cmdrepo")
    src = tmp / "src"
    (src / "shims").mkdir(parents=True, exist_ok=True)
    (src / "shims" / "inject_shim.kt").write_text(INJECT_SHIM, encoding="utf-8")
    (src / "shims" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    harness = src / "Harness.kt"
    harness.write_text(HARNESS_KT, encoding="utf-8")

    out_dir = tmp / "out"
    out_dir.mkdir(exist_ok=True)

    compile_cp = str(tc["stdlib"])

    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", compile_cp,
        "-d", str(out_dir),
        str(src / "shims" / "inject_shim.kt"),
        str(src / "shims" / "json_shim.kt"),
        *[str(s) for s in REAL_SOURCES],
        str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilaÃ§Ã£o do CommandRepository falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, tc["stdlib"]])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execuÃ§Ã£o do harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_kv(run.stdout)


# --------------------------------------------------------------------------- #
# Behavioural â€” each domain call invokes the transport with the right JSON.
# --------------------------------------------------------------------------- #
def test_send_key_invokes_transport_with_correct_json(out):
    assert out.get("KEY_ret") == "true"
    assert out.get("KEY_frame") == EXPECTED_KEY_FRAME, (
        f"frame de tecla inesperado: {out.get('KEY_frame')!r}"
    )


def test_send_text_invokes_transport_with_correct_json(out):
    assert out.get("TEXT_ret") == "true"
    assert out.get("TEXT_frame") == EXPECTED_TEXT_FRAME, (
        f"frame de texto inesperado: {out.get('TEXT_frame')!r}"
    )


def test_launch_app_invokes_transport_with_correct_json(out):
    assert out.get("APP_ret") == "true"
    assert out.get("APP_frame") == EXPECTED_APP_FRAME, (
        f"frame de launch inesperado: {out.get('APP_frame')!r}"
    )


def test_each_call_forwards_exactly_one_frame(out):
    # sendKey + sendText + launchApp = 3 frames no caminho feliz.
    assert out.get("TOTAL_count") == "3"


def test_repository_propagates_transport_failure(out):
    # Sem conexÃ£o, o transporte retorna false; o repositÃ³rio propaga sem engolir.
    assert out.get("DISC_ret") == "false"
    assert out.get("DISC_count") == "1", "o frame deve ser entregue ao transporte mesmo offline"
    assert out.get("DISC_frame", "").startswith('{"method":"ms.remote.control"')


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_sources_present():
    for p in (REPO_KT, TRANSPORT_KT):
        assert p.is_file(), f"fonte ausente: {p}"


def test_repository_exposes_domain_api():
    text = _read(REPO_KT)
    assert "class CommandRepository" in text
    assert "fun sendKey(" in text and "RemoteKey" in text
    assert "fun sendText(" in text
    assert "fun launchApp(" in text


def test_repository_maps_through_protocol_layer():
    text = _read(REPO_KT)
    assert "TizenProtocol.sendKey" in text
    assert "TizenProtocol.sendText" in text
    assert "TizenProtocol.launchApp" in text


def test_repository_writes_via_transport_seam():
    text = _read(REPO_KT)
    assert "CommandTransport" in text, "deve depender da costura de transporte"
    assert "transport.send" in text, "frames devem ser escritos via transport.send"


def test_remote_session_implements_transport():
    text = _read(PKG / "network" / "session" / "RemoteSession.kt")
    assert "CommandTransport" in text, "RemoteSession deve implementar CommandTransport"
