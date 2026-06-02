"""Tests for task f7ed960d — Teclado numérico.

Painel numérico (``KEY_0``..``KEY_9``) adicionado à tela de controle para troca
direta de canais — ligado ao ``RemoteViewModel``.

Acceptance criteria verificado aqui:
  **Teste de UI: tocar cada dígito envia o ``KEY_<n>`` correspondente via
  ViewModel fake.**

Como o runtime Compose não roda na JVM desktop, provamos *comportamentalmente* o
elo crítico exigido pelo aceite (seguindo a convenção do repositório —
``test_remote_media_controls.py`` / ``test_remote_volume_channel.py``): para CADA
um dos 10 dígitos (0..9), a tela resolve a tecla no ``RemoteKeyCatalog`` (pelo
mesmo código ``KEY_<n>`` que ``NumericKeys[n]`` usa) e, roteada pelo
``RemoteViewModel`` REAL ligado a um ``CommandTransport`` *fake* (gravador),
produz exatamente o frame ``SendRemoteKey`` com o ``DataOfCmd`` daquele dígito —
e os 10 frames são distintos (nenhum dígito fixado na tecla de outro). O
comportamento "toque → intent" sobre o runtime Compose é coberto pelo teste de
UI instrumentado real (ver ``test_compose_ui_test_covers_digits``).

Strategy
--------
Compilamos os fontes Kotlin reais (``RemoteKeyCatalog`` + ``RemoteViewModel`` +
``CommandRepository`` + ``RemoteSession`` + modelos + ``TizenProtocol``) contra
*shims* puros de ``javax.inject``, ``org.json``, ``androidx.lifecycle`` e
``dagger.hilt`` (mais ``kotlinx-coroutines`` + ``okhttp``/``okio`` reais para
construir a sessão). O harness percorre os 10 dígitos exatamente como a tela faz
(``NumericKeys[n] = key("KEY_$n")``), resolve cada tecla no catálogo e a roteia
pelo ViewModel real ligado a um transporte fake que grava os frames.

Se o toolchain Kotlin/JDK ou os jars não forem localizados nos caches do Gradle,
os testes comportamentais dão ``skip``; as asserções estruturais sempre rodam.
"""

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
CONNECTION_STATE_KT = SESSION_DIR / "ConnectionState.kt"
COMMAND_TRANSPORT_KT = SESSION_DIR / "CommandTransport.kt"

PROTO_DIR = PKG / "network" / "protocol"
TIZEN_PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
TIZEN_MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

REPO_KT = PKG / "data" / "repository" / "CommandRepository.kt"
REMOTE_KEY_KT = PKG / "data" / "registry" / "RemoteKey.kt"
REMOTE_KEY_CATALOG_KT = PKG / "data" / "registry" / "RemoteKeyCatalog.kt"
DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"

REAL_SOURCES = [
    VIEWMODEL_KT, REPO_KT,
    REMOTE_SESSION_KT, CONNECTION_STATE_KT, COMMAND_TRANSPORT_KT,
    TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT,
    REMOTE_KEY_KT, REMOTE_KEY_CATALOG_KT, DISCOVERED_TV_KT,
]

UI_TEST_KT = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "ui" / "remote" / "RemoteScreenTest.kt"
)

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# The ten numeric-keypad digits this task adds. This is the contract under test
# for the acceptance criteria: digit n -> KEY_<n> -> PressKey intent -> frame.
DIGITS = list(range(10))


def _code(digit: int) -> str:
    return f"KEY_{digit}"


def _key_frame(code: str) -> str:
    return (
        '{"method":"ms.remote.control","params":{"Cmd":"Click",'
        f'"DataOfCmd":"{code}","Option":"false","TypeOfRemote":"SendRemoteKey"}}}}'
    )


# --------------------------------------------------------------------------- #
# Shims — pure annotations, org.json, and the Android/Hilt symbols the
# ViewModel links against. (Shared, verbatim, with test_remote_media_controls.py
# so the real ViewModel/repository/session link without an Android runtime.)
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
# Harness — reproduces what the numeric keypad does for every digit: resolve the
# RemoteKey from RemoteKeyCatalog (by the same KEY_<n> code the screen's
# NumericKeys uses) and route RemoteIntent.PressKey(key) through the REAL
# RemoteViewModel, ligado a um transporte fake gravador. Emits "code|frame".
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.RemoteKeyCatalog
import com.factory.samsungremote.data.repository.CommandRepository
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

    // Exactly what the screen builds: NumericKeys[n] = key("KEY_$n"), and
    // DigitButton(n).onClick = onPress(NumericKeys[n]) -> PressKey via the fake.
    for (digit in 0..9) {
        val code = "KEY_$digit"
        val key = RemoteKeyCatalog.findByCode(code)
        if (key == null) { println("$code|<<MISSING>>"); continue }
        val before = transport.sent.size
        vm.onIntent(RemoteIntent.PressKey(key))
        val added = transport.sent.size - before
        val frame = if (added == 1) transport.sent[transport.sent.size - 1] else "<<added=$added>>"
        println("$code|$frame")
    }
    println("TOTAL|${transport.sent.size}")
    scope.cancel()
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_remote_media_controls.py).
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
    """Parse 'code|frame' harness lines into {code: frame}."""
    out = {}
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if "|" not in line:
            continue
        code, _, frame = line.partition("|")
        out[code.strip()] = frame
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

    tmp = tmp_path_factory.mktemp("remote_numeric")
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
        "compilação do harness do teclado numérico falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, *link_libs])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execução do harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_lines(run.stdout)


# --------------------------------------------------------------------------- #
# Acceptance (behavioural) — tapping each digit sends KEY_<n> (with fake).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("digit", DIGITS)
def test_each_digit_sends_its_key(out, digit):
    code = _code(digit)
    # The catalog lookup the screen performs must resolve (not <<MISSING>>)...
    frame = out.get(code)
    assert frame is not None, f"harness não emitiu o dígito {digit} ({code}): {out!r}"
    assert frame != "<<MISSING>>", f"tecla {code} ausente no RemoteKeyCatalog"
    # ...and tapping it emits exactly the SendRemoteKey frame for KEY_<n>.
    assert frame == _key_frame(code), (
        f"tocar o dígito {digit} não enviou o KEY_<n> correto: {frame!r}"
    )


def test_all_ten_digits_emit_distinct_frames(out):
    frames = [out.get(_code(d)) for d in DIGITS]
    assert all(f and f != "<<MISSING>>" for f in frames), f"dígito faltando: {frames!r}"
    # No digit is hard-coded to another's key — 10 digits, 10 distinct frames.
    assert len(set(frames)) == len(DIGITS), f"frames duplicados entre dígitos: {frames!r}"


def test_each_digit_press_forwards_exactly_one_frame(out):
    # 10 digits pressed once each -> exactly 10 frames.
    assert out.get("TOTAL") == str(len(DIGITS)), (
        f"total de frames inesperado: {out.get('TOTAL')!r}"
    )


# --------------------------------------------------------------------------- #
# Structural — the Compose screen wiring (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_screen_present():
    assert SCREEN_KT.is_file(), f"RemoteScreen ausente: {SCREEN_KT}"


def test_screen_defines_test_tag_for_every_digit():
    text = _read(SCREEN_KT)
    # The screen exposes a stable testTag per digit (RemoteTestTags.digit(n)).
    assert "fun digit(" in text, "RemoteTestTags deve expor um testTag por dígito (digit(n))"
    assert "testTag" in text, "os dígitos devem expor testTags estáveis"
    assert "RemoteTestTags.digit(" in text, "cada DigitButton deve usar RemoteTestTags.digit(n)"


def test_screen_resolves_digit_keys_from_catalog():
    # The screen must derive its digit keys from the catalog (not hard-code a
    # KEY_<n> string on a button), keeping it in sync with RemoteKeyCatalog.
    text = _read(SCREEN_KT)
    assert "RemoteKeyCatalog" in text, "a tela deve resolver teclas via RemoteKeyCatalog"
    assert "NumericKeys" in text, "a tela deve construir a lista NumericKeys (KEY_0..KEY_9)"
    assert 'key("KEY_$' in text, "NumericKeys deve resolver KEY_<n> dinamicamente do catálogo"


def test_screen_emits_press_key_intents_for_digits():
    text = _read(SCREEN_KT)
    assert "RemoteIntent.PressKey" in text, "cada dígito deve emitir RemoteIntent.PressKey"
    assert "NumericKeypad" in text, "a tela deve renderizar o NumericKeypad"


def test_catalog_contains_every_digit_key():
    text = _read(REMOTE_KEY_CATALOG_KT)
    for digit in DIGITS:
        assert f'"{_code(digit)}"' in text, f"catálogo não define a tecla {_code(digit)}"


# --------------------------------------------------------------------------- #
# Criterion (UI) — the instrumented Compose UI test artifact covers the keypad.
# --------------------------------------------------------------------------- #
def test_compose_ui_test_covers_digits():
    assert UI_TEST_KT.is_file(), f"teste de UI Compose ausente: {UI_TEST_KT}"
    text = _read(UI_TEST_KT)
    assert "createComposeRule" in text, "teste de UI deve usar createComposeRule"
    assert "setContent" in text and "RemoteScreen(" in text, "teste deve renderizar RemoteScreen"
    assert "performClick" in text, "teste deve tocar nos dígitos"
    assert "RemoteIntent.PressKey" in text, "teste deve verificar o intent disparado (com fake)"
    # Every digit's tag must be exercised by the UI test (RemoteTestTags.digit(n)).
    assert "RemoteTestTags.digit(" in text, (
        "teste de UI deve tocar cada dígito via RemoteTestTags.digit(n)"
    )
