"""Tests for task 38eb3b28 â€” Teclas de atalho de streaming.

Atalhos dedicados (Netflix / Prime Video / Disney+ / YouTube) adicionados Ã  tela
de controle. Cada atalho chama ``CommandRepository.launchApp(appId)`` (via
``RemoteIntent.LaunchApp`` no ``RemoteViewModel``) para o ``appId`` resolvido do
``AppShortcutCatalog``; quando o launch nÃ£o chega a uma conexÃ£o aberta, a tela
faz *fallback* para navegaÃ§Ã£o por tecla (``KEY_HOME``).

Acceptance criteria verificado aqui:
  **Teste de UI: tocar o atalho Netflix invoca ``launchApp('3201907018807')`` no
  ViewModel fake; os 4 atalhos disparam o ``appId`` correto; fallback acionado
  quando ``launchApp`` falha.**

Como o runtime Compose nÃ£o roda na JVM desktop, provamos *comportamentalmente* o
elo crÃ­tico exigido pelo aceite (seguindo a convenÃ§Ã£o do repositÃ³rio â€”
``test_remote_media_controls.py`` / ``test_remote_screen.py``): reproduzimos o
*exato* handler ``launch`` da tela. Para cada um dos 4 atalhos, resolvemos o
``AppShortcut`` no ``AppShortcutCatalog`` (pelos mesmos ``appId`` que a tela usa)
e roteamos ``RemoteIntent.LaunchApp(shortcut.appId)`` pelo ``RemoteViewModel``
REAL ligado a um ``CommandTransport`` *fake* (gravador) â€” produzindo exatamente o
frame ``ms.channel.emit`` / ``ed.apps.launch`` para aquele ``appId``, e os 4
frames sÃ£o distintos. Para o *fallback*, o transporte fake reporta "nÃ£o
conectado" (``send`` â†’ ``false``): o handler deve entÃ£o emitir um
``PressKey(KEY_HOME)`` apÃ³s o ``LaunchApp`` que falhou. O comportamento "toque â†’
intent" sobre o runtime Compose Ã© coberto pelo teste de UI instrumentado real
(ver ``test_compose_ui_test_covers_shortcuts``).

Strategy
--------
Compilamos os fontes Kotlin reais (``AppShortcut`` + ``AppShortcutCatalog`` +
``RemoteKeyCatalog`` + ``RemoteViewModel`` + ``CommandRepository`` +
``RemoteSession`` + modelos + ``TizenProtocol``) contra *shims* puros de
``javax.inject``, ``org.json``, ``androidx.lifecycle`` e ``dagger.hilt`` (mais
``kotlinx-coroutines`` + ``okhttp``/``okio`` reais para construir a sessÃ£o). O
harness reproduz o handler ``launch`` da tela duas vezes: caminho feliz
(conexÃ£o aberta) e caminho de falha (fallback).

Se o toolchain Kotlin/JDK ou os jars nÃ£o forem localizados nos caches do Gradle,
os testes comportamentais dÃ£o ``skip``; as asserÃ§Ãµes estruturais sempre rodam.
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
APP_SHORTCUT_KT = PKG / "data" / "registry" / "AppShortcut.kt"
APP_SHORTCUT_CATALOG_KT = PKG / "data" / "registry" / "AppShortcutCatalog.kt"
DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"

REAL_SOURCES = [
    VIEWMODEL_KT, REPO_KT,
    REMOTE_SESSION_KT, CONNECTION_STATE_KT, COMMAND_TRANSPORT_KT,
    TIZEN_PROTOCOL_KT, TIZEN_MESSAGE_KT,
    REMOTE_KEY_KT, REMOTE_KEY_CATALOG_KT,
    APP_SHORTCUT_KT, APP_SHORTCUT_CATALOG_KT,
    DISCOVERED_TV_KT,
]

UI_TEST_KT = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "ui" / "remote" / "RemoteScreenTest.kt"
)

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# The four streaming shortcuts this task adds, in the screen's display order:
#   (RemoteTestTags constant, Tizen appId, display name)
# This is the contract under test for the acceptance criteria:
#   tap shortcut -> RemoteIntent.LaunchApp(appId) -> launchApp(appId) frame.
SHORTCUTS = [
    ("APP_NETFLIX", "3201907018807", "Netflix"),
    ("APP_PRIME", "3201910019365", "Prime Video"),
    ("APP_DISNEY", "3201901017640", "Disney+"),
    ("APP_YOUTUBE", "111299001912", "YouTube"),
]

# The key the screen falls back to when an app fails to launch.
FALLBACK_CODE = "KEY_HOME"


def _launch_frame(app_id: str) -> str:
    """The ms.channel.emit / ed.apps.launch frame TizenProtocol builds for app_id."""
    return (
        '{"method":"ms.channel.emit","params":{"event":"ed.apps.launch","to":"host",'
        '"data":{"action_type":"DEEP_LINK","appId":"' + app_id + '"}}}'
    )


def _key_frame(code: str) -> str:
    """The ms.remote.control / SendRemoteKey frame for a key press."""
    return (
        '{"method":"ms.remote.control","params":{"Cmd":"Click",'
        f'"DataOfCmd":"{code}","Option":"false","TypeOfRemote":"SendRemoteKey"}}}}'
    )


# --------------------------------------------------------------------------- #
# Shims â€” pure annotations, org.json, and the Android/Hilt symbols the
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
# Harness â€” reproduces the screen's exact `launch` handler:
#
#   val launch: (AppShortcut) -> Unit = { shortcut ->
#       if (!onIntent(RemoteIntent.LaunchApp(shortcut.appId))) {
#           onIntent(RemoteIntent.PressKey(FallbackNavKey /* KEY_HOME */))
#       }
#   }
#
# Run twice over the REAL RemoteViewModel + a recording CommandTransport:
#  - happy path  (send -> true):  each shortcut launches its appId, no fallback.
#  - failure path (send -> false): launch fails -> KEY_HOME fallback fires.
# Emits parseable "key|value" lines.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.AppShortcut
import com.factory.samsungremote.data.registry.AppShortcutCatalog
import com.factory.samsungremote.data.registry.RemoteKeyCatalog
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

/** Records every frame; [connected] controls whether send() reports success. */
class FakeTransport(private val connected: Boolean) : CommandTransport {
    val sent = ArrayList<String>()
    override fun send(frame: String): Boolean { sent.add(frame); return connected }
}

/** Inert socket factory: the session is never connected in this harness. */
class NoopFactory : WebSocket.Factory {
    override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket =
        throw UnsupportedOperationException("not used")
}

// The four streaming shortcut appIds, in the screen's display order.
private val SHORTCUT_APP_IDS = listOf(
    "3201907018807",   // Netflix
    "3201910019365", // Prime Video
    "3201901017640", // Disney+
    "111299001912",  // YouTube
)

private const val FALLBACK_CODE = "KEY_HOME"

@OptIn(ExperimentalCoroutinesApi::class)
fun main() {
    // The screen's exact `launch` handler: route LaunchApp(shortcut.appId) and,
    // when it does not reach an open connection, fall back to PressKey(KEY_HOME).
    fun launch(vm: RemoteViewModel, shortcut: AppShortcut) {
        if (!vm.onIntent(RemoteIntent.LaunchApp(shortcut.appId))) {
            vm.onIntent(RemoteIntent.PressKey(RemoteKeyCatalog.findByCode(FALLBACK_CODE)!!))
        }
    }

    // --- Happy path: connection open, each shortcut launches its app id. ---
    run {
        val transport = FakeTransport(connected = true)
        val scope = CoroutineScope(StandardTestDispatcher(TestCoroutineScheduler()))
        val vm = RemoteViewModel(CommandRepository(transport), RemoteSession(NoopFactory(), scope))
        for (appId in SHORTCUT_APP_IDS) {
            // Mirror the screen: resolve the shortcut from the catalog by appId.
            val shortcut = AppShortcutCatalog.findByAppId(appId)
            if (shortcut == null) { println("LAUNCH_$appId|<<MISSING>>"); continue }
            val before = transport.sent.size
            launch(vm, shortcut)
            val added = transport.sent.size - before
            val frame = if (added == 1) transport.sent[transport.sent.size - 1] else "<<added=$added>>"
            println("LAUNCH_$appId|$frame")
        }
        println("LAUNCH_TOTAL|${transport.sent.size}")
        scope.cancel()
    }

    // --- Failure path: not connected, launch fails -> KEY_HOME fallback. ---
    run {
        val transport = FakeTransport(connected = false)
        val scope = CoroutineScope(StandardTestDispatcher(TestCoroutineScheduler()))
        val vm = RemoteViewModel(CommandRepository(transport), RemoteSession(NoopFactory(), scope))
        val netflix = AppShortcutCatalog.findByAppId("3201907018807")
        if (netflix == null) {
            println("FB_COUNT|<<MISSING>>")
        } else {
            launch(vm, netflix)
            println("FB_COUNT|${transport.sent.size}")
            for ((i, f) in transport.sent.withIndex()) println("FB_$i|$f")
        }
        scope.cancel()
    }
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
    """Parse 'key|value' harness lines into {key: value}."""
    out = {}
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if "|" not in line:
            continue
        key, _, value = line.partition("|")
        out[key.strip()] = value
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

    tmp = tmp_path_factory.mktemp("remote_shortcuts")
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
        "compilaÃ§Ã£o do harness de atalhos falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
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
# Acceptance (behavioural) â€” each shortcut launches its app id (with fake).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("_tag,app_id,_name", SHORTCUTS)
def test_each_shortcut_launches_its_app_id(out, _tag, app_id, _name):
    # The catalog lookup the screen performs must resolve (not <<MISSING>>)...
    frame = out.get(f"LAUNCH_{app_id}")
    assert frame is not None, f"harness nÃ£o emitiu o atalho {app_id}: {out!r}"
    assert frame != "<<MISSING>>", f"appId {app_id} ausente no AppShortcutCatalog"
    # ...and tapping it launches exactly that app id (ed.apps.launch frame).
    assert frame == _launch_frame(app_id), (
        f"atalho {app_id} nÃ£o roteou o launchApp correto: {frame!r}"
    )


def test_netflix_shortcut_invokes_launch_app_3201907018807(out):
    # The acceptance criteria calls out Netflix explicitly.
    frame = out.get("LAUNCH_3201907018807")
    assert frame is not None and frame != "<<MISSING>>", (
        f"atalho Netflix nÃ£o emitido: {out!r}"
    )
    assert frame == _launch_frame("3201907018807"), (
        f"tocar Netflix deve invocar launchApp('3201907018807'): {frame!r}"
    )


def test_all_four_shortcuts_emit_distinct_app_frames(out):
    frames = [out.get(f"LAUNCH_{a}") for _t, a, _n in SHORTCUTS]
    assert all(f and f != "<<MISSING>>" for f in frames), f"atalho faltando: {frames!r}"
    # No shortcut is hard-coded to another's appId â€” 4 shortcuts, 4 distinct frames.
    assert len(set(frames)) == len(SHORTCUTS), f"frames duplicados entre atalhos: {frames!r}"


def test_successful_launch_forwards_exactly_one_frame_each(out):
    # 4 shortcuts, connection open -> exactly 4 frames, none triggered a fallback.
    assert out.get("LAUNCH_TOTAL") == str(len(SHORTCUTS)), (
        f"total de frames inesperado no caminho feliz: {out.get('LAUNCH_TOTAL')!r}"
    )


def test_fallback_to_home_key_when_launch_fails(out):
    # Launch fails (no open connection): the handler emits the LaunchApp frame,
    # then falls back to a KEY_HOME press so the user can navigate to the app.
    assert out.get("FB_COUNT") == "2", (
        f"fallback deveria produzir 2 frames (launch + home), veio: {out.get('FB_COUNT')!r}"
    )
    assert out.get("FB_0") == _launch_frame("3201907018807"), (
        f"primeiro frame do fallback deve ser o launchApp que falhou: {out.get('FB_0')!r}"
    )
    assert out.get("FB_1") == _key_frame(FALLBACK_CODE), (
        f"fallback deve acionar uma tecla {FALLBACK_CODE}: {out.get('FB_1')!r}"
    )


# --------------------------------------------------------------------------- #
# Structural â€” the Compose screen wiring (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_screen_present():
    assert SCREEN_KT.is_file(), f"RemoteScreen ausente: {SCREEN_KT}"


def test_screen_defines_test_tags_for_every_shortcut():
    text = _read(SCREEN_KT)
    for tag, _app_id, _name in SHORTCUTS:
        assert tag in text, f"test tag '{tag}' ausente na tela"
    assert "testTag" in text, "os atalhos devem expor testTags estÃ¡veis"


def test_screen_uses_launch_app_intent():
    text = _read(SCREEN_KT)
    assert "RemoteIntent.LaunchApp" in text, "cada atalho deve emitir RemoteIntent.LaunchApp"


def test_screen_resolves_shortcuts_from_catalog_by_app_id():
    # The screen must derive its shortcuts from the catalog (not hard-code the
    # AppShortcut), keeping it in sync with AppShortcutCatalog.
    text = _read(SCREEN_KT)
    assert "AppShortcutCatalog" in text, "a tela deve resolver atalhos via AppShortcutCatalog"
    for _tag, app_id, _name in SHORTCUTS:
        assert app_id in text, f"appId {app_id} nÃ£o referenciado pela tela"


def test_screen_falls_back_to_home_key_on_launch_failure():
    text = _read(SCREEN_KT)
    # The fallback hinges on onIntent reporting whether the frame reached an
    # open connection; the screen presses KEY_HOME when it did not.
    assert "onIntent: (RemoteIntent) -> Boolean" in text, (
        "onIntent deve retornar Boolean para sinalizar falha de launch"
    )
    assert FALLBACK_CODE in text, f"a tela deve fazer fallback para {FALLBACK_CODE}"
    assert "RemoteIntent.PressKey" in text, "o fallback deve disparar uma PressKey"


def test_catalog_contains_every_shortcut_app_id():
    text = _read(APP_SHORTCUT_CATALOG_KT)
    for _tag, app_id, _name in SHORTCUTS:
        assert f'"{app_id}"' in text, f"catÃ¡logo nÃ£o define o appId {app_id}"


# --------------------------------------------------------------------------- #
# Criterion (UI) â€” the instrumented Compose UI test artifact covers shortcuts.
# --------------------------------------------------------------------------- #
def test_compose_ui_test_covers_shortcuts():
    assert UI_TEST_KT.is_file(), f"teste de UI Compose ausente: {UI_TEST_KT}"
    text = _read(UI_TEST_KT)
    assert "createComposeRule" in text, "teste de UI deve usar createComposeRule"
    assert "setContent" in text and "RemoteScreen(" in text, "teste deve renderizar RemoteScreen"
    assert "performClick" in text, "teste deve tocar nos atalhos"
    # The acceptance criteria: tapping a shortcut invokes launchApp (LaunchApp intent).
    assert "RemoteIntent.LaunchApp" in text, (
        "teste de UI deve verificar que tocar o atalho dispara RemoteIntent.LaunchApp (com fake)"
    )
    # Every streaming shortcut's tag must be exercised by the UI test.
    for tag, _app_id, _name in SHORTCUTS:
        assert f"RemoteTestTags.{tag}" in text, (
            f"teste de UI nÃ£o cobre o atalho {tag}"
        )
    # The fallback-on-failure branch must be exercised too.
    assert FALLBACK_CODE in text or "PressKey" in text, (
        "teste de UI deve cobrir o fallback por tecla quando o launch falha"
    )
