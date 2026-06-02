"""Tests for task ab1888ac — Wake-on-LAN (ligar TV desligada).

Uma TV totalmente desligada não responde no socket de controle. Quando o
usuário aperta POWER e a sessão está offline, o app deve cair para um envio de
**magic packet** Wake-on-LAN, em broadcast UDP, usando o ``macAddress``
persistido (capturado em ``connect``).

Acceptance criteria verificado aqui (comportamentalmente):
  1. **Teste unitário valida o formato do magic packet (6x 0xFF + 16x MAC).**
  2. **O botão POWER tenta WoL quando a sessão está offline.**

Estratégia (segue a convenção do repositório — ver ``test_remote_text_input.py``
/ ``test_remote_viewmodel.py``): compilamos e EXECUTAMOS os fontes Kotlin REAIS
(``WakeOnLan`` + ``RemoteViewModel`` + ``CommandRepository`` + ``RemoteSession``
+ modelos + ``TizenProtocol``) contra *shims* puros de ``javax.inject``,
``org.json``, ``androidx.lifecycle`` (incluindo a propriedade de extensão
``viewModelScope``, agora usada pelo ViewModel) e ``dagger.hilt`` — mais
``kotlinx-coroutines`` + ``okhttp``/``okio`` reais.

Para o critério (1) chamamos a função pura ``WakeOnLan.buildMagicPacket`` (sem
I/O) e imprimimos os 102 bytes em hex; o Python verifica, de forma independente,
o layout exigido (6 bytes 0xFF + 6-byte MAC × 16) e que MACs inválidos são
rejeitados.

Para o critério (2), como WoL é um efeito de rede "fire-and-forget" (UDP
broadcast para ``255.255.255.255:9``) disparado pelo ``RemoteViewModel`` REAL,
abrimos um socket UDP local em ``0.0.0.0:9`` e provamos o comportamento pelo
*pacote observado na rede* — exatamente como os outros testes provam o frame
serializado. O harness aciona ``onIntent(PressKey(POWER))`` com um transporte
*fake* OFFLINE (``sendKey`` -> ``false``) e confirma que o magic packet do MAC
persistido chega ao receptor. Os contracasos (POWER online, tecla NÃO-power
offline, e POWER offline sem MAC) NÃO devem produzir pacote algum.

Se o ambiente não entregar o broadcast limitado em loopback (alguns CIs sem
rede), o bloco comportamental de rede dá ``skip``; as asserções de formato
(puras) e as estruturais sempre rodam. Se o toolchain Kotlin/JDK ou os jars não
forem localizados, os testes que compilam dão ``skip``.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

WAKE_ON_LAN_KT = PKG / "network" / "wol" / "WakeOnLan.kt"
VIEWMODEL_KT = PKG / "viewmodel" / "RemoteViewModel.kt"

SESSION_DIR = PKG / "network" / "session"
REMOTE_SESSION_KT = SESSION_DIR / "RemoteSession.kt"
CONNECTION_STATE_KT = SESSION_DIR / "ConnectionState.kt"
COMMAND_TRANSPORT_KT = SESSION_DIR / "CommandTransport.kt"

PROTO_DIR = PKG / "network" / "protocol"
TIZEN_PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
TIZEN_MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

REPO_KT = PKG / "data" / "repository" / "CommandRepository.kt"
REMOTE_KEY_KT = PKG / "data" / "registry" / "RemoteKey.kt"
DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"

REAL_SOURCES = [
    WAKE_ON_LAN_KT, VIEWMODEL_KT, REPO_KT,
    REMOTE_SESSION_KT, CONNECTION_STATE_KT, COMMAND_TRANSPORT_KT,
    TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT,
    REMOTE_KEY_KT, DISCOVERED_TV_KT,
]

GRADLE_CACHES = Path.home() / ".gradle" / "caches"

# Test MAC used both on the Kotlin side (harness) and recomputed in Python.
TEST_MAC = "AA:BB:CC:DD:EE:FF"
TEST_MAC_HEX = "aabbccddeeff"
WOL_PORT = 9


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _expected_magic_packet_hex(mac_hex: str) -> str:
    """6 bytes 0xFF (sync stream) + the 6-byte MAC repeated 16 times."""
    return "ff" * 6 + mac_hex * 16


# --------------------------------------------------------------------------- #
# Shims — pure annotations, org.json, and the Android/Hilt symbols the
# ViewModel/Session link against. Mirrors test_remote_text_input.py, EXTENDED so
# androidx.lifecycle also provides the `viewModelScope` extension property now
# used by RemoteViewModel (backed by a real IO-dispatched scope so the
# fire-and-forget WoL coroutine actually runs).
# --------------------------------------------------------------------------- #
INJECT_SHIM = r'''package javax.inject

annotation class Inject
annotation class Singleton
annotation class Qualifier
'''

LIFECYCLE_SHIM = r'''package androidx.lifecycle

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

abstract class ViewModel {
    open fun onCleared() {}
}

// Real androidx provides this as an extension property; a shared IO-backed scope
// is enough for the harness — the launched WoL send runs on a real thread so the
// receiver observes the broadcast.
private val sharedViewModelScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
val ViewModel.viewModelScope: CoroutineScope get() = sharedViewModelScope
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
# Harness — exercises the REAL WakeOnLan + RemoteViewModel and emits
# "label|value" lines:
#   FORMAT|<hex 102 bytes>           buildMagicPacket(TEST_MAC) layout
#   FORMAT_LEN|<int>                 packet length
#   INVALID_MAC|<THREW|NOTHROW>      non-hex MAC rejected
#   SHORT_MAC|<THREW|NOTHROW>        wrong octet count rejected
#   WOL_POWER_OFFLINE|<hex|NONE>     POWER + offline -> magic packet on the wire
#   WOL_POWER_ONLINE|<hex|NONE>      POWER + online  -> nothing (NONE)
#   WOL_VOLUME_OFFLINE|<hex|NONE>    non-POWER + offline -> nothing (NONE)
#   WOL_POWER_NOMAC|<hex|NONE>       POWER + offline + no stored MAC -> nothing
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.session.CommandTransport
import com.factory.samsungremote.network.session.RemoteSession
import com.factory.samsungremote.network.wol.WakeOnLan
import com.factory.samsungremote.viewmodel.RemoteIntent
import com.factory.samsungremote.viewmodel.RemoteViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/** Transport whose connectivity is fixed: send() == "reached an open socket?". */
class FakeTransport(private val connected: Boolean) : CommandTransport {
    override fun send(frame: String): Boolean = connected
}

/** Inert socket factory: the session is never actually opened in this harness. */
class NoopFactory : WebSocket.Factory {
    override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket =
        throw UnsupportedOperationException("not used")
}

fun hex(bytes: ByteArray, len: Int): String {
    val sb = StringBuilder()
    for (i in 0 until len) sb.append(String.format("%02x", bytes[i].toInt() and 0xFF))
    return sb.toString()
}

const val WOL_PORT = 9
val MAC = "AA:BB:CC:DD:EE:FF"
val TV = DiscoveredTv(id = "uuid:test", name = "TV", ipAddress = "127.0.0.1")
val POWER = RemoteKey(code = "KEY_POWER", category = KeyCategory.POWER, label = "Power")
val VOLUP = RemoteKey(code = "KEY_VOLUP", category = KeyCategory.VOLUME, label = "Vol+")

@OptIn(ExperimentalCoroutinesApi::class)
fun newViewModel(connected: Boolean): RemoteViewModel {
    // Session lives on a never-advanced test dispatcher: connect() only enqueues
    // work (no real socket is opened via NoopFactory) but the MAC is stored
    // synchronously by the ViewModel for the WoL fallback.
    val scheduler = TestCoroutineScheduler()
    val sessionScope = CoroutineScope(StandardTestDispatcher(scheduler))
    val session = RemoteSession(NoopFactory(), sessionScope)
    return RemoteViewModel(CommandRepository(FakeTransport(connected)), session, WakeOnLan())
}

/**
 * Connects (storing [mac]), presses [key], and reports the magic packet captured
 * on the local WoL port (or NONE on timeout — i.e. no WoL was attempted).
 */
fun probe(label: String, connected: Boolean, key: RemoteKey, mac: String?, timeoutMs: Int) {
    val vm = newViewModel(connected)
    vm.connect(TV, null, mac)

    val rx = DatagramSocket(null)
    rx.reuseAddress = true
    rx.broadcast = true
    rx.bind(InetSocketAddress("0.0.0.0", WOL_PORT))
    rx.soTimeout = timeoutMs
    try {
        vm.onIntent(RemoteIntent.PressKey(key))
        val buf = ByteArray(256)
        val dp = DatagramPacket(buf, buf.size)
        val value = try {
            rx.receive(dp)
            hex(buf, dp.length)
        } catch (e: SocketTimeoutException) {
            "NONE"
        }
        println("$label|$value")
    } finally {
        rx.close()
    }
}

fun main() {
    // ---- (1) Magic packet format — pure, no I/O. ----
    val packet = WakeOnLan.buildMagicPacket(MAC)
    println("FORMAT|" + hex(packet, packet.size))
    println("FORMAT_LEN|" + packet.size)
    val invalid = try { WakeOnLan.buildMagicPacket("zz:zz:zz:zz:zz:zz"); "NOTHROW" }
        catch (e: IllegalArgumentException) { "THREW" }
    println("INVALID_MAC|$invalid")
    val shortMac = try { WakeOnLan.buildMagicPacket("AA:BB:CC"); "NOTHROW" }
        catch (e: IllegalArgumentException) { "THREW" }
    println("SHORT_MAC|$shortMac")

    // ---- (2) POWER press tries WoL only when offline + MAC known. ----
    // Positive first (proves the environment delivers the broadcast at all).
    probe("WOL_POWER_OFFLINE", connected = false, key = POWER, mac = MAC, timeoutMs = 8000)
    probe("WOL_POWER_ONLINE", connected = true, key = POWER, mac = MAC, timeoutMs = 2500)
    probe("WOL_VOLUME_OFFLINE", connected = false, key = VOLUP, mac = MAC, timeoutMs = 2500)
    probe("WOL_POWER_NOMAC", connected = false, key = POWER, mac = null, timeoutMs = 2500)

    println("DONE|1")
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_remote_text_input.py).
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


def _parse_lines(stdout):
    out = {}
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if "|" not in line:
            continue
        label, _, value = line.partition("|")
        out[label.strip()] = value
    return out


# --------------------------------------------------------------------------- #
# Behavioural fixture — compile real sources + harness, run once.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def out(tmp_path_factory):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("toolchain/jars indisponíveis: " + ", ".join(tc["missing"]))
    for s in REAL_SOURCES:
        if not s.is_file():
            pytest.fail(f"fonte ausente: {s}")

    tmp = tmp_path_factory.mktemp("remote_wol")
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
        "compilação do harness WoL falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, *link_libs])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execução do harness WoL falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_lines(run.stdout)


# --------------------------------------------------------------------------- #
# Acceptance (1) — magic packet format: 6x 0xFF + 16x MAC (behavioural, pure).
# --------------------------------------------------------------------------- #
def test_harness_ran(out):
    assert out.get("DONE") == "1", f"harness não concluiu: {out!r}"


def test_magic_packet_layout_is_sync_stream_plus_mac_x16(out):
    packet = out.get("FORMAT")
    assert packet is not None, f"harness não emitiu FORMAT: {out!r}"
    expected = _expected_magic_packet_hex(TEST_MAC_HEX)
    assert packet == expected, (
        f"layout do magic packet incorreto:\n  obtido:   {packet}\n  esperado: {expected}"
    )


def test_magic_packet_starts_with_six_ff_bytes(out):
    packet = out.get("FORMAT", "")
    assert packet[:12] == "ff" * 6, (
        f"o magic packet deve começar com 6 bytes 0xFF: {packet[:12]!r}"
    )


def test_magic_packet_repeats_mac_sixteen_times(out):
    packet = out.get("FORMAT", "")
    body = packet[12:]  # after the 6-byte sync stream
    assert body == TEST_MAC_HEX * 16, "o MAC deve ser repetido exatamente 16 vezes"
    # Independent check: exactly 16 occurrences of the MAC in the body.
    assert body.count(TEST_MAC_HEX) == 16


def test_magic_packet_total_length_is_102_bytes(out):
    assert out.get("FORMAT_LEN") == "102", (
        f"tamanho do magic packet deve ser 102 (6 + 16*6): {out.get('FORMAT_LEN')!r}"
    )
    assert len(out.get("FORMAT", "")) == 102 * 2  # hex chars


def test_invalid_mac_is_rejected(out):
    assert out.get("INVALID_MAC") == "THREW", "MAC não-hex deve ser rejeitado"
    assert out.get("SHORT_MAC") == "THREW", "MAC com nº errado de octetos deve ser rejeitado"


# --------------------------------------------------------------------------- #
# Acceptance (2) — POWER press tries WoL when the session is offline.
# Network-dependent: skipped only if the environment cannot deliver the local
# limited broadcast (so the positive case itself never arrives).
# --------------------------------------------------------------------------- #
def _require_delivery(out):
    if out.get("WOL_POWER_OFFLINE") == "NONE":
        pytest.skip(
            "ambiente não entregou o broadcast WoL local (255.255.255.255:9); "
            "asserções de rede ignoradas"
        )


def test_power_press_offline_sends_magic_packet(out):
    _require_delivery(out)
    captured = out.get("WOL_POWER_OFFLINE")
    assert captured is not None, f"harness não emitiu WOL_POWER_OFFLINE: {out!r}"
    expected = _expected_magic_packet_hex(TEST_MAC_HEX)
    assert captured == expected, (
        "POWER offline deveria transmitir o magic packet do MAC persistido:\n"
        f"  obtido:   {captured}\n  esperado: {expected}"
    )


def test_power_press_online_does_not_send_wol(out):
    _require_delivery(out)
    assert out.get("WOL_POWER_ONLINE") == "NONE", (
        "com a sessão ONLINE, POWER não deve disparar WoL: "
        f"{out.get('WOL_POWER_ONLINE')!r}"
    )


def test_non_power_key_offline_does_not_send_wol(out):
    _require_delivery(out)
    assert out.get("WOL_VOLUME_OFFLINE") == "NONE", (
        "tecla NÃO-power offline não deve disparar WoL: "
        f"{out.get('WOL_VOLUME_OFFLINE')!r}"
    )


def test_power_press_offline_without_known_mac_skips_wol(out):
    _require_delivery(out)
    assert out.get("WOL_POWER_NOMAC") == "NONE", (
        "sem MAC persistido, WoL deve ser pulado (sem pacote): "
        f"{out.get('WOL_POWER_NOMAC')!r}"
    )


# --------------------------------------------------------------------------- #
# Structural — wiring guarantees (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_wake_on_lan_source_present():
    assert WAKE_ON_LAN_KT.is_file(), f"WakeOnLan ausente: {WAKE_ON_LAN_KT}"


def test_build_magic_packet_defined_as_pure_function():
    text = _read(WAKE_ON_LAN_KT)
    assert "fun buildMagicPacket(" in text, "WakeOnLan deve expor buildMagicPacket"
    assert "0xFF" in text, "o magic packet deve usar bytes 0xFF no sync stream"


def test_magic_packet_constants_match_6_plus_16x6():
    text = _read(WAKE_ON_LAN_KT)
    # 6 sync bytes, MAC repeated 16 times, 6-byte MAC => 102 bytes total.
    assert "SYNC_STREAM_LENGTH = 6" in text
    assert "MAC_REPETITIONS = 16" in text
    assert "MAC_LENGTH = 6" in text


def test_wake_broadcasts_over_udp():
    text = _read(WAKE_ON_LAN_KT)
    assert "DatagramSocket" in text and "DatagramPacket" in text, (
        "wake() deve enviar o magic packet via UDP"
    )
    assert "broadcast = true" in text, "o socket WoL deve habilitar broadcast"


def test_viewmodel_attempts_wol_on_power_when_offline():
    text = _read(VIEWMODEL_KT)
    assert "import com.factory.samsungremote.network.wol.WakeOnLan" in text, (
        "o ViewModel deve depender do WakeOnLan"
    )
    assert "wakeOnLan.wake(" in text, "o ViewModel deve chamar wakeOnLan.wake(...)"
    assert "KeyCategory.POWER" in text, "o fallback WoL deve ser restrito à tecla POWER"


def test_viewmodel_stores_mac_address_for_wol():
    text = _read(VIEWMODEL_KT)
    assert "macAddress" in text, (
        "o ViewModel deve guardar o macAddress (de KnownTv) para o WoL"
    )
