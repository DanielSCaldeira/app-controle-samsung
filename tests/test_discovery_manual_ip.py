"""Tests for task ae10f898 — manual IP entry (discovery fallback).

The discovery screen gains a manual-IP fallback for networks where SSDP/mDNS
multicast is blocked: the user types the TV's IP, a *valid* address is turned
into a ``DiscoveredTv`` candidate and reported through ``onTvSelected`` (which
starts pairing), while an *invalid* address surfaces an inline validation error
and does NOT start pairing.

Acceptance criteria
-------------------
  1. A valid IP creates a TV candidate and starts pairing.
  2. An invalid IP shows a validation error.

Strategy
--------
Following the repo convention (exercise the **real** code on a desktop JVM
rather than only inspecting sources), the pure core of the feature — the IPv4
validator ``isValidIpv4`` and the candidate builder ``manualTvCandidate`` — is
extracted *verbatim* from the shipped ``DiscoveryScreen.kt`` and compiled
against the real ``DiscoveredTv`` data class, then driven by a harness that
reports validation verdicts and the built candidate. Those two functions depend
only on the Kotlin stdlib + ``DiscoveredTv`` (no Compose runtime), so they run
faithfully on a plain JVM.

The Compose UI itself (text field, submit button, inline error) cannot run on
the JVM harness, so it is covered by (a) structural assertions over
``DiscoveryScreen.kt`` (valid submit -> ``onSubmit(candidate)``; invalid submit
-> error state + ``MANUAL_IP_ERROR``) and (b) a real instrumented Compose UI
test (``app/src/androidTest/.../DiscoveryManualIpTest.kt``) executable on
device/CI.

If the Kotlin/JDK toolchain is not found in the Gradle caches, the behavioural
tests ``skip``; the structural assertions always run.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"
DISC = PKG / "network" / "discovery"

SCREEN_KT = PKG / "ui" / "discovery" / "DiscoveryScreen.kt"
DISCOVERED_TV_KT = DISC / "DiscoveredTv.kt"
STRINGS_XML = ROOT / "app" / "src" / "main" / "res" / "values" / "strings.xml"

UI_TEST_KT = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "ui" / "discovery" / "DiscoveryManualIpTest.kt"
)

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


# --------------------------------------------------------------------------- #
# Extract the REAL pure functions verbatim from the shipped source so the
# harness compiles the actual shipped logic (not a hand-written copy).
# --------------------------------------------------------------------------- #
def _screen_text():
    assert SCREEN_KT.is_file(), f"DiscoveryScreen ausente: {SCREEN_KT}"
    return SCREEN_KT.read_text(encoding="utf-8")


def _extract_pure_functions(text):
    """Slice from the first `internal fun manualTvCandidate` to EOF.

    Both pure helpers (``manualTvCandidate`` then ``isValidIpv4``) live at the
    tail of the file and reference only ``DiscoveredTv`` + the stdlib, so the
    tail is a self-contained, compilable unit.
    """
    m = re.search(r"^internal fun manualTvCandidate", text, re.MULTILINE)
    if not m:
        return None
    return text[m.start():]


# --------------------------------------------------------------------------- #
# Toolchain discovery (mirrors the other harness-based tests).
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
        "stdlib": _find_jar("kotlin-stdlib-1*.jar", "kotlin-stdlib-2*.jar"),
        "scrt": _find_jar("kotlin-script-runtime-*.jar"),
        "refl": _find_jar("kotlin-reflect-*.jar"),
        "trove": _find_jar("trove4j-*.jar"),
        "annot": _find_jar("annotations-13*.jar"),
        # The embeddable compiler references coroutines symbols at startup, so it
        # must be on the compiler classpath even though our functions don't use it.
        "corout": _find_jar("kotlinx-coroutines-core-jvm-*.jar"),
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"], tc["annot"],
        tc["corout"],
    ))


HARNESS_TEMPLATE = r'''package com.factory.samsungremote.ui.discovery

import com.factory.samsungremote.network.discovery.DiscoveredTv

// --- real functions extracted verbatim from DiscoveryScreen.kt ---
__PURE_FUNCTIONS__
// --- end extracted ---

private fun checkValid(ip: String) {
    println("valid|$ip|${isValidIpv4(ip)}")
}

fun main() {
    // Valid addresses (criterion 1: these become candidates / start pairing).
    listOf("192.168.0.10", "0.0.0.0", "255.255.255.255", "1.2.3.4", "  10.0.0.1  ")
        .forEach(::checkValid)
    // Invalid addresses (criterion 2: these must be rejected -> validation error).
    listOf("", "1.2.3", "1.2.3.4.5", "256.1.1.1", "1.2.3.999", "1.2.3.",
           "abc.1.1.1", "1234.1.1.1", "192.168.0.-1")
        .forEach(::checkValid)

    // A valid IP is turned into a transient DiscoveredTv candidate.
    val tv = manualTvCandidate("192.168.0.50")
    println("cand|${tv.id}|${tv.name}|${tv.ipAddress}|${tv.modelName ?: "<null>"}")
}
'''


@pytest.fixture(scope="module")
def harness_out(tmp_path_factory):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("Kotlin/JDK toolchain unavailable: missing " + ", ".join(tc["missing"]))
    if not DISCOVERED_TV_KT.is_file():
        pytest.fail(f"fonte ausente: {DISCOVERED_TV_KT}")

    pure = _extract_pure_functions(_screen_text())
    if pure is None:
        pytest.fail("não foi possível extrair manualTvCandidate/isValidIpv4 de DiscoveryScreen.kt")

    tmp = tmp_path_factory.mktemp("manual_ip")
    src = tmp / "src"
    src.mkdir(parents=True, exist_ok=True)
    harness = src / "ManualIpHarness.kt"
    harness.write_text(HARNESS_TEMPLATE.replace("__PURE_FUNCTIONS__", pure), encoding="utf-8")

    out = tmp / "out"
    out.mkdir(exist_ok=True)

    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", str(tc["stdlib"]),
        "-d", str(out),
        str(DISCOVERED_TV_KT),
        str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilação do harness de IP manual falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in (out, tc["stdlib"]))
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "com.factory.samsungremote.ui.discovery.ManualIpHarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execução do harness de IP manual falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )

    valids, cand = {}, None
    for raw in run.stdout.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("valid|"):
            _, ip, verdict = line.split("|", 2)
            valids[ip] = (verdict == "true")
        elif line.startswith("cand|"):
            _, cid, name, ip, model = line.split("|", 4)
            cand = {"id": cid, "name": name, "ip": ip, "model": model}
    return {"valids": valids, "cand": cand, "stdout": run.stdout}


# --------------------------------------------------------------------------- #
# Criterion 1 (behavioural) — a valid IP is accepted and built into a candidate.
# --------------------------------------------------------------------------- #
def test_valid_ips_are_accepted(harness_out):
    valids = harness_out["valids"]
    for ip in ("192.168.0.10", "0.0.0.0", "255.255.255.255", "1.2.3.4"):
        assert valids.get(ip) is True, f"IP válido rejeitado: {ip!r} ({harness_out['stdout']!r})"


def test_surrounding_whitespace_is_tolerated(harness_out):
    assert harness_out["valids"].get("  10.0.0.1  ") is True, "espaços ao redor deveriam ser tolerados"


def test_valid_ip_builds_tv_candidate_for_pairing(harness_out):
    cand = harness_out["cand"]
    assert cand is not None, "manualTvCandidate não produziu candidato"
    # id derived from the address so it de-dupes against itself; ip carried through.
    assert cand["id"] == "manual:192.168.0.50", f"id inesperado: {cand!r}"
    assert cand["ip"] == "192.168.0.50"
    assert cand["name"] == "192.168.0.50"
    # model is unknown until pairing/connection resolves it.
    assert cand["model"] == "<null>"


# --------------------------------------------------------------------------- #
# Criterion 2 (behavioural) — malformed addresses are rejected (drives error).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [
    "", "1.2.3", "1.2.3.4.5", "256.1.1.1", "1.2.3.999", "1.2.3.",
    "abc.1.1.1", "1234.1.1.1", "192.168.0.-1",
])
def test_invalid_ips_are_rejected(harness_out, bad):
    assert harness_out["valids"].get(bad) is False, (
        f"IP inválido aceito indevidamente: {bad!r} ({harness_out['stdout']!r})"
    )


# --------------------------------------------------------------------------- #
# Structural — the Compose wiring (always runs, no toolchain required).
# --------------------------------------------------------------------------- #
def test_manual_entry_composable_and_tags_present():
    text = _screen_text()
    assert "ManualIpEntry" in text, "deve haver um composable de entrada manual de IP"
    for tag in ("MANUAL_IP_FIELD", "MANUAL_IP_SUBMIT", "MANUAL_IP_ERROR"):
        assert tag in text, f"test tag '{tag}' ausente"
    assert "OutlinedTextField" in text, "deve haver um campo de texto para o IP"
    assert "DiscoveryTestTags.MANUAL_IP_FIELD" in text, "o campo deve ter a tag MANUAL_IP_FIELD"


def test_valid_submit_creates_candidate_and_starts_pairing():
    text = _screen_text()
    # On submit: validate, build a candidate, and hand it to the selection callback.
    assert "isValidIpv4" in text, "submit deve validar o IP via isValidIpv4"
    assert "manualTvCandidate" in text, "submit deve construir um DiscoveredTv via manualTvCandidate"
    assert re.search(r"onSubmit\(candidate\)", text), (
        "um IP válido deve ser reportado via onSubmit(candidate) (inicia o pareamento)"
    )
    # The manual entry's onSubmit is wired to the screen's onTvSelected.
    assert "ManualIpEntry(onSubmit = onTvSelected)" in text, (
        "a entrada manual deve disparar onTvSelected (mesmo fluxo de uma TV descoberta)"
    )


def test_invalid_submit_shows_validation_error():
    text = _screen_text()
    assert "showError = true" in text, "um IP inválido deve ativar o estado de erro"
    assert "isError = showError" in text, "o campo deve refletir o estado de erro"
    # The inline error message is rendered under the error test tag.
    assert re.search(r"if \(showError\)", text), "a mensagem de erro deve ser condicional ao estado de erro"
    assert "DiscoveryTestTags.MANUAL_IP_ERROR" in text, "a mensagem de erro deve usar a tag MANUAL_IP_ERROR"
    assert "discovery_manual_invalid" in text, "a mensagem deve usar o texto de validação localizado"


def test_manual_candidate_id_and_model_contract():
    text = _screen_text()
    assert 'id = "manual:$ip"' in text, "o id do candidato manual deve ser derivado do IP"
    assert "modelName = null" in text, "o modelo é desconhecido até o pareamento resolver"


def test_localized_strings_present():
    assert STRINGS_XML.is_file(), f"strings.xml ausente: {STRINGS_XML}"
    xml = STRINGS_XML.read_text(encoding="utf-8")
    for name in (
        "discovery_manual_hint", "discovery_manual_label",
        "discovery_manual_connect", "discovery_manual_invalid",
    ):
        assert f'name="{name}"' in xml, f"string '{name}' ausente"


# --------------------------------------------------------------------------- #
# Criterion 2 — the instrumented Compose UI test artifact exists and is real.
# --------------------------------------------------------------------------- #
def test_compose_ui_test_authored():
    assert UI_TEST_KT.is_file(), f"teste de UI Compose ausente: {UI_TEST_KT}"
    text = UI_TEST_KT.read_text(encoding="utf-8")
    assert "createComposeRule" in text, "teste de UI deve usar createComposeRule"
    assert "setContent" in text and "DiscoveryScreen(" in text, "teste deve renderizar DiscoveryScreen"
    assert "performTextInput" in text, "teste deve digitar um IP no campo"
    assert "MANUAL_IP_SUBMIT" in text and "performClick" in text, "teste deve submeter o IP"
    assert "MANUAL_IP_ERROR" in text, "teste deve verificar a mensagem de erro de validação"
    assert "onTvSelected" in text, "teste deve verificar o início do pareamento via callback"
    assert text.count("@Test") >= 2, "deve cobrir caminho válido e inválido"
