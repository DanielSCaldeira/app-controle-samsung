"""Tests for task 250ebe0e — Tela de pareamento (PairingScreen + PairingViewModel).

Acceptance criteria verified here:
  1. **Estado 'aguardando autorização'**: durante o pareamento o estado fica em
     ``PairingStatus.Pairing`` (a tela mostra a instrução "aceite na TV"). Coberto
     *comportamentalmente* — o ``PairingViewModel`` REAL parte de ``Pairing`` e
     permanece nele enquanto o handshake não resolve.
  2. **Token (fake) → navega para a tela de controle**: ao receber um token de um
     ``PairingManager`` *fake*, o ``uiState`` vira ``PairingStatus.Success`` com o
     token, e a tela dispara ``onPaired(token)`` (navegação). Coberto
     comportamentalmente (ViewModel) + estruturalmente (tela) + por um teste de UI
     Compose instrumentado real.
  3. **Erro → botão de retry**: uma ``PairingException`` vira
     ``PairingStatus.Error`` preservando o ``failureReason``; um novo ``pair()``
     (retry) reinicia o fluxo. A tela mostra um botão de retry ligado a
     ``onRetry``.

Strategy
--------
Seguindo a convenção do repositório (rodar o **código real** numa JVM desktop em
vez de só inspecionar fontes): compilamos o ``PairingViewModel`` REAL — junto com
os tipos REAIS ``DiscoveredTv`` e ``PairingException``/``PairingFailureReason`` —
contra *shims* puros de ``androidx.lifecycle`` (``ViewModel`` + ``viewModelScope``
ancorado num ``Dispatchers.Unconfined`` determinístico), ``dagger.hilt`` e
``javax.inject``, **mais** um ``PairingManager`` *shim* cujo ``pair()`` é
roteirizado (retorna um token ou lança ``PairingException``). Um harness observa
``viewModel.uiState.value`` após cada cenário.

A tela Compose não tem runtime no harness JVM, então o critério da UI é coberto
por (a) asserções estruturais sobre ``PairingScreen.kt`` e (b) um teste de UI
Compose instrumentado real
(``app/src/androidTest/.../ui/pairing/PairingScreenTest.kt``), executável em
device/CI.

Se o toolchain Kotlin/JDK não for localizado nos caches do Gradle, os testes
comportamentais dão ``skip``; as asserções estruturais sempre rodam.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

VIEWMODEL_KT = PKG / "viewmodel" / "PairingViewModel.kt"
SCREEN_KT = PKG / "ui" / "pairing" / "PairingScreen.kt"
DISCOVERED_TV_KT = PKG / "network" / "discovery" / "DiscoveredTv.kt"
PAIRING_EXCEPTION_KT = PKG / "network" / "pairing" / "PairingException.kt"

UI_TEST_KT = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "ui" / "pairing" / "PairingScreenTest.kt"
)

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


# --------------------------------------------------------------------------- #
# Shims — pure JVM stand-ins for the Android/Hilt/javax-inject symbols the
# ViewModel links against. viewModelScope is anchored to Dispatchers.Unconfined
# so the launched pairing coroutine runs synchronously and the test is
# deterministic (no Main dispatcher required).
# --------------------------------------------------------------------------- #
LIFECYCLE_SHIM_KT = r'''package androidx.lifecycle

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import java.util.concurrent.ConcurrentHashMap

abstract class ViewModel {
    open fun onCleared() {}
    companion object {
        val scopes = ConcurrentHashMap<ViewModel, CoroutineScope>()
    }
}

val ViewModel.viewModelScope: CoroutineScope
    get() = ViewModel.scopes.getOrPut(this) {
        CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
    }
'''

HILT_SHIM_KT = r'''package dagger.hilt.android.lifecycle

@Retention(AnnotationRetention.BINARY)
@Target(AnnotationTarget.CLASS)
annotation class HiltViewModel
'''

INJECT_SHIM_KT = r'''package javax.inject

@Retention(AnnotationRetention.RUNTIME)
@Target(
    AnnotationTarget.CONSTRUCTOR,
    AnnotationTarget.FIELD,
    AnnotationTarget.FUNCTION,
)
annotation class Inject
'''

# Shim PairingManager: replaces the real (okhttp/registry-backed) one with a
# scriptable handshake. Lives in the real package so PairingViewModel links
# against it unchanged. pair() runs the scripted lambda — returning a token or
# throwing a (real) PairingException.
PAIRING_MANAGER_SHIM_KT = r'''package com.factory.samsungremote.network.pairing

import com.factory.samsungremote.network.discovery.DiscoveredTv

class PairingManager(
    private val script: suspend (DiscoveredTv) -> String,
) {
    suspend fun pair(tv: DiscoveredTv): String = script(tv)
}
'''

# --------------------------------------------------------------------------- #
# Harness — drives the REAL PairingViewModel against the shim PairingManager.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.pairing.PairingException
import com.factory.samsungremote.network.pairing.PairingFailureReason
import com.factory.samsungremote.network.pairing.PairingManager
import com.factory.samsungremote.viewmodel.PairingViewModel
import kotlinx.coroutines.runBlocking

private val TV = DiscoveredTv("uuid:1", "[TV] Living Room", "192.168.0.10", "QN65Q80B")

private fun report(tag: String, vm: PairingViewModel) {
    val s = vm.uiState.value
    println("$tag|status=${s.status}|token=${s.token ?: "<null>"}|reason=${s.failureReason ?: "<null>"}")
}

fun main() = runBlocking {
    // Initial state, before any pair() call: waiting for authorization.
    report("initial", PairingViewModel(PairingManager { "UNUSED" }))

    // Happy path: a returned token flips state to Success and carries the token.
    val successVm = PairingViewModel(PairingManager { "FAKE-TOKEN-123" })
    successVm.pair(TV)
    report("success", successVm)

    // Denial: PairingException(UNAUTHORIZED) → Error keeping the reason.
    val unauthVm = PairingViewModel(PairingManager {
        throw PairingException(PairingFailureReason.UNAUTHORIZED, "denied")
    })
    unauthVm.pair(TV)
    report("unauthorized", unauthVm)

    // Connection failure: reason preserved for a TV-unreachable message.
    val connVm = PairingViewModel(PairingManager {
        throw PairingException(PairingFailureReason.CONNECTION_FAILED, "no route")
    })
    connVm.pair(TV)
    report("connection", connVm)

    // No token: handshake completed but never delivered a token.
    val noTokenVm = PairingViewModel(PairingManager {
        throw PairingException(PairingFailureReason.NO_TOKEN, "no token")
    })
    noTokenVm.pair(TV)
    report("no_token", noTokenVm)

    // Unexpected error: surfaces as Error with an unclassified (null) reason.
    val genericVm = PairingViewModel(PairingManager { throw RuntimeException("boom") })
    genericVm.pair(TV)
    report("generic", genericVm)

    // Retry: the first attempt fails, a second pair() recovers to Success.
    var calls = 0
    val retryVm = PairingViewModel(PairingManager {
        calls++
        if (calls == 1) throw PairingException(PairingFailureReason.CONNECTION_FAILED, "transient")
        else "RETRY-TOKEN"
    })
    retryVm.pair(TV)
    report("retry_failed", retryVm)
    retryVm.pair(TV)
    report("retry_succeeded", retryVm)
}
'''


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
    }
    tc["missing"] = [n for n, v in tc.items() if not v]
    return tc


def _compiler_classpath(tc):
    return os.pathsep.join(str(p) for p in (
        tc["emb"], tc["stdlib"], tc["scrt"], tc["refl"], tc["trove"],
        tc["annot"], tc["corout"],
    ))


def _parse_lines(stdout):
    """Parse 'tag|k=v|k=v' harness lines into {tag: {k: v}}."""
    out = {}
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if "|" not in line:
            continue
        tag, _, rest = line.partition("|")
        fields = {}
        for chunk in rest.split("|"):
            if "=" in chunk:
                k, _, v = chunk.partition("=")
                fields[k] = v
        out[tag.strip()] = fields
    return out


@pytest.fixture(scope="module")
def vm_out(tmp_path_factory):
    tc = _toolchain()
    if tc["missing"]:
        pytest.skip("Kotlin/JDK toolchain unavailable: missing " + ", ".join(tc["missing"]))
    for s in (VIEWMODEL_KT, DISCOVERED_TV_KT, PAIRING_EXCEPTION_KT):
        if not s.is_file():
            pytest.fail(f"fonte ausente: {s}")

    tmp = tmp_path_factory.mktemp("pair_vm")
    src = tmp / "src"
    # Write the shims under their package directories.
    (src / "androidx" / "lifecycle").mkdir(parents=True, exist_ok=True)
    (src / "androidx" / "lifecycle" / "lifecycle_shim.kt").write_text(LIFECYCLE_SHIM_KT, encoding="utf-8")
    (src / "dagger" / "hilt" / "android" / "lifecycle").mkdir(parents=True, exist_ok=True)
    (src / "dagger" / "hilt" / "android" / "lifecycle" / "hilt_shim.kt").write_text(HILT_SHIM_KT, encoding="utf-8")
    (src / "javax" / "inject").mkdir(parents=True, exist_ok=True)
    (src / "javax" / "inject" / "inject_shim.kt").write_text(INJECT_SHIM_KT, encoding="utf-8")
    pm_dir = src / "com" / "factory" / "samsungremote" / "network" / "pairing"
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "PairingManagerShim.kt").write_text(PAIRING_MANAGER_SHIM_KT, encoding="utf-8")
    harness = src / "PairHarness.kt"
    harness.write_text(HARNESS_KT, encoding="utf-8")

    out = tmp / "out"
    out.mkdir(exist_ok=True)

    shims = [
        src / "androidx" / "lifecycle" / "lifecycle_shim.kt",
        src / "dagger" / "hilt" / "android" / "lifecycle" / "hilt_shim.kt",
        src / "javax" / "inject" / "inject_shim.kt",
        pm_dir / "PairingManagerShim.kt",
    ]
    real_sources = [
        DISCOVERED_TV_KT, PAIRING_EXCEPTION_KT, VIEWMODEL_KT,
    ]
    compile_cp = os.pathsep.join(str(p) for p in (tc["stdlib"], tc["corout"]))
    cmd = [
        tc["java"], "-cp", _compiler_classpath(tc),
        "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        "-no-stdlib", "-no-reflect",
        "-classpath", compile_cp,
        "-d", str(out),
        *[str(p) for p in shims],
        *[str(p) for p in real_sources],
        str(harness),
    ]
    cr = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert cr.returncode == 0, (
        "compilação do PairingViewModel harness falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in (out, tc["stdlib"], tc["corout"]))
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "PairHarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execução do PairingViewModel harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_lines(run.stdout)


# --------------------------------------------------------------------------- #
# Criterion 1 — 'aguardando autorização' is the initial/in-flight state.
# --------------------------------------------------------------------------- #
def test_initial_state_is_pairing(vm_out):
    initial = vm_out.get("initial")
    assert initial is not None, f"harness não emitiu 'initial': {vm_out!r}"
    assert initial["status"] == "Pairing", f"estado inicial deve ser Pairing: {initial!r}"
    assert initial["token"] == "<null>"
    assert initial["reason"] == "<null>"


# --------------------------------------------------------------------------- #
# Criterion 2 — token (fake) → Success + token (screen navigates).
# --------------------------------------------------------------------------- #
def test_token_received_transitions_to_success(vm_out):
    success = vm_out.get("success")
    assert success is not None
    assert success["status"] == "Success", f"token recebido deve virar Success: {success!r}"
    assert success["token"] == "FAKE-TOKEN-123", f"token não propagado: {success!r}"
    assert success["reason"] == "<null>"


# --------------------------------------------------------------------------- #
# Criterion 3 — failures surface as Error keeping the reason (retry possible).
# --------------------------------------------------------------------------- #
def test_unauthorized_surfaces_as_error_with_reason(vm_out):
    err = vm_out.get("unauthorized")
    assert err is not None
    assert err["status"] == "Error", f"denial deve virar Error: {err!r}"
    assert err["reason"] == "UNAUTHORIZED", f"reason não preservado: {err!r}"
    assert err["token"] == "<null>"


def test_connection_failure_surfaces_as_error_with_reason(vm_out):
    err = vm_out.get("connection")
    assert err["status"] == "Error"
    assert err["reason"] == "CONNECTION_FAILED"


def test_no_token_surfaces_as_error_with_reason(vm_out):
    err = vm_out.get("no_token")
    assert err["status"] == "Error"
    assert err["reason"] == "NO_TOKEN"


def test_unexpected_error_surfaces_as_error_without_reason(vm_out):
    err = vm_out.get("generic")
    assert err["status"] == "Error", f"erro inesperado deve virar Error: {err!r}"
    assert err["reason"] == "<null>", "erro não classificado deve ter reason nulo"


def test_retry_recovers_from_failure(vm_out):
    failed = vm_out.get("retry_failed")
    succeeded = vm_out.get("retry_succeeded")
    # First attempt fails...
    assert failed["status"] == "Error", f"primeira tentativa deveria falhar: {failed!r}"
    assert failed["reason"] == "CONNECTION_FAILED"
    # ...and calling pair() again (retry) recovers, replacing the error state.
    assert succeeded["status"] == "Success", f"retry deveria recuperar: {succeeded!r}"
    assert succeeded["token"] == "RETRY-TOKEN"
    assert succeeded["reason"] == "<null>", "retry bem-sucedido deve limpar o erro anterior"


# --------------------------------------------------------------------------- #
# Structural — ViewModel wiring (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_viewmodel_present_and_wired():
    assert VIEWMODEL_KT.is_file(), f"PairingViewModel ausente: {VIEWMODEL_KT}"
    text = VIEWMODEL_KT.read_text(encoding="utf-8")
    assert "@HiltViewModel" in text, "ViewModel deve ser um @HiltViewModel"
    assert "@Inject constructor" in text, "ViewModel deve receber dependências via @Inject"
    assert "pairingManager: PairingManager" in text, "ViewModel deve depender de PairingManager"
    assert "StateFlow<PairingUiState>" in text, "ViewModel deve expor um StateFlow do estado"
    assert "pairingManager.pair(" in text, "ViewModel deve chamar PairingManager.pair"
    assert "viewModelScope" in text, "o handshake deve rodar no viewModelScope"
    assert "PairingException" in text, "ViewModel deve mapear PairingException para o estado"


def test_viewmodel_exposes_three_status_states():
    text = VIEWMODEL_KT.read_text(encoding="utf-8")
    for state in ("Pairing", "Success", "Error"):
        assert state in text, f"PairingStatus.{state} ausente no ViewModel"


# --------------------------------------------------------------------------- #
# Criterion 2/3 (structural) — Compose screen: waiting, navigate, retry.
# --------------------------------------------------------------------------- #
def test_screen_present():
    assert SCREEN_KT.is_file(), f"PairingScreen ausente: {SCREEN_KT}"


def test_screen_shows_waiting_instruction_and_progress():
    text = SCREEN_KT.read_text(encoding="utf-8")
    assert "pairing_instruction" in text, "tela deve mostrar a instrução 'aceite na TV'"
    assert "CircularProgressIndicator" in text, "tela deve mostrar progresso durante o pareamento"


def test_screen_navigates_on_success():
    text = SCREEN_KT.read_text(encoding="utf-8")
    assert "onPaired: (String) -> Unit" in text, "tela deve expor callback de sucesso onPaired(token)"
    assert "PairingStatus.Success" in text, "tela deve reagir ao estado de sucesso"
    assert "onPaired(state.token)" in text, "sucesso deve disparar onPaired com o token"


def test_screen_offers_retry_on_error():
    text = SCREEN_KT.read_text(encoding="utf-8")
    assert "onRetry: () -> Unit" in text, "tela deve expor callback de retry"
    assert "PairingStatus.Error" in text, "tela deve reagir ao estado de erro"
    assert "onClick = onRetry" in text, "o botão de retry deve estar ligado a onRetry"


def test_screen_exposes_stable_test_tags():
    text = SCREEN_KT.read_text(encoding="utf-8")
    assert "testTag" in text
    for tag_const in ("INSTRUCTION", "PROGRESS", "ERROR", "RETRY"):
        assert tag_const in text, f"test tag '{tag_const}' ausente"


def test_route_observes_uistate_and_starts_pairing():
    text = SCREEN_KT.read_text(encoding="utf-8")
    assert "collectAsState" in text, "a rota deve observar uiState via collectAsState"
    assert "viewModel.uiState" in text
    assert "viewModel.pair(" in text, "a rota deve iniciar o handshake"


# --------------------------------------------------------------------------- #
# Criterion (UI) — the instrumented Compose UI test artifact exists and is real.
# --------------------------------------------------------------------------- #
def test_compose_ui_test_authored():
    assert UI_TEST_KT.is_file(), f"teste de UI Compose ausente: {UI_TEST_KT}"
    text = UI_TEST_KT.read_text(encoding="utf-8")
    assert "createComposeRule" in text, "teste de UI deve usar createComposeRule"
    assert "setContent" in text and "PairingScreen(" in text, "teste deve renderizar PairingScreen"
    assert "PairingTestTags.INSTRUCTION" in text, "teste deve verificar o estado de espera"
    assert "PairingTestTags.RETRY" in text and "performClick" in text, "teste deve clicar no retry"
    assert "onPaired" in text, "teste deve verificar a navegação no sucesso"
    assert "@Test" in text
