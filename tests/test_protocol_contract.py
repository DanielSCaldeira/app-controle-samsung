"""Tests for task d7903bbe — Testes de contrato (versionados) do protocolo.

Acceptance criterion (this file): "Suite de contrato passa para todos os tipos
de mensagem".

What makes this a *versioned contract* suite
--------------------------------------------
The wire format is frozen in ``tests/contracts/tizen_protocol_v<N>.json`` — a
golden snapshot of the exact JSON the ``protocol/`` layer must emit for every
domain action, and exactly what the parser must extract from incoming TV
messages. The architecture pins this responsibility explicitly: "Camada
``protocol/`` isolada e versionada; testes de contrato" (docs/architecture.md),
backing ADR-0003 (the Samsung Tizen protocol is undocumented and may drift).

The contract file is the single source of truth. This test is generic: it loads
the contract, drives the **real** ``TizenProtocol`` through a small Kotlin
harness for *every* case in the file, and asserts each produced value equals the
pinned ``expected``. Adding cases means editing only the JSON. A breaking
protocol revision must land as a NEW versioned file (``..._v3.json``) rather than
by mutating these snapshots — that is what "versionado" buys us.

Strategy (mirrors test_tizen_protocol.py)
-----------------------------------------
``TizenProtocol`` depends on ``org.json`` (present on Android, absent on a desktop
JVM). We compile the real sources together with a behaviour-compatible
``org.json`` shim (insertion-ordered objects, compact ``toString()``) plus a
harness that reads the contract JSON and runs each case, then assert on stdout.

If no Kotlin/JDK toolchain is found in the Gradle caches the behavioural cases
``skip``; the structural checks over the contract file always run.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory"
    / "samsungremote" / "network" / "protocol"
)
PROTOCOL_KT = PROTO_DIR / "TizenProtocol.kt"
MESSAGE_KT = PROTO_DIR / "TizenMessage.kt"

CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"
CONTRACT_FILE = CONTRACTS_DIR / "tizen_protocol_v2.json"

GRADLE_CACHES = Path.home() / ".gradle" / "caches"

# Sentinel printed by the harness for a Kotlin ``null`` (distinguishes a real
# null from the literal string "null" a parser might emit). Kept in sync with the
# ``NULL_SENTINEL`` constant in HARNESS_KT below.
NULL_SENTINEL = "<<NULL>>"


# --------------------------------------------------------------------------- #
# Embedded org.json shim (+ keys() so the harness can iterate cases generically)
# + harness that executes EVERY contract case against the real protocol.
# --------------------------------------------------------------------------- #
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
    fun keys(): List<String> = ArrayList(map.keys)
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

# Reads the contract JSON (path = args[0]) and runs EVERY case against the real
# TizenProtocol, printing TAB-delimited "kind<TAB>name<TAB>value" lines. A null
# result is emitted as the NULL sentinel so the Python side can tell it apart
# from the literal string "null".
HARNESS_KT = r'''import com.factory.samsungremote.network.protocol.TizenProtocol
import com.factory.samsungremote.network.protocol.TizenCommand
import com.factory.samsungremote.network.protocol.LaunchActionType
import org.json.JSONObject
import java.io.File

const val NULL_SENTINEL = "<<NULL>>"

fun emit(kind: String, name: String, value: String?) {
    println(kind + "\t" + name + "\t" + (value ?: NULL_SENTINEL))
}

fun runSend(op: String, args: JSONObject): String = when (op) {
    "sendKey" -> TizenProtocol.sendKey(
        args.optString("keyCode"),
        TizenCommand.valueOf(args.optString("command")),
    )
    "launchApp" -> TizenProtocol.launchApp(
        args.optString("appId"),
        LaunchActionType.valueOf(args.optString("actionType")),
    )
    "sendText" -> TizenProtocol.sendText(args.optString("text"))
    else -> throw RuntimeException("unknown send op: $op")
}

fun main(argv: Array<String>) {
    val contract = JSONObject(File(argv[0]).readText(Charsets.UTF_8))

    val send = contract.optJSONObject("send_cases") ?: throw RuntimeException("send_cases ausente")
    for (name in send.keys()) {
        val c = send.optJSONObject(name)!!
        emit("SEND", name, runSend(c.optString("op"), c.optJSONObject("args")!!))
    }

    val parse = contract.optJSONObject("parse_cases") ?: throw RuntimeException("parse_cases ausente")
    for (name in parse.keys()) {
        val c = parse.optJSONObject(name)!!
        val input = c.optString("input")
        when (c.optString("op")) {
            "parseToken" -> emit("TOKEN", name, TizenProtocol.parseToken(input))
            "parseEvent" -> {
                val ev = TizenProtocol.parseEvent(input)
                emit("EVENT_NAME", name, ev?.event)
                emit("EVENT_TOKEN", name, ev?.token)
            }
            else -> throw RuntimeException("unknown parse op")
        }
    }
}
'''


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors the sibling protocol tests).
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


def _run_contract(tmp_path):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("toolchain/jars indisponíveis: " + ", ".join(tc["missing"]))
    if not PROTOCOL_KT.is_file() or not MESSAGE_KT.is_file():
        pytest.fail(f"fontes do protocolo ausentes em {PROTO_DIR}")
    if not CONTRACT_FILE.is_file():
        pytest.fail(f"contrato versionado ausente: {CONTRACT_FILE}")

    src = tmp_path / "src"
    (src / "org" / "json").mkdir(parents=True)
    (src / "org" / "json" / "json_shim.kt").write_text(ORG_JSON_SHIM, encoding="utf-8")
    (src / "Harness.kt").write_text(HARNESS_KT, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    compile_cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", str(tc["stdlib"]),
        "-d", str(out),
        str(PROTOCOL_KT), str(MESSAGE_KT),
        str(src / "org" / "json" / "json_shim.kt"), str(src / "Harness.kt"),
    ]
    cr = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilação do contrato falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join([str(out), str(tc["stdlib"])])
    rr = subprocess.run(
        [tc["java"], "-cp", run_cp, "HarnessKt", str(CONTRACT_FILE)],
        capture_output=True, text=True, timeout=120,
    )
    assert rr.returncode == 0, (
        "execução do harness de contrato falhou:\n" + (rr.stdout or "") + (rr.stderr or "")
    )

    produced = {}
    for line in rr.stdout.splitlines():
        line = line.rstrip("\r")
        parts = line.split("\t")
        if len(parts) == 3:
            kind, name, value = parts
            produced[(kind, name)] = None if value == NULL_SENTINEL else value
    return produced


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def contract():
    with CONTRACT_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    return _run_contract(tmp_path_factory.mktemp("proto_contract"))


# --------------------------------------------------------------------------- #
# Behavioural — the REAL protocol matches the versioned contract for every case.
# --------------------------------------------------------------------------- #
def _send_case_ids():
    with CONTRACT_FILE.open(encoding="utf-8") as fh:
        return list(json.load(fh)["send_cases"].keys())


def _parse_case_ids():
    with CONTRACT_FILE.open(encoding="utf-8") as fh:
        return list(json.load(fh)["parse_cases"].keys())


@pytest.mark.parametrize("case_id", _send_case_ids())
def test_send_case_matches_contract(produced, contract, case_id):
    spec = contract["send_cases"][case_id]
    actual = produced.get(("SEND", case_id))
    assert actual == spec["expected"], (
        f"[{case_id}] frame fora do contrato v{contract['version']}\n"
        f"  esperado: {spec['expected']!r}\n  obtido:   {actual!r}"
    )


@pytest.mark.parametrize("case_id", _parse_case_ids())
def test_parse_case_matches_contract(produced, contract, case_id):
    spec = contract["parse_cases"][case_id]
    op = spec["op"]
    if op == "parseToken":
        actual = produced.get(("TOKEN", case_id))
        assert actual == spec["expected"], (
            f"[{case_id}] token fora do contrato: esperado {spec['expected']!r}, "
            f"obtido {actual!r}"
        )
    elif op == "parseEvent":
        actual_event = produced.get(("EVENT_NAME", case_id))
        actual_token = produced.get(("EVENT_TOKEN", case_id))
        assert actual_event == spec["expected_event"], (
            f"[{case_id}] event esperado {spec['expected_event']!r}, obtido {actual_event!r}"
        )
        assert actual_token == spec["expected_token"], (
            f"[{case_id}] token esperado {spec['expected_token']!r}, obtido {actual_token!r}"
        )
    else:
        pytest.fail(f"op de parse desconhecida no contrato: {op}")


def test_every_contract_case_was_exercised(produced, contract):
    """Guard: no contract case silently skipped by the harness."""
    missing = []
    for name in contract["send_cases"]:
        if ("SEND", name) not in produced:
            missing.append(f"SEND/{name}")
    for name, spec in contract["parse_cases"].items():
        if spec["op"] == "parseToken" and ("TOKEN", name) not in produced:
            missing.append(f"TOKEN/{name}")
        if spec["op"] == "parseEvent" and ("EVENT_NAME", name) not in produced:
            missing.append(f"EVENT/{name}")
    assert not missing, "casos do contrato não exercitados: " + ", ".join(missing)


# --------------------------------------------------------------------------- #
# Structural — always run (no toolchain needed): the versioned contract itself.
# --------------------------------------------------------------------------- #
def test_contract_file_present_and_versioned():
    assert CONTRACT_FILE.is_file(), f"contrato ausente: {CONTRACT_FILE}"
    with CONTRACT_FILE.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data.get("version"), "contrato deve declarar um 'version'"
    assert data.get("protocol") == "samsung-tizen-ws"
    # filename version must match the declared version (versionamento consistente)
    assert f"_v{data['version']}." in CONTRACT_FILE.name, (
        "nome do arquivo deve refletir a versão do contrato"
    )


def test_contract_covers_all_message_types():
    with CONTRACT_FILE.open(encoding="utf-8") as fh:
        data = json.load(fh)
    send_ops = {c["op"] for c in data["send_cases"].values()}
    parse_ops = {c["op"] for c in data["parse_cases"].values()}
    # frames de tecla, launchApp, texto
    assert {"sendKey", "launchApp", "sendText"} <= send_ops, (
        f"contrato não cobre todos os tipos de envio: {send_ops}"
    )
    # parsing de token (e evento)
    assert {"parseToken", "parseEvent"} <= parse_ops, (
        f"contrato não cobre o parsing esperado: {parse_ops}"
    )
    # cobre as três variantes de comando de tecla
    commands = {
        c["args"].get("command")
        for c in data["send_cases"].values()
        if c["op"] == "sendKey"
    }
    assert {"CLICK", "PRESS", "RELEASE"} <= commands, (
        f"contrato deve cobrir Click/Press/Release: {commands}"
    )


def test_protocol_sources_present():
    assert PROTOCOL_KT.is_file(), f"TizenProtocol.kt ausente em {PROTO_DIR}"
    assert MESSAGE_KT.is_file(), f"TizenMessage.kt ausente em {PROTO_DIR}"
