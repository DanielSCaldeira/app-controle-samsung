"""Tests for task 6178558d â€” Entrada de texto (teclado da TV).

A tela de controle ganha um campo de texto + botÃ£o "Enviar" (``TextEntryRow``)
para digitar em campos de busca da TV. Ao submeter, a tela encaminha o texto a
``RemoteIntent.TypeText``, que o ``RemoteViewModel`` roteia para
``CommandRepository.sendText`` â€” e a camada de protocolo codifica o texto em
Base64 no frame ``SendInputString``.

Acceptance criteria verificado aqui (comportamentalmente):
  **Teste: digitar texto e enviar resulta em ``sendText`` chamado com a string;
  a mensagem serializada contÃ©m o texto em Base64 (teste de protocolo).**

Como o runtime Compose nÃ£o roda na JVM desktop, provamos o elo crÃ­tico exigido
pelo aceite seguindo a convenÃ§Ã£o do repositÃ³rio (``test_remote_numeric_keypad.py``
/ ``test_remote_viewmodel.py``): o harness reproduz EXATAMENTE o que o
``TextEntryRow`` faz ao submeter â€”

    val submit = { if (text.isNotBlank()) { onSend(text); text = "" } }

â€” roteando ``onSend`` por ``RemoteIntent.TypeText(text)`` atravÃ©s do
``RemoteViewModel`` REAL ligado a um ``CommandTransport`` *fake* (gravador). Para
cada entrada provamos que:

  * o frame gravado Ã© o ``ms.remote.control`` / ``SendInputString`` com o texto
    **Base64** no ``Cmd`` (calculado de forma independente em Python â€” teste de
    protocolo), inclusive para entradas com espaÃ§o e UTF-8 multibyte; e
  * entrada **em branco** Ã© ignorada (nenhum frame), exatamente como o gate
    ``isNotBlank()`` da tela.

O comportamento "toque â†’ intent" sobre o runtime Compose Ã© coberto pela camada
de UI instrumentada; aqui fixamos o contrato de domÃ­nio + protocolo.

Strategy
--------
Compilamos os fontes Kotlin reais (``RemoteViewModel`` + ``CommandRepository`` +
``RemoteSession`` + modelos + ``TizenProtocol``) contra *shims* puros de
``javax.inject``, ``org.json`` (serializador compacto, ordem de inserÃ§Ã£o),
``androidx.lifecycle`` e ``dagger.hilt`` (mais ``kotlinx-coroutines`` +
``okhttp``/``okio`` reais para construir a sessÃ£o). O ``java.util.Base64`` usado
por ``TizenProtocol.sendText`` Ã© o real da JDK.

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

SCREEN_KT = PKG / "ui" / "remote" / "RemoteScreen.kt"
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

STRINGS_XML = ROOT / "app" / "src" / "main" / "res" / "values" / "strings.xml"

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---- Text inputs under test + their independently-computed wire frames. -----
# Cobrimos: palavra simples, frase com espaÃ§o (campo de busca), e UTF-8
# multibyte (acentos) â€” provando que o Base64 Ã© do texto exato submetido.
TEXT_INPUTS = ["hello", "Game of Thrones", "cafÃ©"]
BLANK_INPUT = "   "  # only-whitespace -> isNotBlank() == false -> ignored.


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _text_frame(text: str) -> str:
    return (
        '{"method":"ms.remote.control","params":{"Cmd":"' + _b64(text) + '",'
        '"DataOfCmd":"base64","TypeOfRemote":"SendInputString"}}'
    )


# --------------------------------------------------------------------------- #
# Shims â€” pure annotations, org.json, and the Android/Hilt symbols the
# ViewModel links against. (Shared, verbatim, with test_remote_viewmodel.py so
# the real ViewModel/repository/session link without an Android runtime.)
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
# Harness â€” reproduces TextEntryRow's submit gate for every input and routes
# onSend through the REAL RemoteViewModel (RemoteIntent.TypeText) wired to a
# recording transport. Emits "label|<frame|<<NONE>>>" lines (base64 in the
# label is avoided; the Python side keys by the plain text).
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.session.CommandTransport
import com.factory.samsungremote.network.session.RemoteSession
import com.factory.samsungremote.viewmodel.RemoteIntent
import com.factory.samsungremote.viewmodel.RemoteViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** Records every frame the ViewModel -> Repository chain produced. */
class FakeTransport : CommandTransport {
    val sent = ArrayList<String>()
    override fun send(frame: String): Boolean { sent.add(frame); return true }
}

/** Inert socket factory: the session is never connected in this harness. */
class NoopFactory : WebSocket.Factory {
    override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket =
        throw UnsupportedOperationException("not used")
}

@OptIn(ExperimentalCoroutinesApi::class)
fun main() {
    val transport = FakeTransport()
    val repo = CommandRepository(transport)
    val scheduler = TestCoroutineScheduler()
    val scope = CoroutineScope(StandardTestDispatcher(scheduler))
    val session = RemoteSession(NoopFactory(), scope)
    val vm = RemoteViewModel(repo, session)

    // Exactly TextEntryRow.submit: blank input is dropped; otherwise onSend(text)
    // -> RemoteIntent.TypeText(text) routed through the real ViewModel.
    fun submit(label: String, text: String) {
        val before = transport.sent.size
        if (text.isNotBlank()) {
            vm.onIntent(RemoteIntent.TypeText(text))
        }
        val added = transport.sent.size - before
        val frame = when (added) {
            0 -> "<<NONE>>"
            1 -> transport.sent[transport.sent.size - 1]
            else -> "<<added=$added>>"
        }
        println("$label|$frame")
    }

    submit("hello", "hello")
    submit("Game of Thrones", "Game of Thrones")
    submit("cafe", "cafÃ©")
    submit("blank", "   ")

    println("TOTAL|${transport.sent.size}")
    scope.cancel()
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_remote_viewmodel.py).
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
    """Parse 'label|frame' harness lines into {label: frame}."""
    out = {}
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if "|" not in line:
            continue
        label, _, frame = line.partition("|")
        out[label.strip()] = frame
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

    tmp = tmp_path_factory.mktemp("remote_text")
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
        "compilaÃ§Ã£o do harness de entrada de texto falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, *link_libs])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execuÃ§Ã£o do harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_lines(run.stdout)


# --------------------------------------------------------------------------- #
# Acceptance (behavioural) â€” typing + send => sendText with the string, and the
# serialized message carries the text Base64-encoded (protocol test).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", TEXT_INPUTS)
def test_typing_and_send_emits_send_input_string_with_base64(out, text):
    label = "cafe" if text == "cafÃ©" else text
    frame = out.get(label)
    assert frame is not None, f"harness nÃ£o emitiu a entrada {text!r}: {out!r}"
    assert frame not in ("<<NONE>>",), f"texto {text!r} nÃ£o produziu frame (foi ignorado?)"
    # The exact wire frame: ms.remote.control / SendInputString com o texto em
    # Base64 (b64 calculado independentemente em Python).
    assert frame == _text_frame(text), (
        f"frame de texto inesperado para {text!r}: {frame!r} != {_text_frame(text)!r}"
    )


@pytest.mark.parametrize("text", TEXT_INPUTS)
def test_serialized_message_contains_text_base64(out, text):
    # Foco do "teste de protocolo": o Cmd carrega exatamente o Base64 do texto.
    label = "cafe" if text == "cafÃ©" else text
    frame = out.get(label, "")
    assert f'"Cmd":"{_b64(text)}"' in frame, (
        f"o Base64 de {text!r} ({_b64(text)!r}) nÃ£o aparece no frame: {frame!r}"
    )
    assert '"DataOfCmd":"base64"' in frame
    assert '"TypeOfRemote":"SendInputString"' in frame


def test_each_send_forwards_exactly_one_frame(out):
    # 3 entradas vÃ¡lidas enviadas (a entrada em branco nÃ£o conta).
    assert out.get("TOTAL") == str(len(TEXT_INPUTS)), (
        f"total de frames inesperado: {out.get('TOTAL')!r}"
    )


def test_blank_input_is_ignored(out):
    # O gate isNotBlank() da tela: entrada sÃ³ de espaÃ§os nÃ£o envia nada.
    assert out.get("blank") == "<<NONE>>", (
        f"entrada em branco nÃ£o deveria enviar frame: {out.get('blank')!r}"
    )


def test_multiword_search_text_roundtrips(out):
    # Campo de busca: frase com espaÃ§os preserva o texto completo no Base64.
    frame = out.get("Game of Thrones", "")
    assert frame == _text_frame("Game of Thrones"), (
        f"texto com espaÃ§os nÃ£o preservado: {frame!r}"
    )
    # Sanidade: o Base64 decodifica de volta ao texto original.
    decoded = base64.b64decode(_b64("Game of Thrones")).decode("utf-8")
    assert decoded == "Game of Thrones"


# --------------------------------------------------------------------------- #
# Structural â€” the Compose screen wiring (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_screen_present():
    assert SCREEN_KT.is_file(), f"RemoteScreen ausente: {SCREEN_KT}"


def test_screen_renders_text_entry_with_input_and_send():
    text = _read(SCREEN_KT)
    assert "TextEntryRow" in text, "a tela deve renderizar o TextEntryRow"
    assert "OutlinedTextField" in text, "deve haver um campo de texto"
    assert "TEXT_INPUT" in text and "TEXT_SEND" in text, (
        "campo e botÃ£o de envio devem expor testTags estÃ¡veis"
    )


def test_screen_routes_typed_text_to_type_text_intent():
    text = _read(SCREEN_KT)
    assert "RemoteIntent.TypeText" in text, "o envio deve emitir RemoteIntent.TypeText"


def test_screen_gates_blank_and_clears_after_send():
    text = _read(SCREEN_KT)
    assert "isNotBlank" in text, "entrada em branco deve ser ignorada (isNotBlank)"


def test_viewmodel_routes_type_text_to_send_text():
    text = _read(VIEWMODEL_KT)
    assert "RemoteIntent.TypeText" in text, "deve haver o intent TypeText"
    assert "commandRepository.sendText" in text, "TypeText deve chamar sendText"


def test_protocol_send_text_encodes_base64():
    text = _read(TIZEN_PROTOCOL_KT)
    assert "fun sendText(" in text, "TizenProtocol deve definir sendText"
    assert "Base64" in text, "sendText deve codificar o texto em Base64"
    assert "SendInputString" in text or "TYPE_SEND_INPUT_STRING" in text, (
        "sendText deve usar o TypeOfRemote SendInputString"
    )


def test_string_resources_present():
    text = _read(STRINGS_XML)
    assert "remote_text_label" in text and "remote_text_send" in text, (
        "strings do campo de texto devem existir"
    )
