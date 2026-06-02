"""Tests for task 1f5263f1 — DiscoveryService via SSDP/mDNS.

Acceptance criteria verified here (behaviourally):
  1. A fake HTTP server's ``GET /api/v2/`` Samsung response is parsed into a TV
     model (id, name/model, IP) by the real ``SamsungDeviceInfoParser`` — and a
     non-Samsung / invalid response is rejected.
  2. End-to-end discovery over a **fake UDP (SSDP) server + fake HTTP server**:
     the real ``SsdpCandidateSource`` -> ``RestTvCandidateValidator`` (OkHttp) ->
     ``DiscoveryService`` pipeline emits the Samsung TV, and it surfaces in
     ``< 5 s`` on the simulated happy path.

Strategy
--------
The discovery code is Kotlin and leans on ``org.json`` (Android at runtime),
OkHttp and kotlinx-coroutines. To exercise the *real* code on a desktop JVM we
compile the discovery sources together with a tiny, behaviour-compatible
``org.json`` shim (same semantics as Android's org.json for the ops used) and a
small harness, then run it and assert on the output.

``MdnsCandidateSource`` is intentionally **excluded** from compilation: it is the
only file that depends on the Android framework (``NsdManager``) and cannot link
on a plain JVM. The mDNS *fallback wiring* in ``DiscoveryService`` is exercised
through the ``TvCandidateSource`` fun-interface (a fake source), and the real
mDNS source is checked structurally.

For criterion 2 the test stands up two real fake servers on loopback:
  * a UDP responder bound to ``127.0.0.1`` that answers any ``M-SEARCH`` with an
    SSDP ``200 OK`` whose ``LOCATION`` points at the fake HTTP server, and
  * an HTTP server that serves a Samsung ``/api/v2/`` device-info document.
``SsdpCandidateSource`` is pointed at the UDP server (its multicast group/port
are constructor params), so the genuine SSDP send/receive/parse path runs, then
the genuine OkHttp validator fetches and parses the HTTP body, then the genuine
``DiscoveryService`` emits the de-duplicated TV — all measured for the ``< 5 s``
budget.

If no Kotlin toolchain / required jars can be located in the Gradle caches (or no
JDK is available) the behavioural tests ``skip`` rather than fail; the structural
fallbacks always run.
"""

import os
import re
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DISC_DIR = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory"
    / "samsungremote" / "network" / "discovery"
)

DISCOVERED_TV_KT = DISC_DIR / "DiscoveredTv.kt"
PARSER_KT = DISC_DIR / "SamsungDeviceInfoParser.kt"
SOURCE_IFACE_KT = DISC_DIR / "TvCandidateSource.kt"
VALIDATOR_IFACE_KT = DISC_DIR / "TvCandidateValidator.kt"
REST_VALIDATOR_KT = DISC_DIR / "RestTvCandidateValidator.kt"
SSDP_SOURCE_KT = DISC_DIR / "SsdpCandidateSource.kt"
MDNS_SOURCE_KT = DISC_DIR / "MdnsCandidateSource.kt"
SERVICE_KT = DISC_DIR / "DiscoveryService.kt"

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


# --------------------------------------------------------------------------- #
# Embedded org.json shim (insertion-ordered, JSON-null sentinel) — identical
# semantics to Android's org.json for the operations the parser uses.
# --------------------------------------------------------------------------- #
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
# Harness 1 — pure parser (no network, no coroutines)
# --------------------------------------------------------------------------- #
PARSER_HARNESS_KT = r'''import com.factory.samsungremote.network.discovery.SamsungDeviceInfoParser
import com.factory.samsungremote.network.discovery.DiscoveredTv

fun emit(key: String, tv: DiscoveredTv?) {
    if (tv == null) {
        println("$key=<null>")
    } else {
        println("$key|id=${tv.id}|name=${tv.name}|ip=${tv.ipAddress}|model=${tv.modelName ?: "<null>"}")
    }
}

fun main() {
    val samsung = """{"device":{"id":"uuid:abc-123","name":"[TV] Living Room","modelName":"UN50MU6300","type":"Samsung SmartTV","OS":"Tizen","ip":"192.168.1.50","wifiMac":"aa:bb:cc:dd:ee:ff"},"id":"uuid:abc-123","name":"[TV] Living Room","type":"Samsung SmartTV","version":"2.0.25"}"""
    emit("samsung", SamsungDeviceInfoParser.parse(samsung, "10.0.0.1"))

    val fallbackIp = """{"device":{"id":"uuid:xyz","name":"[TV] Bedroom","modelName":"QN90A","type":"Samsung SmartTV","OS":"Tizen"},"name":"[TV] Bedroom"}"""
    emit("fallbackip", SamsungDeviceInfoParser.parse(fallbackIp, "10.0.0.7"))

    val tizenOnly = """{"device":{"id":"uuid:tz","name":"Kitchen","type":"Smart Device","OS":"Tizen","ip":"10.0.0.9"}}"""
    emit("tizen", SamsungDeviceInfoParser.parse(tizenOnly, "10.0.0.1"))

    val nonSamsung = """{"device":{"id":"uuid:lg","name":"LG TV","type":"webOS TV","OS":"webOS","ip":"10.0.0.8"}}"""
    emit("nonsamsung", SamsungDeviceInfoParser.parse(nonSamsung, "10.0.0.1"))

    emit("invalid", SamsungDeviceInfoParser.parse("not-a-json", "10.0.0.1"))
}
'''

# --------------------------------------------------------------------------- #
# Harness 2 — full pipeline (real SSDP source + OkHttp validator + service)
#   args[0] = HTTP port, args[1] = UDP (fake SSDP) port
# --------------------------------------------------------------------------- #
E2E_HARNESS_KT = r'''import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.discovery.DiscoveryService
import com.factory.samsungremote.network.discovery.RestTvCandidateValidator
import com.factory.samsungremote.network.discovery.SsdpCandidateSource
import com.factory.samsungremote.network.discovery.TvCandidateSource
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

fun main(args: Array<String>) {
    val httpPort = args[0].toInt()
    val udpPort = args[1].toInt()

    val client = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    // Point the REAL SSDP source at the fake UDP server on loopback.
    val ssdp = SsdpCandidateSource(
        multicastGroup = "127.0.0.1",
        multicastPort = udpPort,
        responseTimeoutMs = 3000,
    )
    // mDNS fallback wiring is exercised via the fun-interface (no Android needed).
    val mdns = TvCandidateSource { emptyFlow() }
    val validator = RestTvCandidateValidator(
        client = client,
        port = httpPort,
        scheme = "http",
    )
    // Long fallback timeout so the SSDP happy path is what we measure.
    val service = DiscoveryService(ssdp, mdns, validator, ssdpFallbackTimeoutMs = 60_000L)

    runBlocking {
        val start = System.nanoTime()
        val tv: DiscoveredTv? = withTimeoutOrNull(5_000L) { service.discover().first() }
        val elapsedMs = (System.nanoTime() - start) / 1_000_000
        if (tv == null) {
            println("e2e_status=timeout")
            println("e2e_elapsed_ms=$elapsedMs")
        } else {
            println("e2e_status=ok")
            println("e2e_id=${tv.id}")
            println("e2e_name=${tv.name}")
            println("e2e_ip=${tv.ipAddress}")
            println("e2e_model=${tv.modelName ?: "<null>"}")
            println("e2e_elapsed_ms=$elapsedMs")
        }
    }
}
'''

SAMSUNG_API_V2_BODY = (
    '{"device":{"id":"uuid:e2e-777","name":"[TV] Office","modelName":"QN65Q80B",'
    '"type":"Samsung SmartTV","OS":"Tizen","ip":"127.0.0.1",'
    '"wifiMac":"aa:bb:cc:dd:ee:01"},"id":"uuid:e2e-777","name":"[TV] Office",'
    '"type":"Samsung SmartTV","version":"2.0.25"}'
)


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors test_tizen_protocol.py)
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
            name = p.name.lower()
            if any(x in name for x in exclude):
                continue
            matches.append(p)
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.name)[-1]


def _compiler_toolchain():
    """Pieces needed to *compile* Kotlin with the embeddable compiler.

    ``kotlin-compiler-embeddable`` 2.x references kotlinx-coroutines at runtime,
    so it must sit on the *compiler* classpath (mirrors test_tizen_protocol.py).
    """
    java = _java_exe()
    emb = _find_jar("kotlin-compiler-embeddable-*.jar")
    stdlib = _find_jar("kotlin-stdlib-1*.jar", "kotlin-stdlib-2*.jar")
    scrt = _find_jar("kotlin-script-runtime-*.jar")
    refl = _find_jar("kotlin-reflect-*.jar")
    trove = _find_jar("trove4j-*.jar")
    annot = _find_jar("annotations-13*.jar")
    corout = _find_jar("kotlinx-coroutines-core-jvm-*.jar")
    tc = {
        "java": java, "emb": emb, "stdlib": stdlib, "scrt": scrt,
        "refl": refl, "trove": trove, "annot": annot, "corout": corout,
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _runtime_libs():
    """Extra libraries the discovery code links against (OkHttp stack)."""
    okhttp = _find_jar("okhttp-4*.jar", "okhttp-3*.jar", "okhttp-5*.jar")
    okio = _find_jar("okio-jvm-*.jar")
    libs = {"okhttp": okhttp, "okio": okio}
    libs["missing"] = [n for n, v in libs.items() if not v]
    return libs


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"],
        tc["annot"], tc["corout"],
    ))


def _compile(tmp_path, sources, extra_libs, label):
    """Compile *sources* (list of Path) + the org.json shim into a classes dir.

    Returns (out_dir, link_classpath_list). Skips if toolchain/libs missing.
    """
    tc = _compiler_toolchain()
    if tc["missing"]:
        pytest.skip("Kotlin/JDK toolchain unavailable: missing " + ", ".join(tc["missing"]))
    for s in sources:
        if not s.is_file():
            pytest.fail(f"fonte de discovery ausente: {s}")

    src = tmp_path / "src"
    (src / "org" / "json").mkdir(parents=True, exist_ok=True)
    (src / "org" / "json" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)

    # -classpath for the code under compilation = stdlib + extra link libs.
    link_libs = [tc["stdlib"]] + [p for p in extra_libs if p]
    compile_cp = os.pathsep.join(str(p) for p in link_libs)

    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", compile_cp,
        "-d", str(out),
        str(src / "org" / "json" / "json_shim.kt"),
        *[str(s) for s in sources],
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        f"compilação de discovery ({label}) falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )
    run_cp = [out, tc["stdlib"]] + [p for p in extra_libs if p]
    return out, run_cp, tc


def _parse_kv_lines(stdout):
    """Parse 'key=value' and 'key|id=..|name=..' harness output into a dict."""
    out = {}
    for line in stdout.splitlines():
        line = line.rstrip("\r")
        if line.startswith(tuple("abcdefghijklmnopqrstuvwxyz")) is False:
            pass
        if "|" in line and "=" not in line.split("|", 1)[0]:
            key, _, rest = line.partition("|")
            fields = {}
            for chunk in rest.split("|"):
                if "=" in chunk:
                    k, _, v = chunk.partition("=")
                    fields[k] = v
            out[key.strip()] = fields
        elif "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v
    return out


# --------------------------------------------------------------------------- #
# Criterion 1 — parser turns a Samsung /api/v2/ response into a TV model
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def parser_out(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("disc_parser")
    sources = [DISCOVERED_TV_KT, PARSER_KT]
    out, run_cp, tc = _compile(tmp, sources, extra_libs=[], label="parser")

    harness = tmp / "src" / "ParserHarness.kt"
    harness.write_text(PARSER_HARNESS_KT, encoding="utf-8")
    # Re-compile including the harness.
    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", str(tc["stdlib"]),
        "-d", str(out),
        str(tmp / "src" / "org" / "json" / "json_shim.kt"),
        str(DISCOVERED_TV_KT), str(PARSER_KT), str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, "compilação do parser harness falhou:\n" + (cr.stdout or "") + (cr.stderr or "")

    run = subprocess.run(
        [tc["java"], "-cp", os.pathsep.join(str(p) for p in run_cp), "ParserHarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, "execução do parser harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    return _parse_kv_lines(run.stdout)


def test_parses_samsung_api_v2_into_tv_model(parser_out):
    tv = parser_out.get("samsung")
    assert isinstance(tv, dict), f"esperado modelo de TV, veio: {parser_out.get('samsung')!r}"
    assert tv["id"] == "uuid:abc-123"
    assert tv["name"] == "[TV] Living Room"
    assert tv["ip"] == "192.168.1.50"
    assert tv["model"] == "UN50MU6300"


def test_uses_fallback_ip_when_device_ip_absent(parser_out):
    tv = parser_out.get("fallbackip")
    assert isinstance(tv, dict)
    assert tv["id"] == "uuid:xyz"
    assert tv["ip"] == "10.0.0.7"  # fallback (request target) used
    assert tv["model"] == "QN90A"


def test_accepts_tizen_os_even_without_samsung_type(parser_out):
    tv = parser_out.get("tizen")
    assert isinstance(tv, dict)
    assert tv["id"] == "uuid:tz"
    assert tv["name"] == "Kitchen"
    assert tv["ip"] == "10.0.0.9"


def test_rejects_non_samsung_responder(parser_out):
    assert parser_out.get("nonsamsung") == "<null>"


def test_rejects_invalid_json(parser_out):
    assert parser_out.get("invalid") == "<null>"


# --------------------------------------------------------------------------- #
# Fake servers for the end-to-end discovery test
# --------------------------------------------------------------------------- #
class _SamsungHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/api/v2":
            body = SAMSUNG_API_V2_BODY.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence
        return


class _FakeServers:
    """A loopback HTTP server (/api/v2/) + UDP SSDP responder."""

    def __init__(self):
        self.http = HTTPServer(("127.0.0.1", 0), _SamsungHandler)
        self.http_port = self.http.server_address[1]
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp_port = self.udp.getsockname()[1]
        self.udp.settimeout(0.3)
        self._stop = threading.Event()
        self._threads = []

    def _serve_http(self):
        while not self._stop.is_set():
            self.http.handle_request()

    def _serve_udp(self):
        response = (
            "HTTP/1.1 200 OK\r\n"
            "CACHE-CONTROL: max-age=1800\r\n"
            "EXT:\r\n"
            f"LOCATION: http://127.0.0.1:{self.http_port}/api/v2/\r\n"
            "SERVER: Tizen/2.0 UPnP/1.0\r\n"
            "ST: urn:samsung.com:device:RemoteControlReceiver:1\r\n"
            "USN: uuid:e2e-777::urn:samsung.com:device:RemoteControlReceiver:1\r\n"
            "\r\n"
        ).encode("ascii")
        while not self._stop.is_set():
            try:
                data, addr = self.udp.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if b"M-SEARCH" in data:
                try:
                    self.udp.sendto(response, addr)
                except OSError:
                    pass

    def start(self):
        self.http.timeout = 0.3
        for target in (self._serve_http, self._serve_udp):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        try:
            self.http.server_close()
        except Exception:
            pass
        try:
            self.udp.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Criterion 2 — full pipeline finds the TV via fake SSDP+HTTP in < 5 s
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def e2e_out(tmp_path_factory):
    libs = _runtime_libs()
    if libs["missing"]:
        pytest.skip("bibliotecas de runtime ausentes: " + ", ".join(libs["missing"]))

    tmp = tmp_path_factory.mktemp("disc_e2e")
    tc = _compiler_toolchain()
    if tc["missing"]:
        pytest.skip("Kotlin/JDK toolchain unavailable: missing " + ", ".join(tc["missing"]))

    extra = [tc["corout"], libs["okhttp"], libs["okio"]]
    sources = [
        DISCOVERED_TV_KT, SOURCE_IFACE_KT, VALIDATOR_IFACE_KT, PARSER_KT,
        REST_VALIDATOR_KT, SSDP_SOURCE_KT, SERVICE_KT,
    ]
    src = tmp / "src"
    (src / "org" / "json").mkdir(parents=True, exist_ok=True)
    (src / "org" / "json" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    harness = src / "E2EHarness.kt"
    harness.write_text(E2E_HARNESS_KT, encoding="utf-8")
    out = tmp / "out"
    out.mkdir(exist_ok=True)

    compile_cp = os.pathsep.join(str(p) for p in [tc["stdlib"], *extra])
    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", compile_cp,
        "-d", str(out),
        str(src / "org" / "json" / "json_shim.kt"),
        *[str(s) for s in sources],
        str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilação do pipeline de discovery falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    servers = _FakeServers()
    servers.start()
    try:
        run_cp = os.pathsep.join(str(p) for p in [out, tc["stdlib"], *extra])
        run = subprocess.run(
            [tc["java"], "-cp", run_cp, "E2EHarnessKt",
             str(servers.http_port), str(servers.udp_port)],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        servers.stop()
    assert run.returncode == 0, (
        "execução do pipeline de discovery falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_kv_lines(run.stdout)


def test_discovery_emits_samsung_tv_from_fake_ssdp_and_http(e2e_out):
    assert e2e_out.get("e2e_status") == "ok", f"discovery não emitiu TV: {e2e_out!r}"
    assert e2e_out.get("e2e_id") == "uuid:e2e-777"
    assert e2e_out.get("e2e_name") == "[TV] Office"
    assert e2e_out.get("e2e_ip") == "127.0.0.1"
    assert e2e_out.get("e2e_model") == "QN65Q80B"


def test_discovery_happy_path_under_5s(e2e_out):
    assert e2e_out.get("e2e_status") == "ok"
    elapsed = int(e2e_out["e2e_elapsed_ms"])
    assert elapsed < 5000, f"descoberta demorou {elapsed} ms (orçamento < 5000 ms)"


# --------------------------------------------------------------------------- #
# Structural fallbacks (always run, no toolchain required)
# --------------------------------------------------------------------------- #
def test_discovery_sources_present():
    for p in (
        DISCOVERED_TV_KT, PARSER_KT, SOURCE_IFACE_KT, VALIDATOR_IFACE_KT,
        REST_VALIDATOR_KT, SSDP_SOURCE_KT, MDNS_SOURCE_KT, SERVICE_KT,
    ):
        assert p.is_file(), f"fonte ausente: {p}"


def test_service_emits_flow_and_dedupes():
    text = SERVICE_KT.read_text(encoding="utf-8")
    assert "fun discover(): Flow<DiscoveredTv>" in text, "discover() deve emitir um Flow de TVs"
    assert "validator.validate(" in text, "service deve validar candidatos via REST"
    assert "seenIds" in text and ".add(" in text, "service deve de-duplicar por id"


def test_service_falls_back_to_mdns_when_ssdp_silent():
    text = SERVICE_KT.read_text(encoding="utf-8")
    # mDNS only starts after the SSDP grace window if SSDP produced nothing.
    assert "ssdpFallbackTimeoutMs" in text
    assert "mdnsSource.candidates()" in text
    assert "ssdpProducedCandidate" in text


def test_rest_validator_targets_api_v2_with_okhttp():
    text = REST_VALIDATOR_KT.read_text(encoding="utf-8")
    assert "/api/v2/" in text, "validator deve consultar GET /api/v2/"
    assert "OkHttpClient" in text and "newCall" in text, "validator deve usar OkHttp"
    assert "SamsungDeviceInfoParser" in text, "validator deve delegar o parse"


def test_ssdp_source_uses_multicast_udp():
    text = SSDP_SOURCE_KT.read_text(encoding="utf-8")
    assert "MulticastSocket" in text and "DatagramPacket" in text
    assert "239.255.255.250" in text and "1900" in text
    assert "M-SEARCH" in text


def test_mdns_source_uses_nsd_browse():
    text = MDNS_SOURCE_KT.read_text(encoding="utf-8")
    assert "NsdManager" in text
    assert "discoverServices" in text and "PROTOCOL_DNS_SD" in text
    assert "_samsungmsf._tcp." in text
