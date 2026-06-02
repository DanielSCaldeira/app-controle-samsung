"""Tests for task e367750f — PairingManager: handshake e obtenção de token.

Acceptance criteria verified here (behaviourally):
  1. Um **WebSocket fake** (no espírito do MockWebServer) simula a resposta de
     handshake do TV carregando ``data.token``; confirma-se que o
     ``PairingManager`` *extrai* o token e o *persiste* via ``TvRegistry``
     (cifrado — nunca em claro no "banco").
  2. Falha de autorização (``ms.channel.unauthorized``) **propaga um erro
     tratável** (``PairingException`` com ``reason = UNAUTHORIZED``) e nada é
     persistido; o mesmo vale para falha de conexão (``onFailure`` ->
     ``CONNECTION_FAILED`` preservando a causa) e fechamento sem token
     (``onClosed`` -> ``NO_TOKEN``).
  3. Renovação: se já há token guardado, ele é reenviado na query (``token=``);
     o TV reconfirmando sem novo token mantém o token; reemitindo um novo token
     a rotação é persistida.

Strategy
--------
Seguindo a convenção do repositório (executar o **código real** num JVM desktop
em vez de só inspecionar fontes), compilamos os fontes Kotlin reais do pairing —
``PairingManager`` + ``PairingException`` — junto com o ``TvRegistry`` real,
``TizenProtocol`` real e seus modelos, contra:

  * pequenos *shims* de anotações puras (``androidx.room.*``, ``javax.inject.*``)
    e um shim de ``org.json`` com a mesma semântica usada pelo parser; e
  * um ``KnownTvDao`` in-memory + um ``TokenCipher`` reversível de referência,
    de modo que o ``TvRegistry`` real roda de ponta a ponta.

O handshake é dirigido por um ``WebSocket.Factory`` **fake** que captura a URL
montada pelo ``PairingManager`` e injeta as mensagens/eventos do TV no
``WebSocketListener`` real — exatamente o ponto de extensão que o design expõe
(``socketFactory: WebSocket.Factory``). Isso exercita o caminho genuíno de
``suspendCancellableCoroutine`` -> parse -> persistência.

Se o toolchain Kotlin/JDK ou os jars (okhttp/okio/coroutines) não forem
localizados nos caches do Gradle, os testes comportamentais dão ``skip``; as
asserções estruturais sempre rodam.
"""

import base64
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

PAIR_DIR = PKG / "network" / "pairing"
PAIRING_MANAGER_KT = PAIR_DIR / "PairingManager.kt"
PAIRING_EXCEPTION_KT = PAIR_DIR / "PairingException.kt"
LAN_TRUST_KT = PAIR_DIR / "LanTrustManager.kt"

PROTO_DIR = PKG / "network" / "protocol"
TIZEN_PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
TIZEN_MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"
REGISTRY_KT = PKG / "data" / "registry" / "TvRegistry.kt"
KNOWN_TV_KT = PKG / "data" / "db" / "KnownTv.kt"
KNOWN_TV_DAO_KT = PKG / "data" / "db" / "KnownTvDao.kt"
TOKEN_CIPHER_KT = PKG / "data" / "crypto" / "TokenCipher.kt"

REAL_SOURCES = [
    PAIRING_MANAGER_KT, PAIRING_EXCEPTION_KT,
    TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT,
    DISCOVERED_TV_KT, REGISTRY_KT,
    KNOWN_TV_KT, KNOWN_TV_DAO_KT, TOKEN_CIPHER_KT,
]

GRADLE_CACHES = Path.home() / ".gradle" / "caches"

APP_NAME = "SamsungRemote"
APP_NAME_B64 = base64.b64encode(APP_NAME.encode("utf-8")).decode("ascii")
CONTROL_PATH = "/api/v2/channels/samsung.remote.control"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Shims — pure annotations + org.json (same semantics the code relies on).
# --------------------------------------------------------------------------- #
ROOM_SHIM = r'''package androidx.room

annotation class Entity(val tableName: String = "")
annotation class PrimaryKey(val autoGenerate: Boolean = false)
annotation class ColumnInfo(val name: String = "")
annotation class Dao
annotation class Query(val value: String)
annotation class Insert(val onConflict: Int = 1)

object OnConflictStrategy {
    const val REPLACE = 1
    const val ABORT = 3
    const val IGNORE = 5
}
'''

INJECT_SHIM = r'''package javax.inject

annotation class Inject
annotation class Singleton
annotation class Qualifier
'''

ORG_JSON_SHIM = r'''package org.json

class JSONException(message: String) : RuntimeException(message)

object NULL { override fun toString(): String = "null" }

class JSONArray {
    val items = ArrayList<Any?>()
    fun put(value: Any?): JSONArray { items.add(value); return this }
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
# Harness — drives the REAL PairingManager + REAL TvRegistry via a fake socket.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.crypto.TokenCipher
import com.factory.samsungremote.data.crypto.TokenCipherException
import com.factory.samsungremote.data.db.KnownTv
import com.factory.samsungremote.data.db.KnownTvDao
import com.factory.samsungremote.data.registry.TvRegistry
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.pairing.PairingException
import com.factory.samsungremote.network.pairing.PairingManager
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.IOException
import java.nio.charset.StandardCharsets
import java.util.Base64

/** In-memory KnownTvDao so the real TvRegistry runs without Room. */
class FakeDao : KnownTvDao {
    val store = LinkedHashMap<String, KnownTv>()
    override suspend fun upsert(tv: KnownTv) { store[tv.id] = tv }
    override suspend fun getById(id: String): KnownTv? = store[id]
    override suspend fun getAll(): List<KnownTv> = store.values.toList()
    override fun observeAll(): Flow<List<KnownTv>> = flowOf(store.values.toList())
    override suspend fun delete(id: String) { store.remove(id) }
}

/** Reversible, clearly-not-plaintext cipher mirroring the TokenCipher contract. */
class FakeCipher : TokenCipher {
    override fun encrypt(plaintext: String): String =
        "enc::" + Base64.getEncoder().encodeToString(plaintext.toByteArray(StandardCharsets.UTF_8))
    override fun decrypt(ciphertext: String): String {
        if (!ciphertext.startsWith("enc::")) throw TokenCipherException("not produced by me")
        val body = ciphertext.removePrefix("enc::")
        return String(Base64.getDecoder().decode(body), StandardCharsets.UTF_8)
    }
}

class FakeWebSocket(private val req: Request) : WebSocket {
    override fun request(): Request = req
    override fun queueSize(): Long = 0L
    override fun send(text: String): Boolean = true
    override fun send(bytes: ByteString): Boolean = true
    override fun close(code: Int, reason: String?): Boolean = true
    override fun cancel() {}
}

/** Captures the handshake URL and scripts the TV's reply into the listener. */
class ScriptedFactory(val script: (WebSocket, WebSocketListener) -> Unit) : WebSocket.Factory {
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
        val ws = FakeWebSocket(request)
        script(ws, listener)
        return ws
    }
}

fun p(k: String, v: Any?) = println("$k=$v")

fun main() {
    val tv = DiscoveredTv("uuid:tv-1", "[TV] Sala", "192.168.0.50", "QN65")

    // ---- A: happy path — TV delivers data.token; extract + persist ----
    run {
        val dao = FakeDao(); val reg = TvRegistry(dao, FakeCipher())
        val factory = ScriptedFactory { ws, l ->
            l.onMessage(ws, """{"event":"ms.channel.connect","data":{"id":"abc","token":"TOKEN-ABC-123"}}""")
        }
        val pm = PairingManager(reg, factory)
        try {
            val token = runBlocking { pm.pair(tv) }
            p("A_status", "ok")
            p("A_returned", token)
            p("A_getToken", runBlocking { reg.getToken(tv.id) })
            p("A_raw", dao.store[tv.id]?.tokenEncrypted)
            p("A_count", dao.store.size)
            p("A_name", dao.store[tv.id]?.name)
            p("A_ip", dao.store[tv.id]?.ipAddress)
            p("A_scheme", factory.scheme)
            p("A_host", factory.host)
            p("A_port", factory.port)
            p("A_path", factory.path)
            p("A_nameparam", factory.nameParam)
            p("A_tokenparam", factory.tokenParam)
        } catch (e: Throwable) {
            p("A_status", "threw:" + e.javaClass.simpleName + ":" + e.message)
        }
    }

    // ---- B: unauthorized — treatable error, nothing persisted ----
    run {
        val dao = FakeDao(); val reg = TvRegistry(dao, FakeCipher())
        val factory = ScriptedFactory { ws, l ->
            l.onMessage(ws, """{"event":"ms.channel.unauthorized"}""")
        }
        val pm = PairingManager(reg, factory)
        try {
            val token = runBlocking { pm.pair(tv) }
            p("B_status", "ok:" + token)
        } catch (e: PairingException) {
            p("B_status", "pairing")
            p("B_reason", e.reason)
            p("B_count", dao.store.size)
        } catch (e: Throwable) {
            p("B_status", "other:" + e.javaClass.simpleName)
        }
    }

    // ---- C: connection failure — CONNECTION_FAILED preserving cause ----
    run {
        val dao = FakeDao(); val reg = TvRegistry(dao, FakeCipher())
        val factory = ScriptedFactory { ws, l ->
            l.onFailure(ws, IOException("socket boom"), null)
        }
        val pm = PairingManager(reg, factory)
        try {
            runBlocking { pm.pair(tv) }
            p("C_status", "ok")
        } catch (e: PairingException) {
            p("C_status", "pairing")
            p("C_reason", e.reason)
            p("C_cause", e.cause?.javaClass?.simpleName)
            p("C_count", dao.store.size)
        } catch (e: Throwable) {
            p("C_status", "other:" + e.javaClass.simpleName)
        }
    }

    // ---- D: renewal — existing token replayed; TV reconfirms w/o new token ----
    run {
        val dao = FakeDao(); val reg = TvRegistry(dao, FakeCipher())
        runBlocking { reg.saveTv(KnownTv(id = tv.id, name = "old", ipAddress = "10.0.0.1"), "OLD-TOKEN") }
        val factory = ScriptedFactory { ws, l ->
            l.onMessage(ws, """{"event":"ms.channel.connect","data":{"id":"abc"}}""")
        }
        val pm = PairingManager(reg, factory)
        try {
            val token = runBlocking { pm.pair(tv) }
            p("D_status", "ok")
            p("D_returned", token)
            p("D_getToken", runBlocking { reg.getToken(tv.id) })
            p("D_tokenparam", factory.tokenParam)
            p("D_name", dao.store[tv.id]?.name)
            p("D_ip", dao.store[tv.id]?.ipAddress)
        } catch (e: Throwable) {
            p("D_status", "threw:" + e.javaClass.simpleName + ":" + e.message)
        }
    }

    // ---- E: renewal with rotation — TV issues a NEW token ----
    run {
        val dao = FakeDao(); val reg = TvRegistry(dao, FakeCipher())
        runBlocking { reg.saveTv(KnownTv(id = tv.id, name = "old", ipAddress = "10.0.0.1"), "OLD-TOKEN") }
        val factory = ScriptedFactory { ws, l ->
            l.onMessage(ws, """{"event":"ms.channel.connect","data":{"token":"NEW-TOKEN-999"}}""")
        }
        val pm = PairingManager(reg, factory)
        try {
            val token = runBlocking { pm.pair(tv) }
            p("E_returned", token)
            p("E_getToken", runBlocking { reg.getToken(tv.id) })
            p("E_tokenparam", factory.tokenParam)
        } catch (e: Throwable) {
            p("E_status", "threw:" + e.javaClass.simpleName + ":" + e.message)
        }
    }

    // ---- F: closed before any token — NO_TOKEN ----
    run {
        val dao = FakeDao(); val reg = TvRegistry(dao, FakeCipher())
        val factory = ScriptedFactory { ws, l ->
            l.onClosed(ws, 1000, "bye")
        }
        val pm = PairingManager(reg, factory)
        try {
            runBlocking { pm.pair(tv) }
            p("F_status", "ok")
        } catch (e: PairingException) {
            p("F_status", "pairing")
            p("F_reason", e.reason)
            p("F_count", dao.store.size)
        } catch (e: Throwable) {
            p("F_status", "other:" + e.javaClass.simpleName)
        }
    }
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_discovery_service.py).
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
    java = _java_exe()
    tc = {
        "java": java,
        "emb": _find_jar("kotlin-compiler-embeddable-*.jar"),
        "stdlib": _find_jar("kotlin-stdlib-1*.jar", "kotlin-stdlib-2*.jar"),
        "scrt": _find_jar("kotlin-script-runtime-*.jar"),
        "refl": _find_jar("kotlin-reflect-*.jar"),
        "trove": _find_jar("trove4j-*.jar"),
        "annot": _find_jar("annotations-13*.jar"),
        "corout": _find_jar("kotlinx-coroutines-core-jvm-*.jar"),
        "okhttp": _find_jar("okhttp-4*.jar", "okhttp-3*.jar", "okhttp-5*.jar"),
        "okio": _find_jar("okio-jvm-*.jar"),
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"],
        tc["annot"], tc["corout"],
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
# Behavioural fixture — compile real sources + harness, run once.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def out(tmp_path_factory):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("toolchain/jars indisponíveis: " + ", ".join(tc["missing"]))
    for s in REAL_SOURCES:
        if not s.is_file():
            pytest.fail(f"fonte do pairing ausente: {s}")

    tmp = tmp_path_factory.mktemp("pairing")
    src = tmp / "src"
    (src / "shims").mkdir(parents=True, exist_ok=True)
    (src / "shims" / "room_shim.kt").write_text(ROOM_SHIM, encoding="utf-8")
    (src / "shims" / "inject_shim.kt").write_text(INJECT_SHIM, encoding="utf-8")
    (src / "shims" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    harness = src / "Harness.kt"
    harness.write_text(HARNESS_KT, encoding="utf-8")

    out_dir = tmp / "out"
    out_dir.mkdir(exist_ok=True)

    link_libs = [tc["stdlib"], tc["corout"], tc["okhttp"], tc["okio"]]
    compile_cp = os.pathsep.join(str(p) for p in link_libs)

    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", compile_cp,
        "-d", str(out_dir),
        str(src / "shims" / "room_shim.kt"),
        str(src / "shims" / "inject_shim.kt"),
        str(src / "shims" / "json_shim.kt"),
        *[str(s) for s in REAL_SOURCES],
        str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilação do pairing falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, *link_libs])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execução do harness de pairing falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_kv(run.stdout)


# --------------------------------------------------------------------------- #
# Criterion 1 — fake WebSocket delivers token; manager extracts + persists.
# --------------------------------------------------------------------------- #
def test_extracts_token_from_handshake(out):
    assert out.get("A_status") == "ok", f"handshake feliz falhou: {out!r}"
    assert out.get("A_returned") == "TOKEN-ABC-123"


def test_persists_token_via_registry(out):
    # Recuperável (decifrado) pelo TvRegistry...
    assert out.get("A_getToken") == "TOKEN-ABC-123"
    # ...e exatamente uma TV gravada.
    assert out.get("A_count") == "1"


def test_persisted_token_is_encrypted_not_clear_text(out):
    raw = out.get("A_raw")
    assert raw and raw != "TOKEN-ABC-123", "token gravado em claro"
    assert "TOKEN-ABC-123" not in raw, "token em claro vazou no valor persistido"
    assert raw.startswith("enc::"), "token não passou pelo cipher antes de persistir"


def test_persists_discovered_tv_metadata(out):
    assert out.get("A_name") == "[TV] Sala"
    assert out.get("A_ip") == "192.168.0.50"


def test_handshake_url_targets_secure_control_endpoint(out):
    # OkHttp traduz wss:// -> https:// ao montar a Request; o destino é o mesmo.
    assert out.get("A_scheme") == "https"
    assert out.get("A_host") == "192.168.0.50"
    assert out.get("A_port") == "8002"
    assert out.get("A_path") == CONTROL_PATH


def test_handshake_url_carries_base64_name(out):
    name = out.get("A_nameparam")
    assert name == APP_NAME_B64, f"name esperado {APP_NAME_B64!r}, veio {name!r}"
    assert base64.b64decode(name).decode("utf-8") == APP_NAME


def test_fresh_pairing_sends_no_token_param(out):
    # Sem token guardado, nada de &token= na URL do primeiro pareamento.
    assert out.get("A_tokenparam") in ("null", "", None)


# --------------------------------------------------------------------------- #
# Criterion 2 — failures propagate as treatable PairingException.
# --------------------------------------------------------------------------- #
def test_unauthorized_propagates_treatable_error(out):
    assert out.get("B_status") == "pairing", f"esperado PairingException: {out!r}"
    assert out.get("B_reason") == "UNAUTHORIZED"


def test_unauthorized_persists_nothing(out):
    assert out.get("B_count") == "0", "nada deve ser persistido numa negação"


def test_connection_failure_is_treatable_and_keeps_cause(out):
    assert out.get("C_status") == "pairing"
    assert out.get("C_reason") == "CONNECTION_FAILED"
    assert out.get("C_cause") == "IOException", "causa de transporte não preservada"
    assert out.get("C_count") == "0"


def test_closed_without_token_yields_no_token_error(out):
    assert out.get("F_status") == "pairing"
    assert out.get("F_reason") == "NO_TOKEN"
    assert out.get("F_count") == "0"


# --------------------------------------------------------------------------- #
# Criterion 3 — renewal: replay stored token; keep or rotate.
# --------------------------------------------------------------------------- #
def test_renewal_replays_stored_token_in_url(out):
    assert out.get("D_status") == "ok", f"renovação falhou: {out!r}"
    assert out.get("D_tokenparam") == "OLD-TOKEN", "token existente não reenviado p/ renovação"


def test_renewal_without_new_token_keeps_existing(out):
    assert out.get("D_returned") == "OLD-TOKEN"
    assert out.get("D_getToken") == "OLD-TOKEN"
    # Metadados da TV descoberta são atualizados ao reconfirmar.
    assert out.get("D_name") == "[TV] Sala"
    assert out.get("D_ip") == "192.168.0.50"


def test_renewal_with_rotation_persists_new_token(out):
    assert out.get("E_tokenparam") == "OLD-TOKEN", "token antigo deveria ser reenviado"
    assert out.get("E_returned") == "NEW-TOKEN-999"
    assert out.get("E_getToken") == "NEW-TOKEN-999", "token rotacionado não foi persistido"


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_pairing_sources_present():
    for p in (PAIRING_MANAGER_KT, PAIRING_EXCEPTION_KT, LAN_TRUST_KT):
        assert p.is_file(), f"fonte ausente: {p}"


def test_manager_opens_secure_control_websocket():
    text = _read(PAIRING_MANAGER_KT)
    assert "wss" in text, "deve usar o esquema seguro wss"
    assert "8002" in text, "porta de controle 8002 ausente"
    assert CONTROL_PATH in text, "endpoint de controle samsung.remote.control ausente"
    assert "name=" in text, "nome do controlador deve ir na query"
    assert "Base64" in text and "encodeToString" in text, "nome deve ser Base64-encoded"
    assert "WebSocket.Factory" in text, "deve abrir via WebSocket.Factory injetável"


def test_manager_extracts_token_and_persists_via_registry():
    text = _read(PAIRING_MANAGER_KT)
    assert "TizenProtocol.parseEvent" in text or "TizenProtocol.parseToken" in text, \
        "token deve ser extraído via TizenProtocol"
    assert "registry.saveTv" in text, "token deve ser persistido via TvRegistry.saveTv"
    assert "registry.getToken" in text, "token existente deve ser lido p/ renovação"


def test_manager_maps_failures_to_pairing_exception():
    text = _read(PAIRING_MANAGER_KT)
    assert "onFailure" in text and "PairingException" in text
    assert "ms.channel.unauthorized" in text, "negação de autorização deve ser tratada"
    for reason in ("UNAUTHORIZED", "CONNECTION_FAILED", "NO_TOKEN"):
        assert reason in text, f"razão de falha ausente: {reason}"


def test_manager_replays_token_for_renewal():
    text = _read(PAIRING_MANAGER_KT)
    assert "token=" in text, "renovação deve reenviar &token= na URL"


def test_pairing_exception_is_treatable_with_reason_and_cause():
    text = _read(PAIRING_EXCEPTION_KT)
    assert "enum class PairingFailureReason" in text
    assert "class PairingException" in text
    assert "Exception(message, cause)" in text, "deve preservar a causa subjacente"
    assert "val reason" in text, "deve expor uma razão tratável para a UI"


def test_lan_trust_manager_accepts_self_signed_for_session():
    text = _read(LAN_TRUST_KT)
    assert "X509TrustManager" in text
    # Confiança relaxada apenas para a sessão LAN (cert auto-assinado da TV).
    assert "checkServerTrusted" in text
    assert "hostnameVerifier" in text, "CN do cert da TV não bate com o IP; verifier relaxado"
    assert "sslSocketFactory" in text, "client deve instalar o trust manager"
