"""Tests for task d7903bbe — Verificação de latência toque→envio (caminho local).

Acceptance criterion (this file): "teste de latência confirma que o envio do
comando ocorre em < 150 ms no caminho simulado em LAN" — backing the
architecture's non-functional budget "toque → comando na TV < 150 ms na mesma
LAN" (docs/architecture.md).

What is measured
----------------
The *touch→send* path is the production hot path a button tap travels through:

    (toque) → CommandRepository.{sendKey,sendText,launchApp}
            → TizenProtocol serialises the frame
            → CommandTransport.send(frame)  (writes onto the LAN socket)

We drive the **real** ``CommandRepository`` + ``TizenProtocol`` and substitute a
``SimulatedLanTransport`` for the production ``RemoteSession`` (which *is* a
``CommandTransport``). The fake reproduces a same-subnet LAN socket write by
busy-waiting a jittered few-millisecond cost per frame (deterministic, seeded —
no wall-clock/RNG flakiness), so the measured interval is the genuine
end-to-end local-path cost, not a no-op.

For each message type we time many iterations (after warmup) and compute
p50/p95/p99/max. The suite asserts the whole distribution sits under the 150 ms
budget with a wide margin.

Strategy mirrors test_command_repository.py: compile the real sources against
pure ``javax.inject`` / ``org.json`` shims plus a timing harness, run it, and
assert on the reported percentiles. If no Kotlin/JDK toolchain is available the
behavioural test ``skip``s; structural checks always run.
"""

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

# Budget from the architecture's NFRs (toque → comando na TV < 150 ms na LAN).
BUDGET_MS = 150.0

# Message types exercised on the touch→send path.
MESSAGE_TYPES = ["key", "text", "launchApp"]


# --------------------------------------------------------------------------- #
# Shims — pure annotations + org.json (compact toString, insertion order).
# --------------------------------------------------------------------------- #
INJECT_SHIM = r'''package javax.inject

annotation class Inject
annotation class Singleton
annotation class Qualifier
'''

ORG_JSON_SHIM = r'''package org.json

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
        is String -> sb.append('"').append(escape(value)).append('"')
        is Boolean, is Int, is Long, is Double -> sb.append(value.toString())
        else -> sb.append('"').append(escape(value.toString())).append('"')
    }
}

class JSONObject {
    private val map = LinkedHashMap<String, Any?>()
    constructor()
    constructor(source: String) {
        val parser = JSONParser(source)
        val v = parser.parseValue()
        if (v !is JSONObject) throw RuntimeException("Not a JSON object")
        this.map.putAll(v.map)
    }
    fun put(name: String, value: Any?): JSONObject { map[name] = value; return this }
    fun has(name: String): Boolean = map.containsKey(name)
    fun isNull(name: String): Boolean { val v = map[name]; return v == null || v === NULL }
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
        return when (s[pos]) {
            '{' -> parseObject()
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
            pos++; val value = parseValue(); obj.putRaw(key, value); skipWhitespace()
            when (s[pos]) {
                ',' -> { pos++; continue }
                '}' -> { pos++; return obj }
                else -> throw RuntimeException("Expected ',' or '}' at $pos")
            }
        }
    }
    private fun parseString(): String {
        if (s[pos] != '"') throw RuntimeException("Expected string at $pos")
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
                        else -> sb.append(e)
                    }
                }
                else -> sb.append(c)
            }
        }
        throw RuntimeException("Unterminated string")
    }
    private fun parseBoolean(): Boolean = when {
        s.startsWith("true", pos) -> { pos += 4; true }
        s.startsWith("false", pos) -> { pos += 5; false }
        else -> throw RuntimeException("Invalid literal at $pos")
    }
    private fun parseNull(): Any {
        if (s.startsWith("null", pos)) { pos += 4; return NULL }
        throw RuntimeException("Invalid literal at $pos")
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
# Harness — times the REAL touch→send path through a simulated-LAN transport.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.data.registry.KeyCategory
import com.factory.samsungremote.data.registry.RemoteKey
import com.factory.samsungremote.data.repository.CommandRepository
import com.factory.samsungremote.network.session.CommandTransport
import java.util.Locale
import java.util.Random

/**
 * Stands in for the production RemoteSession (`RemoteSession : CommandTransport`)
 * and reproduces the cost of writing one frame onto a same-subnet LAN socket:
 * a jittered few-millisecond busy-wait. Seeded RNG keeps it deterministic so the
 * measurement is repeatable and free of wall-clock flakiness.
 */
class SimulatedLanTransport : CommandTransport {
    private val rnd = Random(424242L)
    var count = 0
    var minWriteNanos = Long.MAX_VALUE
    override fun send(frame: String): Boolean {
        // 1 ms .. ~9 ms, representative of a LAN frame write + jitter.
        val writeNanos = 1_000_000L + (rnd.nextDouble() * 8_000_000L).toLong()
        if (writeNanos < minWriteNanos) minWriteNanos = writeNanos
        val target = System.nanoTime() + writeNanos
        // Busy-wait: precise simulated network write (sleep granularity on some
        // OSes is too coarse to model a few-ms LAN write).
        while (System.nanoTime() < target) { /* spin */ }
        count++
        return true
    }
}

fun pct(sorted: LongArray, p: Double): Long {
    val rank = Math.ceil(p / 100.0 * sorted.size).toInt().coerceIn(1, sorted.size)
    return sorted[rank - 1]
}

fun ms(nanos: Long): String = String.format(Locale.US, "%.3f", nanos / 1_000_000.0)

fun measure(label: String, warmup: Int, iters: Int, action: () -> Boolean) {
    repeat(warmup) { if (!action()) throw RuntimeException("send false (warmup)") }
    val samples = LongArray(iters)
    for (i in 0 until iters) {
        val t0 = System.nanoTime()
        val ok = action()                 // toque → serialize → transport.send
        val t1 = System.nanoTime()
        if (!ok) throw RuntimeException("send returned false")
        samples[i] = t1 - t0
    }
    val sorted = samples.clone()
    java.util.Arrays.sort(sorted)
    println("LAT\t$label\titers\t$iters")
    println("LAT\t$label\tp50\t" + ms(pct(sorted, 50.0)))
    println("LAT\t$label\tp95\t" + ms(pct(sorted, 95.0)))
    println("LAT\t$label\tp99\t" + ms(pct(sorted, 99.0)))
    println("LAT\t$label\tmin\t" + ms(sorted[0]))
    println("LAT\t$label\tmax\t" + ms(sorted[sorted.size - 1]))
    println("LAT\t$label\tmean\t" + ms(samples.sum() / iters))
}

fun main() {
    val transport = SimulatedLanTransport()
    val repo = CommandRepository(transport)
    val volUp = RemoteKey("KEY_VOLUP", KeyCategory.VOLUME, "Vol+")

    val warmup = 40
    val iters = 120
    measure("key", warmup, iters) { repo.sendKey(volUp) }
    measure("text", warmup, iters) { repo.sendText("hello world") }
    measure("launchApp", warmup, iters) { repo.launchApp("11101200001") }

    println("LAT\tmeta\tbudget_ms\t" + String.format(Locale.US, "%.1f", 150.0))
    println("LAT\tmeta\tsimulated_min_write_ms\t" + ms(transport.minWriteNanos))
    println("LAT\tmeta\ttotal_sends\t" + transport.count)
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_command_repository.py).
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
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"], tc["annot"],
        tc["corout"],
    ))


def _parse_lat(stdout):
    """Parse 'LAT<TAB>label<TAB>metric<TAB>value' lines into {label: {metric: value}}."""
    out = {}
    for line in stdout.splitlines():
        line = line.rstrip("\r")
        parts = line.split("\t")
        if len(parts) == 4 and parts[0] == "LAT":
            _, label, metric, value = parts
            out.setdefault(label, {})[metric] = value
    return out


# --------------------------------------------------------------------------- #
# Behavioural fixture — compile real sources + timing harness, run once.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def lat(tmp_path_factory):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("toolchain/jars indisponíveis: " + ", ".join(tc["missing"]))
    for s in REAL_SOURCES:
        if not s.is_file():
            pytest.fail(f"fonte ausente: {s}")

    tmp = tmp_path_factory.mktemp("latency")
    src = tmp / "src"
    (src / "shims").mkdir(parents=True, exist_ok=True)
    (src / "shims" / "inject_shim.kt").write_text(INJECT_SHIM, encoding="utf-8")
    (src / "shims" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    (src / "Harness.kt").write_text(HARNESS_KT, encoding="utf-8")

    out_dir = tmp / "out"
    out_dir.mkdir(exist_ok=True)

    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", str(tc["stdlib"]),
        "-d", str(out_dir),
        str(src / "shims" / "inject_shim.kt"),
        str(src / "shims" / "json_shim.kt"),
        *[str(s) for s in REAL_SOURCES],
        str(src / "Harness.kt"),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilação do harness de latência falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in [out_dir, tc["stdlib"]])
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt"],
        capture_output=True, text=True, timeout=180,
    )
    assert run.returncode == 0, (
        "execução do harness de latência falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_lat(run.stdout)


# --------------------------------------------------------------------------- #
# Behavioural — touch→send stays under the 150 ms LAN budget for every type.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("msg_type", MESSAGE_TYPES)
def test_touch_to_send_under_budget(lat, msg_type):
    stats = lat.get(msg_type)
    assert stats, f"sem medições para o tipo de mensagem '{msg_type}'"
    p95 = float(stats["p95"])
    p99 = float(stats["p99"])
    mx = float(stats["max"])
    assert p95 < BUDGET_MS, f"[{msg_type}] p95={p95} ms excede o orçamento de {BUDGET_MS} ms"
    assert p99 < BUDGET_MS, f"[{msg_type}] p99={p99} ms excede o orçamento de {BUDGET_MS} ms"
    assert mx < BUDGET_MS, f"[{msg_type}] max={mx} ms excede o orçamento de {BUDGET_MS} ms"


@pytest.mark.parametrize("msg_type", MESSAGE_TYPES)
def test_mean_well_within_budget(lat, msg_type):
    mean = float(lat[msg_type]["mean"])
    # The local path should be nowhere near the ceiling on a LAN.
    assert mean < BUDGET_MS, f"[{msg_type}] média={mean} ms excede {BUDGET_MS} ms"


def test_latency_measurement_is_not_a_noop(lat):
    """The simulated LAN write must actually be exercised (else the test is vacuous)."""
    min_write = float(lat["meta"]["simulated_min_write_ms"])
    assert min_write >= 0.9, (
        f"escrita de LAN simulada não aplicada (min={min_write} ms); medição vazia"
    )
    # 3 message types × (warmup 40 + 120 iters) = 480 sends forwarded.
    assert lat["meta"]["total_sends"] == "480", (
        f"contagem de envios inesperada: {lat['meta'].get('total_sends')}"
    )


def test_budget_constant_matches_architecture(lat):
    assert float(lat["meta"]["budget_ms"]) == BUDGET_MS


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_touch_to_send_path_sources_present():
    for p in (REPO_KT, TRANSPORT_KT, TIZEN_PROTOCOL_KT, REMOTE_KEY_KT):
        assert p.is_file(), f"fonte do caminho toque→envio ausente: {p}"


def test_repository_is_on_the_send_path():
    text = REPO_KT.read_text(encoding="utf-8")
    assert "transport.send" in text, "CommandRepository deve escrever via transport.send"
    for fn in ("fun sendKey(", "fun sendText(", "fun launchApp("):
        assert fn in text, f"ação de envio ausente no repositório: {fn}"
