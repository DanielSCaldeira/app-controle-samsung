"""Tests for task b1df122c — DiscoveryViewModel + tela de descoberta.

Acceptance criteria verified here:
  1. **ViewModel**: ao coletar de um ``DiscoveryService`` *fake*, o
     ``StateFlow`` (``uiState``) expõe a lista de TVs descobertas. Coberto
     *comportamentalmente* compilando o ``DiscoveryViewModel`` REAL numa JVM
     desktop e observando o estado após coletar TVs roteirizadas.
  2. **Tela Compose**: a tela renderiza os itens e dispara o callback de
     seleção. O harness JVM não tem runtime Compose/Android, então o critério é
     coberto por (a) asserções estruturais sobre ``DiscoveryScreen.kt`` (lista
     dos ``state.tvs``, linha *clickable* que invoca ``onTvSelected(tv)``) e
     (b) um teste de UI Compose instrumentado real
     (``app/src/androidTest/.../DiscoveryScreenTest.kt``) que faz ``setContent``,
     clica numa linha e verifica o callback — executável em device/CI.

Strategy
--------
Seguindo a convenção do repositório (executar o **código real** numa JVM em vez
de só inspecionar fontes): compilamos os fontes Kotlin reais
(``DiscoveryViewModel`` + ``DiscoveryService`` + interfaces + ``DiscoveredTv``)
contra *shims* puros de ``androidx.lifecycle`` (``ViewModel`` + ``viewModelScope``
ancorado num ``Dispatchers.Unconfined`` determinístico), ``dagger.hilt`` e
``javax.inject``. Um ``DiscoveryService`` *fake* (subclasse que sobrescreve
``discover()``) emite TVs roteirizadas — incluindo um id duplicado — e um harness
observa ``viewModel.uiState.value``.

Se o toolchain Kotlin/JDK não for localizado nos caches do Gradle, os testes
comportamentais dão ``skip``; as asserções estruturais sempre rodam.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"
DISC = PKG / "network" / "discovery"

VIEWMODEL_KT = PKG / "viewmodel" / "DiscoveryViewModel.kt"
SCREEN_KT = PKG / "ui" / "discovery" / "DiscoveryScreen.kt"
DISCOVERED_TV_KT = DISC / "DiscoveredTv.kt"
SOURCE_IFACE_KT = DISC / "TvCandidateSource.kt"
VALIDATOR_IFACE_KT = DISC / "TvCandidateValidator.kt"
SERVICE_KT = DISC / "DiscoveryService.kt"

UI_TEST_KT = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "ui" / "discovery" / "DiscoveryScreenTest.kt"
)
UNIT_TEST_KT = (
    ROOT / "app" / "src" / "test" / "java" / "com" / "factory"
    / "samsungremote" / "viewmodel" / "DiscoveryViewModelTest.kt"
)

GRADLE_CACHES = Path.home() / ".gradle" / "caches"


# --------------------------------------------------------------------------- #
# Shims — pure JVM stand-ins for the Android/Hilt/javax-inject symbols the
# ViewModel links against. viewModelScope is anchored to Dispatchers.Unconfined
# so the cold discovery flow is collected synchronously and the test is
# deterministic (no Main dispatcher required).
# --------------------------------------------------------------------------- #
LIFECYCLE_SHIM_KT = r'''package androidx.lifecycle

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
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

# --------------------------------------------------------------------------- #
# Harness — drives the REAL DiscoveryViewModel against a fake service.
# --------------------------------------------------------------------------- #
HARNESS_KT = r'''import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.discovery.DiscoveryService
import com.factory.samsungremote.network.discovery.TvCandidateSource
import com.factory.samsungremote.network.discovery.TvCandidateValidator
import com.factory.samsungremote.viewmodel.DiscoveryViewModel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.asFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.runBlocking

/** Fake that overrides discover() to emit scripted TVs (no sockets). */
private class FakeDiscoveryService(
    private val source: Flow<DiscoveredTv>,
) : DiscoveryService(
    TvCandidateSource { emptyFlow() },
    TvCandidateSource { emptyFlow() },
    TvCandidateValidator { null },
) {
    override fun discover(): Flow<DiscoveredTv> = source
}

private fun report(tag: String, vm: DiscoveryViewModel) {
    val s = vm.uiState.value
    val ids = s.tvs.joinToString(",") { it.id }
    val names = s.tvs.joinToString(";") { it.name }
    val ips = s.tvs.joinToString(",") { it.ipAddress }
    println("$tag|count=${s.tvs.size}|ids=$ids|names=$names|ips=$ips|scanning=${s.isScanning}|error=${s.error ?: "<null>"}")
}

fun main() = runBlocking {
    val tvs = listOf(
        DiscoveredTv("uuid:1", "[TV] Living Room", "192.168.0.10", "QN65Q80B"),
        DiscoveredTv("uuid:2", "[TV] Bedroom", "192.168.0.11", null),
        DiscoveredTv("uuid:1", "[TV] Living Room (dup)", "192.168.0.10", "QN65Q80B"),
    )

    // Happy path: StateFlow exposes the de-duplicated list of discovered TVs.
    report("happy", DiscoveryViewModel(FakeDiscoveryService(tvs.asFlow())))

    // Error path: a failing flow surfaces as DiscoveryUiState.error, scan stops.
    report("error", DiscoveryViewModel(FakeDiscoveryService(flow { throw RuntimeException("boom") })))

    // Empty/finite flow: scan ends with no results and no error.
    report("empty", DiscoveryViewModel(FakeDiscoveryService(emptyFlow())))

    // Restart: startScan() resets state (no duplicate accumulation across scans).
    val restartVm = DiscoveryViewModel(FakeDiscoveryService(tvs.asFlow()))
    restartVm.startScan()
    report("restart", restartVm)

    // stopScan(): keeps already-discovered TVs, clears the scanning flag.
    val stopVm = DiscoveryViewModel(FakeDiscoveryService(tvs.asFlow()))
    stopVm.stopScan()
    report("stopped", stopVm)
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
    for s in (VIEWMODEL_KT, DISCOVERED_TV_KT, SOURCE_IFACE_KT, VALIDATOR_IFACE_KT, SERVICE_KT):
        if not s.is_file():
            pytest.fail(f"fonte ausente: {s}")

    tmp = tmp_path_factory.mktemp("disc_vm")
    src = tmp / "src"
    # Write the shims under their package directories.
    (src / "androidx" / "lifecycle").mkdir(parents=True, exist_ok=True)
    (src / "androidx" / "lifecycle" / "lifecycle_shim.kt").write_text(LIFECYCLE_SHIM_KT, encoding="utf-8")
    (src / "dagger" / "hilt" / "android" / "lifecycle").mkdir(parents=True, exist_ok=True)
    (src / "dagger" / "hilt" / "android" / "lifecycle" / "hilt_shim.kt").write_text(HILT_SHIM_KT, encoding="utf-8")
    (src / "javax" / "inject").mkdir(parents=True, exist_ok=True)
    (src / "javax" / "inject" / "inject_shim.kt").write_text(INJECT_SHIM_KT, encoding="utf-8")
    harness = src / "VmHarness.kt"
    harness.write_text(HARNESS_KT, encoding="utf-8")

    out = tmp / "out"
    out.mkdir(exist_ok=True)

    shims = [
        src / "androidx" / "lifecycle" / "lifecycle_shim.kt",
        src / "dagger" / "hilt" / "android" / "lifecycle" / "hilt_shim.kt",
        src / "javax" / "inject" / "inject_shim.kt",
    ]
    real_sources = [
        DISCOVERED_TV_KT, SOURCE_IFACE_KT, VALIDATOR_IFACE_KT, SERVICE_KT, VIEWMODEL_KT,
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
        "compilação do ViewModel harness falhou:\n" + (cr.stdout or "") + (cr.stderr or "")
    )

    run_cp = os.pathsep.join(str(p) for p in (out, tc["stdlib"], tc["corout"]))
    run = subprocess.run(
        [tc["java"], "-cp", run_cp, "VmHarnessKt"],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, (
        "execução do ViewModel harness falhou:\n" + (run.stdout or "") + (run.stderr or "")
    )
    return _parse_lines(run.stdout)


# --------------------------------------------------------------------------- #
# Criterion 1 — collecting from the fake service, uiState exposes the TV list.
# --------------------------------------------------------------------------- #
def test_uistate_exposes_discovered_tv_list(vm_out):
    happy = vm_out.get("happy")
    assert happy is not None, f"harness não emitiu 'happy': {vm_out!r}"
    # Two distinct TVs (the duplicate id is collapsed).
    assert happy["count"] == "2", f"esperado 2 TVs, veio {happy!r}"
    assert happy["ids"] == "uuid:1,uuid:2"
    assert happy["names"] == "[TV] Living Room;[TV] Bedroom"
    assert happy["ips"] == "192.168.0.10,192.168.0.11"


def test_uistate_dedupes_by_id(vm_out):
    # The third scripted TV reuses uuid:1 — its name must NOT appear.
    assert "(dup)" not in vm_out["happy"]["names"]
    assert vm_out["happy"]["ids"].count("uuid:1") == 1


def test_failure_surfaces_as_error_and_stops_scan(vm_out):
    err = vm_out.get("error")
    assert err is not None
    assert err["error"] == "boom", f"erro não propagado: {err!r}"
    assert err["scanning"] == "false"
    assert err["count"] == "0"


def test_finite_flow_completes_without_error(vm_out):
    empty = vm_out.get("empty")
    assert empty["count"] == "0"
    assert empty["error"] == "<null>"
    assert empty["scanning"] == "false"


def test_restart_resets_state_without_accumulating(vm_out):
    # startScan() called again must not double the list (still 2, not 4).
    restart = vm_out.get("restart")
    assert restart["count"] == "2", f"startScan() acumulou em vez de resetar: {restart!r}"
    assert restart["ids"] == "uuid:1,uuid:2"


def test_stop_scan_keeps_results_and_clears_flag(vm_out):
    stopped = vm_out.get("stopped")
    assert stopped["scanning"] == "false"
    assert stopped["count"] == "2", "stopScan() não deve descartar TVs já encontradas"


# --------------------------------------------------------------------------- #
# Structural — ViewModel wiring (always run, no toolchain required).
# --------------------------------------------------------------------------- #
def test_viewmodel_present_and_wired():
    assert VIEWMODEL_KT.is_file(), f"DiscoveryViewModel ausente: {VIEWMODEL_KT}"
    text = VIEWMODEL_KT.read_text(encoding="utf-8")
    assert "@HiltViewModel" in text, "ViewModel deve ser um @HiltViewModel"
    assert "@Inject constructor" in text, "ViewModel deve receber dependências via @Inject"
    assert "discoveryService: DiscoveryService" in text, "ViewModel deve depender de DiscoveryService"
    assert "StateFlow<DiscoveryUiState>" in text, "ViewModel deve expor um StateFlow do estado"
    assert "discoveryService.discover()" in text and ".collect" in text, (
        "ViewModel deve coletar do DiscoveryService"
    )
    assert "viewModelScope" in text, "a coleta deve rodar no viewModelScope"


# --------------------------------------------------------------------------- #
# Criterion 2 (structural) — Compose screen renders items + selection callback.
# --------------------------------------------------------------------------- #
def test_screen_present():
    assert SCREEN_KT.is_file(), f"DiscoveryScreen ausente: {SCREEN_KT}"


def test_screen_lists_tvs_and_fires_selection_callback():
    text = SCREEN_KT.read_text(encoding="utf-8")
    # Stateless screen takes the state and a selection callback.
    assert "onTvSelected: (DiscoveredTv) -> Unit" in text, "tela deve expor callback de seleção"
    # Renders the list from state.tvs.
    assert "LazyColumn" in text and "items(" in text, "tela deve listar TVs numa LazyColumn"
    assert "state.tvs" in text, "tela deve renderizar a partir de state.tvs"
    # A row is clickable and reports the selected TV.
    assert "clickable" in text, "linha de TV deve ser clicável"
    assert "onTvSelected(tv)" in text, "clique numa linha deve disparar onTvSelected(tv)"


def test_route_observes_uistate():
    text = SCREEN_KT.read_text(encoding="utf-8")
    assert "collectAsState" in text, "a rota deve observar uiState via collectAsState"
    assert "viewModel.uiState" in text


def test_screen_exposes_stable_test_tags():
    text = SCREEN_KT.read_text(encoding="utf-8")
    # Tags the Compose UI test targets.
    assert "testTag" in text
    for tag_const in ("TV_LIST", "PROGRESS"):
        assert tag_const in text, f"test tag '{tag_const}' ausente"
    assert "fun tvItem(id: String)" in text, "deve haver tag por item (tvItem)"


# --------------------------------------------------------------------------- #
# Criterion 2 — the instrumented Compose UI test artifact exists and is real.
# --------------------------------------------------------------------------- #
def test_compose_ui_test_authored():
    assert UI_TEST_KT.is_file(), f"teste de UI Compose ausente: {UI_TEST_KT}"
    text = UI_TEST_KT.read_text(encoding="utf-8")
    assert "createComposeRule" in text, "teste de UI deve usar createComposeRule"
    assert "setContent" in text and "DiscoveryScreen(" in text, "teste deve renderizar DiscoveryScreen"
    assert "performClick" in text, "teste deve clicar numa linha"
    assert "onTvSelected" in text, "teste deve verificar o callback de seleção"
    assert "@Test" in text


def test_viewmodel_unit_test_authored():
    assert UNIT_TEST_KT.is_file(), f"teste unitário do ViewModel ausente: {UNIT_TEST_KT}"
    text = UNIT_TEST_KT.read_text(encoding="utf-8")
    assert "DiscoveryViewModel(" in text
    assert "uiState" in text and "@Test" in text
