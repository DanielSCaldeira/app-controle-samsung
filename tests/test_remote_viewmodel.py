"""Tests for task 87a57356 â€” RemoteViewModel.

Acceptance criteria verified here (behaviourally):
  1. **Toques â†’ intents â†’ CommandRepository.** Ao receber um intent de tecla
     (``RemoteIntent.PressKey``) o ViewModel chama ``CommandRepository.sendKey``
     com o ``RemoteKey`` correto. Provamos isso compilando o ``RemoteViewModel``
     REAL contra o ``CommandRepository`` REAL ligado a um ``CommandTransport``
     *fake* que grava cada frame: o frame resultante carrega exatamente o
     ``code`` da tecla pressionada (``KEY_VOLUP`` e depois ``KEY_HOME`` â€” provando
     que o mapeamento nÃ£o Ã© hardcoded). Os intents ``TypeText``/``LaunchApp``
     tambÃ©m sÃ£o roteados Ã s chamadas de domÃ­nio correspondentes, e o booleano do
     transporte (ex.: "nÃ£o conectado") Ã© propagado de volta pelo ViewModel.
  2. **Estado da sessÃ£o â†’ StateFlow exposto.** ``RemoteViewModel.connectionState``
     reexpÃµe o ``StateFlow<ConnectionState>`` do ``RemoteSession`` (a Ãºnica fonte
     de verdade, ADR-0003). Dirigindo um ``RemoteSession`` REAL em tempo virtual
     (via um ``WebSocket.Factory`` *fake*), provamos que cada transiÃ§Ã£o da sessÃ£o
     (Disconnected â†’ Connecting/Connected â†’ Reconnecting â†’ Connected â†’
     Disconnected) aparece imediatamente em ``vm.connectionState`` â€” Ã©, de fato,
     o mesmo ``StateFlow``.

Strategy
--------
Seguindo a convenÃ§Ã£o do repositÃ³rio (executar o **cÃ³digo real** numa JVM desktop
em vez de sÃ³ inspecionar fontes), compilamos os fontes Kotlin reais
(``RemoteViewModel`` + ``CommandRepository`` + ``RemoteSession`` + modelos +
``TizenProtocol``) contra:

  * *shims* puros de ``javax.inject``, ``org.json`` (serializador compacto, ordem
    de inserÃ§Ã£o), ``androidx.lifecycle.ViewModel`` e
    ``dagger.hilt.android.lifecycle.HiltViewModel``; e
  * ``kotlinx-coroutines-test`` + ``okhttp``/``okio`` reais, para acionar a sessÃ£o
    em tempo virtual com um socket *fake* (mesmo ponto de extensÃ£o do design:
    ``socketFactory: WebSocket.Factory``).

O critÃ©rio 1 usa um ``CommandTransport`` *fake* (no papel do ``RemoteSession``
mockado) que grava os frames enviados pela cadeia ViewModel â†’ Repository â†’
Transport. O critÃ©rio 2 dirige a sessÃ£o real e observa ``vm.connectionState``.

Se o toolchain Kotlin/JDK ou os jars nÃ£o forem localizados nos caches do Gradle,
os testes comportamentais dÃ£o ``skip``; as asserÃ§Ãµes estruturais sempre rodam.
"""

import base64
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

VIEWMODEL_KT = PKG / "viewmodel" / "RemoteViewModel.kt"

SESSION_DIR = PKG / "network" / "session"
REMOTE_SESSION_KT = SESSION_DIR / "RemoteSession.kt"
# ADR-0012: a sessao persiste o token que a TV emite/rotaciona por este seam.
TOKEN_STORE_KT = SESSION_DIR / "TokenStore.kt"
CONNECTION_STATE_KT = SESSION_DIR / "ConnectionState.kt"
COMMAND_TRANSPORT_KT = SESSION_DIR / "CommandTransport.kt"

PROTO_DIR = PKG / "network" / "protocol"
TIZEN_PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
TIZEN_MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

REPO_KT = PKG / "data" / "repository" / "CommandRepository.kt"
REMOTE_KEY_KT = PKG / "data" / "registry" / "RemoteKey.kt"
DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"

REAL_SOURCES = [
    VIEWMODEL_KT, REPO_KT,
    REMOTE_SESSION_KT, CONNECTION_STATE_KT, COMMAND_TRANSPORT_KT, TOKEN_STORE_KT,
    TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT,
    REMOTE_KEY_KT, DISCOVERED_TV_KT,
]

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---- Expected wire frames (compact JSON, insertion order). -----------------
def _key_frame(code: str) -> str:
    return (
        '{"method":"ms.remote.control","params":{"Cmd":"Click",'
        f'"DataOfCmd":"{code}","Option":"false","TypeOfRemote":"SendRemoteKey"}}}}'
    )


EXPECTED_VOLUP_FRAME = _key_frame("KEY_VOLUP")
EXPECTED_HOME_FRAME = _key_frame("KEY_HOME")

TEXT_INPUT = "hi"
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


# --------------------------------------------------------------------------- #
# Shims â€” pure annotations, org.json, and the Android/Hilt symbols the
# ViewModel links against (it extends ViewModel and is annotated @HiltViewModel,
# but never uses viewModelScope, so a minimal ViewModel stand-in suffices).
# --------------------------------------------------------------------------- #
INJECT_SHIM = r'''package javax.inject

annotation class Inject
annotation class Singleton
annotation class Qualifier
'''

LIFECYCLE_SHIM = r'''package androidx.lifecycle

abstract class ViewModel {
    open fun onCleared() {}
}
'''

HILT_SHIM = r'''package dagger.hilt.android.lifecycle

@Retention(AnnotationRetention.BINARY)
@Target(AnnotationTarget.CLASS)
annotation class HiltViewModel
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
# Harness â€” drives the REAL RemoteViewModel: criterion 1 via a recording
# transport, criterion 2 via a real RemoteSession in virtual time.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.session.CommandTransport
import com.factory.samsungremote.network.session.ConnectionState
import com.factory.samsungremote.network.session.RemoteSession
import com.factory.samsungremote.viewmodel.RemoteIntent
import com.factory.samsungremote.viewmodel.RemoteViewModel
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

/**
 * Mock transport standing in for the production RemoteSession
 * (which is `RemoteSession : CommandTransport`). Records every frame so we can
 * prove the ViewModel routed the intent through CommandRepository with the right
 * payload, and returns a configurable boolean for the "not connected" path.
 */
class FakeTransport(private val result: Boolean) : CommandTransport {
    val sent = ArrayList<String>()
    override fun send(frame: String): Boolean { sent.add(frame); return result }
}

/** Fake control socket: records frames, reports its own teardown exactly once. */
class FakeWebSocket(
    private val req: Request,
    private val onClose: () -> Unit,
) : WebSocket {
    private var closed = false
    override fun request(): Request = req
    override fun queueSize(): Long = 0L
    override fun send(text: String): Boolean = true
    override fun send(bytes: ByteString): Boolean = true
    override fun close(code: Int, reason: String?): Boolean { markClosed(); return true }
    override fun cancel() { markClosed() }
    private fun markClosed() { if (!closed) { closed = true; onClose() } }
}

/** Auto-opens each socket so the real session reaches Connected. */
class ControllableFactory : WebSocket.Factory {
    var lastSocket: FakeWebSocket? = null
    var lastListener: WebSocketListener? = null
    var live = 0

    override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket {
        live++
        val ws = FakeWebSocket(request, onClose = { live-- })
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
    val volUp = RemoteKey("KEY_VOLUP", KeyCategory.VOLUME, "Vol+")
    val home = RemoteKey("KEY_HOME", KeyCategory.NAV, "Home")

    // ---- A: touches -> CommandRepository calls with the right RemoteKey/payload.
    run {
        val t = FakeTransport(result = true)
        val repo = CommandRepository(t)
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val session = RemoteSession(ControllableFactory(), scope)
        val vm = RemoteViewModel(repo, session)

        p("A_key_ret", vm.onIntent(RemoteIntent.PressKey(volUp)))
        p("A_key_frame", t.sent[t.sent.size - 1])

        // A different key must produce a different code -> mapping is not hardcoded.
        p("A_key2_ret", vm.onIntent(RemoteIntent.PressKey(home)))
        p("A_key2_frame", t.sent[t.sent.size - 1])

        // The pressKey() convenience wraps the same PressKey intent.
        p("A_press_ret", vm.pressKey(volUp))
        p("A_press_frame", t.sent[t.sent.size - 1])

        vm.onIntent(RemoteIntent.TypeText("hi"))
        p("A_text_frame", t.sent[t.sent.size - 1])

        vm.onIntent(RemoteIntent.LaunchApp("11101200001"))
        p("A_app_frame", t.sent[t.sent.size - 1])

        p("A_total", t.sent.size)
        scope.cancel()
    }

    // ---- A2: transport reports "not connected" -> ViewModel propagates false.
    run {
        val t = FakeTransport(result = false)
        val repo = CommandRepository(t)
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val session = RemoteSession(ControllableFactory(), scope)
        val vm = RemoteViewModel(repo, session)

        p("A_offline_ret", vm.onIntent(RemoteIntent.PressKey(volUp)))
        p("A_offline_count", t.sent.size)        // frame still forwarded
        p("A_offline_frame", t.sent[t.sent.size - 1])
        scope.cancel()
    }

    // ---- B: RemoteSession state changes reflect in vm.connectionState.
    run {
        val tv = DiscoveredTv("uuid:tv-1", "[TV] Sala", "192.168.0.50", "QN65")
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val factory = ControllableFactory()
        val session = RemoteSession(factory, scope)
        val vm = RemoteViewModel(CommandRepository(FakeTransport(true)), session)

        // It is literally the session's own StateFlow (single source of truth).
        p("B_same_instance", vm.connectionState === session.state)
        p("B_initial", stateName(vm.connectionState.value))

        vm.connect(tv, "TKN")
        scheduler.advanceUntilIdle()
        p("B_after_connect", stateName(vm.connectionState.value))

        // Drop the live socket -> session transitions through Reconnecting.
        factory.lastListener!!.onFailure(factory.lastSocket!!, IOException("reset"), null)
        scheduler.runCurrent()
        p("B_after_drop", stateName(vm.connectionState.value))

        scheduler.advanceUntilIdle()
        p("B_after_recover", stateName(vm.connectionState.value))

        vm.disconnect()
        scheduler.advanceUntilIdle()
        p("B_after_disconnect", stateName(vm.connectionState.value))
        scope.cancel()
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
            pytest.fail(f"fonte ausente: {s}")

    tmp = tmp_path_factory.mktemp("remote_vm")
    src = tmp / "src"
    (src / "shims").mkdir(parents=True, exist_ok=True)
    (src / "shims" / "inject_shim.kt").write_text(INJECT_SHIM, encoding="utf-8")
    (src / "shims" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    (src / "shims" / "lifecycle_shim.kt").write_text(LIFECYCLE_SHIM, encoding="utf-8")
    (src / "shims" / "hilt_shim.kt").write_text(HILT_SHIM, encoding="utf-8")
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
        str(src / "shims" / "lifecycle_shim.kt"),
        str(src / "shims" / "hilt_shim.kt"),
        *[str(s) for s in REAL_SOURCES],
        str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilaÃ§Ã£o do RemoteViewModel harness falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, *link_libs])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execuÃ§Ã£o do harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_kv(run.stdout)


# --------------------------------------------------------------------------- #
# Criterion 1 â€” a key intent calls CommandRepository.sendKey with the right key.
# --------------------------------------------------------------------------- #
def test_key_intent_routes_to_send_key_with_correct_key(out):
    assert out.get("A_key_ret") == "true"
    assert out.get("A_key_frame") == EXPECTED_VOLUP_FRAME, (
        f"intent de tecla nÃ£o roteou o RemoteKey correto: {out.get('A_key_frame')!r}"
    )


def test_key_mapping_is_not_hardcoded(out):
    # Outra tecla deve produzir outro code â€” prova que o ViewModel encaminha o
    # RemoteKey recebido, e nÃ£o um valor fixo.
    assert out.get("A_key2_frame") == EXPECTED_HOME_FRAME, (
        f"segunda tecla nÃ£o roteou KEY_HOME: {out.get('A_key2_frame')!r}"
    )
    assert out.get("A_key_frame") != out.get("A_key2_frame")


def test_press_key_convenience_routes_same_as_intent(out):
    assert out.get("A_press_ret") == "true"
    assert out.get("A_press_frame") == EXPECTED_VOLUP_FRAME


def test_type_text_intent_routes_to_send_text(out):
    assert out.get("A_text_frame") == EXPECTED_TEXT_FRAME, (
        f"intent de texto nÃ£o roteou sendText: {out.get('A_text_frame')!r}"
    )


def test_launch_app_intent_routes_to_launch_app(out):
    assert out.get("A_app_frame") == EXPECTED_APP_FRAME, (
        f"intent de app nÃ£o roteou launchApp: {out.get('A_app_frame')!r}"
    )


def test_each_intent_forwards_exactly_one_frame(out):
    # PressKey + PressKey + pressKey + TypeText + LaunchApp = 5 frames.
    assert out.get("A_total") == "5"


def test_viewmodel_propagates_not_connected_result(out):
    # Transporte offline -> repository retorna false -> ViewModel propaga false,
    # mas o frame ainda Ã© entregue (sem exceÃ§Ã£o no caminho de controle).
    assert out.get("A_offline_ret") == "false"
    assert out.get("A_offline_count") == "1"
    assert out.get("A_offline_frame") == EXPECTED_VOLUP_FRAME


# --------------------------------------------------------------------------- #
# Criterion 2 â€” session state changes are reflected in the exposed StateFlow.
# --------------------------------------------------------------------------- #
def test_connection_state_is_the_session_stateflow(out):
    assert out.get("B_same_instance") == "true", (
        "connectionState deve ser o prÃ³prio StateFlow do RemoteSession"
    )


def test_initial_state_reflects_disconnected(out):
    assert out.get("B_initial") == "Disconnected"


def test_connect_reflects_connected_state(out):
    assert out.get("B_after_connect") == "Connected", (
        f"conexÃ£o nÃ£o refletiu Connected no StateFlow exposto: {out!r}"
    )


def test_drop_reflects_reconnecting_state(out):
    assert out.get("B_after_drop", "").startswith("Reconnecting"), (
        f"queda nÃ£o refletiu Reconnecting: {out.get('B_after_drop')!r}"
    )


def test_recovery_reflects_connected_again(out):
    assert out.get("B_after_recover") == "Connected"


def test_disconnect_reflects_disconnected_state(out):
    assert out.get("B_after_disconnect") == "Disconnected"


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_sources_present():
    assert VIEWMODEL_KT.is_file(), f"RemoteViewModel ausente: {VIEWMODEL_KT}"


def test_viewmodel_is_hilt_viewmodel_with_injected_deps():
    text = _read(VIEWMODEL_KT)
    assert "@HiltViewModel" in text, "ViewModel deve ser um @HiltViewModel"
    assert "@Inject constructor" in text, "deve receber dependÃªncias via @Inject"
    assert "commandRepository: CommandRepository" in text
    assert "session: RemoteSession" in text


def test_viewmodel_maps_intents_to_repository():
    text = _read(VIEWMODEL_KT)
    assert "RemoteIntent" in text, "deve haver um tipo de intent"
    assert "commandRepository.sendKey" in text, "PressKey deve chamar sendKey"
    assert "commandRepository.sendText" in text, "TypeText deve chamar sendText"
    assert "commandRepository.launchApp" in text, "LaunchApp deve chamar launchApp"


def test_viewmodel_exposes_session_state_as_stateflow():
    text = _read(VIEWMODEL_KT)
    assert "StateFlow<ConnectionState>" in text, "deve expor um StateFlow do estado da sessÃ£o"
    assert "session.state" in text, "deve reexpor o StateFlow do RemoteSession"
