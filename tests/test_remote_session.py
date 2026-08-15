"""Tests for task 0d1e3b9a â€” RemoteSession: WebSocket persistente + reconexÃ£o.

Acceptance criteria verified here (behaviourally):
  1. **Envio de tecla gera o frame esperado.** Com a sessÃ£o conectada (via um
     ``WebSocket.Factory`` *fake* no espÃ­rito do ``MockWebServer``), ``sendKey``
     escreve no socket exatamente o JSON ``ms.remote.control`` / ``SendRemoteKey``
     que ``TizenProtocol`` produz.
  2. **Queda de conexÃ£o dispara reconexÃ£o automÃ¡tica** (estado volta a
     ``Connected``) em **< 3 s simulados**: usando tempo *virtual*
     (``TestCoroutineScheduler``) provamos que, apÃ³s um ``onFailure`` no socket
     vivo, o estado passa por ``Reconnecting`` e retorna a ``Connected`` com o
     backoff inicial (500 ms virtuais), bem abaixo do orÃ§amento de 3 s.
  3. **Nenhum socket paralelo Ã© aberto.** A *factory* fake contabiliza sockets
     criados/vivos: o pico de sockets simultÃ¢neos nunca passa de 1, tanto numa
     reconexÃ£o por queda quanto numa reconexÃ£o para um novo alvo (o socket antigo
     Ã© cancelado antes de abrir o novo). ``RemoteSession`` Ã© a Ãºnica fonte de
     verdade da conexÃ£o.

Strategy
--------
Seguindo a convenÃ§Ã£o do repositÃ³rio (executar o **cÃ³digo real** numa JVM desktop
em vez de sÃ³ inspecionar fontes), compilamos os fontes Kotlin reais
(``RemoteSession`` + ``ConnectionState`` + modelos + ``TizenProtocol``) contra:

  * *shims* puros de ``javax.inject`` e ``org.json`` (mesma semÃ¢ntica usada pelo
    serializador, com ``toString()`` compacto e ordem de inserÃ§Ã£o); e
  * ``kotlinx-coroutines-test`` para acionar a sessÃ£o em **tempo virtual**, de
    modo que o backoff/reconexÃ£o Ã© determinÃ­stico e medÃ­vel em milissegundos
    simulados.

A conexÃ£o Ã© dirigida por um ``WebSocket.Factory`` **fake** que captura a URL
montada por ``RemoteSession``, entrega ``onOpen`` para levar a sessÃ£o a
``Connected``, registra os frames enviados e contabiliza sockets vivos â€” o mesmo
ponto de extensÃ£o que o design expÃµe (``socketFactory: WebSocket.Factory``).
Isso exercita o caminho genuÃ­no: loop de manutenÃ§Ã£o -> canal -> StateFlow ->
backoff -> reconexÃ£o.

Se o toolchain Kotlin/JDK ou os jars (okhttp/okio/coroutines/coroutines-test)
nÃ£o forem localizados nos caches do Gradle, os testes comportamentais dÃ£o
``skip``; as asserÃ§Ãµes estruturais sempre rodam.
"""

import base64
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

SESSION_DIR = PKG / "network" / "session"
REMOTE_SESSION_KT = SESSION_DIR / "RemoteSession.kt"
CONNECTION_STATE_KT = SESSION_DIR / "ConnectionState.kt"
# RemoteSession implements CommandTransport, so its source must be compiled too
# (ADR-0010 added overrides for launchApp/sendText on this seam).
COMMAND_TRANSPORT_KT = SESSION_DIR / "CommandTransport.kt"
# ADR-0012: a sessao persiste o token que a TV emite/rotaciona por este seam.
TOKEN_STORE_KT = SESSION_DIR / "TokenStore.kt"

PROTO_DIR = PKG / "network" / "protocol"
TIZEN_PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
TIZEN_MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

REMOTE_KEY_KT = PKG / "data" / "registry" / "RemoteKey.kt"
DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"

REAL_SOURCES = [
    REMOTE_SESSION_KT, CONNECTION_STATE_KT, COMMAND_TRANSPORT_KT, TOKEN_STORE_KT,
    TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT,
    REMOTE_KEY_KT, DISCOVERED_TV_KT,
]

GRADLE_CACHES = Path.home() / ".gradle" / "caches"

APP_NAME = "SamsungRemote"
APP_NAME_B64 = base64.b64encode(APP_NAME.encode("utf-8")).decode("ascii")
CONTROL_PATH = "/api/v2/channels/samsung.remote.control"

EXPECTED_KEY_FRAME = (
    '{"method":"ms.remote.control","params":{"Cmd":"Click",'
    '"DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}'
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
# Harness â€” drives the REAL RemoteSession via a fake socket in virtual time.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.session.ConnectionState
import com.factory.samsungremote.network.session.RemoteSession
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.IOException

fun p(k: String, v: Any?) = println("$k=$v")

fun stateName(s: ConnectionState): String = when (s) {
    is ConnectionState.Disconnected -> "Disconnected"
    is ConnectionState.Connecting -> "Connecting"
    is ConnectionState.Connected -> "Connected"
    is ConnectionState.Reconnecting -> "Reconnecting(" + s.attempt + ")"
    is ConnectionState.Error -> "Error"
}

/** Fake control socket: records frames, reports its own teardown exactly once. */
class FakeWebSocket(
    private val req: Request,
    private val onClose: () -> Unit,
    private val sent: MutableList<String>,
) : WebSocket {
    private var closed = false
    override fun request(): Request = req
    override fun queueSize(): Long = 0L
    override fun send(text: String): Boolean { sent.add(text); return true }
    override fun send(bytes: ByteString): Boolean = true
    override fun close(code: Int, reason: String?): Boolean { markClosed(); return true }
    override fun cancel() { markClosed() }
    private fun markClosed() { if (!closed) { closed = true; onClose() } }
}

/**
 * Captures the handshake URL, auto-opens each socket (so the session reaches
 * Connected) and accounts for sockets created/alive so we can prove no parallel
 * socket is ever opened.
 */
class ControllableFactory : WebSocket.Factory {
    val sent = ArrayList<String>()
    var created = 0
    var live = 0
    var maxLive = 0
    var lastSocket: FakeWebSocket? = null
    var lastListener: WebSocketListener? = null
    var scheme: String? = null
    var host: String? = null
    var port: Int = -1
    var path: String? = null
    var nameParam: String? = null
    var tokenParam: String? = null

    override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket {
        val u = request.url
        scheme = u.scheme; host = u.host; port = u.port; path = u.encodedPath
        nameParam = u.queryParameter("name"); tokenParam = u.queryParameter("token")
        created++
        live++
        if (live > maxLive) maxLive = live
        val ws = FakeWebSocket(request, onClose = { live-- }, sent = sent)
        lastSocket = ws
        lastListener = listener
        val response = Response.Builder()
            .request(request)
            .protocol(Protocol.HTTP_1_1)
            .code(101)
            .message("Switching Protocols")
            .build()
        listener.onOpen(ws, response)
        return ws
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
fun main() {
    val tv = DiscoveredTv("uuid:tv-1", "[TV] Sala", "192.168.0.50", "QN65")
    val volUp = RemoteKey("KEY_VOLUP", KeyCategory.VOLUME, "Vol+")

    // ---- A: key frame on the open socket (+ URL/target shape) ----
    run {
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val factory = ControllableFactory()
        val session = RemoteSession(factory, scope)

        p("A_send_before", session.sendKey(volUp))   // no socket yet -> false

        session.connect(tv, null)
        scheduler.advanceUntilIdle()
        p("A_state_after_connect", stateName(session.state.value))

        p("A_send_ok", session.sendKey(volUp))
        p("A_frame", if (factory.sent.isNotEmpty()) factory.sent[factory.sent.size - 1] else "<none>")
        p("A_scheme", factory.scheme)
        p("A_host", factory.host)
        p("A_port", factory.port)
        p("A_path", factory.path)
        p("A_name", factory.nameParam)
        p("A_token", factory.tokenParam)
        p("A_created", factory.created)
        p("A_maxlive", factory.maxLive)

        session.disconnect()
        scheduler.advanceUntilIdle()
        scope.cancel()
    }

    // ---- B: drop -> automatic reconnection back to Connected in < 3 s ----
    run {
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val factory = ControllableFactory()
        val session = RemoteSession(factory, scope)

        session.connect(tv, null)
        scheduler.advanceUntilIdle()
        p("B_state1", stateName(session.state.value))
        p("B_created_after_connect", factory.created)

        val t0 = scheduler.currentTime
        // Simulate a transport drop on the live socket.
        factory.lastListener!!.onFailure(factory.lastSocket!!, IOException("conn reset"), null)
        scheduler.runCurrent()                       // process failure; stop at backoff delay
        p("B_state_mid", stateName(session.state.value))
        scheduler.advanceUntilIdle()                 // let the backoff elapse + reconnect
        val t1 = scheduler.currentTime
        p("B_state2", stateName(session.state.value))
        p("B_elapsed", t1 - t0)
        p("B_created_total", factory.created)
        p("B_maxlive", factory.maxLive)
        p("B_live_now", factory.live)

        session.disconnect()
        scheduler.advanceUntilIdle()
        scope.cancel()
    }

    // ---- C: reconnecting to a NEW target opens no parallel socket ----
    run {
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val factory = ControllableFactory()
        val session = RemoteSession(factory, scope)

        session.connect(tv, null)
        scheduler.advanceUntilIdle()

        val tv2 = DiscoveredTv("uuid:tv-2", "[TV] Quarto", "192.168.0.77", "QN55")
        session.connect(tv2, "TKN-2")
        scheduler.advanceUntilIdle()
        p("C_state", stateName(session.state.value))
        p("C_host", factory.host)
        p("C_token", factory.tokenParam)
        p("C_created", factory.created)
        p("C_maxlive", factory.maxLive)
        p("C_live_now", factory.live)

        session.disconnect()
        scheduler.advanceUntilIdle()
        p("C_state_disc", stateName(session.state.value))
        p("C_live_after_disc", factory.live)
        scope.cancel()
    }
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_pairing_manager.py).
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
        "corout": _find_jar("kotlinx-coroutines-core-jvm-*.jar"),
        "coroutest": _find_jar("kotlinx-coroutines-test-jvm-*.jar"),
        "okhttp": _find_jar("okhttp-4*.jar", "okhttp-3*.jar", "okhttp-5*.jar"),
        "okio": _find_jar("okio-jvm-*.jar"),
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"], tc["annot"],
        tc["corout"], tc["coroutest"],
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
            pytest.fail(f"fonte da sessÃ£o ausente: {s}")

    tmp = tmp_path_factory.mktemp("session")
    src = tmp / "src"
    (src / "shims").mkdir(parents=True, exist_ok=True)
    (src / "shims" / "inject_shim.kt").write_text(INJECT_SHIM, encoding="utf-8")
    (src / "shims" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    harness = src / "Harness.kt"
    harness.write_text(HARNESS_KT, encoding="utf-8")

    out_dir = tmp / "out"
    out_dir.mkdir(exist_ok=True)

    link_libs = [tc["stdlib"], tc["corout"], tc["coroutest"], tc["okhttp"], tc["okio"]]
    compile_cp = os.pathsep.join(str(p) for p in link_libs)

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
        "compilaÃ§Ã£o da sessÃ£o falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, *link_libs])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execuÃ§Ã£o do harness da sessÃ£o falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_kv(run.stdout)


# --------------------------------------------------------------------------- #
# Criterion 1 â€” sending a key writes the expected frame to the open socket.
# --------------------------------------------------------------------------- #
def test_connect_reaches_connected_state(out):
    assert out.get("A_state_after_connect") == "Connected", f"sessÃ£o nÃ£o conectou: {out!r}"


def test_send_key_writes_expected_frame(out):
    assert out.get("A_send_ok") == "true", "envio deveria ter sucesso com socket aberto"
    assert out.get("A_frame") == EXPECTED_KEY_FRAME, (
        f"frame de tecla inesperado: {out.get('A_frame')!r}"
    )


def test_send_key_before_connect_is_safe_noop(out):
    # Sem socket aberto, sendKey nÃ£o lanÃ§a e sinaliza falha (a UI reage ao state).
    assert out.get("A_send_before") == "false"


def test_control_url_targets_secure_endpoint(out):
    # OkHttp normaliza wss:// -> https:// ao montar a Request; o destino Ã© o mesmo.
    assert out.get("A_scheme") == "https"
    assert out.get("A_host") == "192.168.0.50"
    assert out.get("A_port") == "8002"
    assert out.get("A_path") == CONTROL_PATH


def test_control_url_carries_base64_name(out):
    name = out.get("A_name")
    assert name == APP_NAME_B64, f"name esperado {APP_NAME_B64!r}, veio {name!r}"
    assert base64.b64decode(name).decode("utf-8") == APP_NAME


def test_single_socket_on_first_connect(out):
    assert out.get("A_created") == "1"
    assert out.get("A_maxlive") == "1"


# --------------------------------------------------------------------------- #
# Criterion 2 â€” a dropped link reconnects automatically, back to Connected,
#               in well under 3 simulated seconds.
# --------------------------------------------------------------------------- #
def test_drop_triggers_reconnecting_state(out):
    assert out.get("B_state1") == "Connected"
    assert out.get("B_state_mid", "").startswith("Reconnecting"), (
        f"queda deveria levar a Reconnecting, veio {out.get('B_state_mid')!r}"
    )


def test_reconnects_back_to_connected(out):
    assert out.get("B_state2") == "Connected", "estado nÃ£o voltou a Connected apÃ³s a queda"


def test_reconnection_within_three_simulated_seconds(out):
    elapsed = int(out.get("B_elapsed", "999999"))
    assert 0 < elapsed < 3000, f"reconexÃ£o demorou {elapsed} ms simulados (orÃ§amento < 3000)"


def test_reconnection_opens_a_fresh_socket(out):
    # Um socket no connect inicial, outro na reconexÃ£o.
    assert out.get("B_created_after_connect") == "1"
    assert out.get("B_created_total") == "2"


# --------------------------------------------------------------------------- #
# Criterion 3 â€” no parallel socket is ever open (single source of truth).
# --------------------------------------------------------------------------- #
def test_no_parallel_socket_during_reconnection(out):
    assert out.get("B_maxlive") == "1", "abriu socket paralelo durante a reconexÃ£o"
    assert out.get("B_live_now") == "1", "deveria haver exatamente um socket vivo apÃ³s reconectar"


def test_reconnect_to_new_target_keeps_single_socket(out):
    assert out.get("C_state") == "Connected"
    assert out.get("C_host") == "192.168.0.77", "nÃ£o migrou para o novo alvo"
    assert out.get("C_token") == "TKN-2", "token do novo alvo nÃ£o foi reenviado na URL"
    assert out.get("C_created") == "2", "deveria ter criado exatamente dois sockets no total"
    assert out.get("C_maxlive") == "1", "socket antigo nÃ£o foi fechado antes de abrir o novo"
    assert out.get("C_live_now") == "1"


def test_disconnect_tears_down_the_socket(out):
    assert out.get("C_state_disc") == "Disconnected"
    assert out.get("C_live_after_disc") == "0", "disconnect deixou um socket vivo"


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_session_sources_present():
    for p in (REMOTE_SESSION_KT, CONNECTION_STATE_KT):
        assert p.is_file(), f"fonte ausente: {p}"


def test_connection_state_models_lifecycle():
    text = _read(CONNECTION_STATE_KT)
    assert "sealed interface ConnectionState" in text
    for state in ("Connecting", "Connected", "Reconnecting", "Error", "Disconnected"):
        assert state in text, f"estado de conexÃ£o ausente: {state}"


def test_session_exposes_state_as_stateflow():
    text = _read(REMOTE_SESSION_KT)
    assert "StateFlow<ConnectionState>" in text, "estado deve ser exposto como StateFlow"
    assert "MutableStateFlow" in text


def test_session_opens_secure_control_websocket():
    text = _read(REMOTE_SESSION_KT)
    assert "wss" in text, "deve usar o esquema seguro wss"
    assert "8002" in text, "porta de controle 8002 ausente"
    assert CONTROL_PATH in text, "endpoint de controle samsung.remote.control ausente"
    assert "WebSocket.Factory" in text, "deve abrir via WebSocket.Factory injetÃ¡vel"
    assert "Base64" in text and "encodeToString" in text, "nome deve ser Base64-encoded"


def test_session_sends_keys_via_protocol():
    text = _read(REMOTE_SESSION_KT)
    assert "TizenProtocol.sendKey" in text, "envio de tecla deve usar TizenProtocol.sendKey"
    assert "fun sendKey" in text, "deve expor sendKey"


def test_session_reconnects_with_backoff():
    text = _read(REMOTE_SESSION_KT)
    assert "delay(" in text, "backoff deve usar delay"
    assert "backoff" in text.lower(), "deve haver lÃ³gica de backoff"
    assert "Reconnecting" in text, "deve transitar por Reconnecting"


def test_session_guards_a_single_socket():
    text = _read(REMOTE_SESSION_KT)
    # Uma Ãºnica fonte de verdade: socket atual rastreado + acesso serializado.
    assert "currentSocket" in text, "deve rastrear o socket atual"
    assert "Mutex" in text or "withLock" in text, "mudanÃ§as de conexÃ£o devem ser serializadas"
    assert "cancelAndJoin" in text, "conexÃ£o anterior deve ser cancelada antes de reabrir"
