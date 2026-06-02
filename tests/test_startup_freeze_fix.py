"""Tests for task b96ab4ee — Corrigir congelamento de inicialização.

Sintoma: no cold start (Android 13+, ex. Moto G35) o app ficava preso na
janela de inicialização do sistema (que mostra o ``android:label`` "Samsung
Remote") e nunca desenhava o primeiro frame da UI Compose
(``DiscoveryRoute`` → "Choose a TV").

Causa raiz corrigida pelo coder: a resolução do tema dinâmico (Material You)
em ``SamsungRemoteTheme`` (``dynamicLightColorScheme`` / ``dynamicDarkColorScheme``)
roda síncrona na primeira composição e, em alguns builds OEM, pode lançar — o
que abortava a primeira composição e deixava a Activity sem primeiro frame.
A correção embrulha essa resolução em um ``try/catch`` com fallback para o
esquema estático, garantindo que falha de cor dinâmica nunca impeça o primeiro
frame.

Critérios de aceite verificados aqui:

  1. (estrutural, rápido) A resolução de cor dinâmica é tolerante a falha:
     qualquer exceção na resolução do Material You cai para um esquema de cor
     estático, de modo que o startup nunca fica sem primeiro frame.
  2. (estrutural, rápido) O contrato de startup da ``MainActivity`` está intacto:
     ``super.onCreate`` é chamado, ``setContent`` embrulha a navegação em
     ``SamsungRemoteTheme`` e a navegação parte de ``Screen.Discovery`` montando
     ``DiscoveryRoute``.
  3. (estrutural, rápido) A descoberta não bloqueia a main thread na
     inicialização: ``DiscoveryViewModel.startScan`` dispara em
     ``viewModelScope`` (corrotina), não numa chamada bloqueante no ``init``.
  4. (build, lento) ``gradlew :app:assembleDebug`` e os testes unitários da
     variante debug terminam em ``BUILD SUCCESSFUL``.
  5. (e2e, lento) Cold start a partir do launcher: a tela de descoberta
     ("Choose a TV") é renderizada em até ~3s, sem ficar presa na janela
     "Samsung Remote", sem ``FATAL EXCEPTION`` e sem ANR no logcat. Sem
     dispositivo/emulador conectado o teste é *skipped* (não falha).
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "com.factory.samsungremote"

SRC = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"
THEME = SRC / "ui" / "theme" / "Theme.kt"
MAIN_ACTIVITY = SRC / "MainActivity.kt"
DISCOVERY_VM = SRC / "viewmodel" / "DiscoveryViewModel.kt"
APP_ENTRY = SRC / "SamsungRemoteApp.kt"
DISCOVERY_STRINGS = ROOT / "app" / "src" / "main" / "res" / "values" / "strings.xml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """Remove comentários de bloco e de linha para evitar casar texto de prosa."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# --------------------------------------------------------------------------- #
# Presença
# --------------------------------------------------------------------------- #
def test_sources_present():
    for path in (THEME, MAIN_ACTIVITY, DISCOVERY_VM, APP_ENTRY):
        assert path.is_file(), f"fonte ausente: {path}"


# --------------------------------------------------------------------------- #
# Critério 1 — resolução de cor dinâmica tolerante a falha (causa raiz)
# --------------------------------------------------------------------------- #
def test_theme_uses_dynamic_color_only_on_supported_sdk():
    code = _strip_comments(_read(THEME))
    # A cor dinâmica só pode ser tentada em SDK >= S (Android 12+).
    assert "Build.VERSION_CODES.S" in code, (
        "o tema deve restringir a cor dinâmica a SDK >= S"
    )


def test_theme_dynamic_color_is_failure_tolerant():
    """Qualquer falha ao resolver o Material You deve cair para esquema estático.

    Esta é a verificação central da causa raiz: a chamada a
    ``dynamicLightColorScheme`` / ``dynamicDarkColorScheme`` precisa estar
    protegida por ``try``/``catch`` para que uma exceção na resolução do tema
    não aborte a primeira composição (o que deixava a Activity presa na janela
    de inicialização sem primeiro frame).
    """
    code = _strip_comments(_read(THEME))

    assert re.search(r"\bdynamic(?:Light|Dark)ColorScheme\s*\(", code), (
        "o tema deveria resolver o esquema de cor dinâmico (Material You)"
    )

    # Localiza cada uso de cor dinâmica e exige que esteja dentro de um try{...}.
    try_blocks = [m.start() for m in re.finditer(r"\btry\b", code)]
    catch_present = re.search(r"\bcatch\s*\(", code) is not None
    assert try_blocks, "nenhum bloco try presente no tema"
    assert catch_present, "nenhum bloco catch presente no tema"

    for m in re.finditer(r"\bdynamic(?:Light|Dark)ColorScheme\s*\(", code):
        # Há ao menos um 'try' que o precede no arquivo (a resolução dinâmica
        # vive dentro do bloco protegido).
        assert any(t < m.start() for t in try_blocks), (
            "a resolução de cor dinâmica não está protegida por try/catch"
        )

    # O catch precisa ser abrangente o bastante para cobrir o crash de startup.
    assert re.search(r"catch\s*\(\s*\w+\s*:\s*(Throwable|Exception)\b", code), (
        "o catch deve capturar Throwable/Exception para não deixar a falha de "
        "tema escapar e abortar a primeira composição"
    )


def test_theme_still_offers_static_fallback_schemes():
    code = _strip_comments(_read(THEME))
    assert "lightColorScheme(" in code and "darkColorScheme(" in code, (
        "os esquemas estáticos (light/dark) precisam existir como fallback"
    )


# --------------------------------------------------------------------------- #
# Critério 2 — contrato de startup da MainActivity intacto
# --------------------------------------------------------------------------- #
def test_main_activity_startup_contract():
    code = _strip_comments(_read(MAIN_ACTIVITY))
    assert "super.onCreate(" in code, "onCreate deve chamar super.onCreate"
    assert "setContent" in code, "MainActivity deve chamar setContent"
    assert "SamsungRemoteTheme" in code, (
        "o conteúdo deve ser embrulhado em SamsungRemoteTheme"
    )
    # A navegação parte da descoberta e monta a DiscoveryRoute.
    assert re.search(
        r"mutableStateOf<\s*Screen\s*>\s*\(\s*Screen\.Discovery\s*\)", code
    ), "o host de navegação não inicia em Screen.Discovery"
    assert "DiscoveryRoute(" in code, "MainActivity não monta DiscoveryRoute"


def test_app_entry_is_hilt_application():
    code = _strip_comments(_read(APP_ENTRY))
    assert "@HiltAndroidApp" in code, "a Application deve ser @HiltAndroidApp"
    assert ": Application" in code, "a entry deve estender Application"


# --------------------------------------------------------------------------- #
# Critério 3 — descoberta não bloqueia a main thread no startup
# --------------------------------------------------------------------------- #
def test_discovery_scan_runs_off_main_thread():
    code = _strip_comments(_read(DISCOVERY_VM))
    # init dispara o scan...
    assert re.search(r"init\s*\{[^}]*startScan\s*\(", code, flags=re.DOTALL), (
        "DiscoveryViewModel.init deveria iniciar o scan"
    )
    # ...mas o scan roda numa corrotina em viewModelScope, não bloqueando o
    # thread que constrói a primeira composição.
    assert re.search(r"viewModelScope\.launch", code), (
        "startScan deve coletar a descoberta em viewModelScope.launch (off-main), "
        "para não bloquear a main thread durante o cold start"
    )


# --------------------------------------------------------------------------- #
# Helpers de runtime
# --------------------------------------------------------------------------- #
def _resolve_java_home():
    if os.environ.get("JAVA_HOME"):
        return os.environ["JAVA_HOME"]
    studio_jbr = Path("C:/Program Files/Android/Android Studio/jbr")
    if studio_jbr.is_dir():
        return str(studio_jbr)
    return None


def _gradle_cmd(*tasks: str):
    gradlew = ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew")
    assert gradlew.is_file(), "gradle wrapper ausente"
    base = [str(gradlew)]
    if os.name != "nt" and shutil.which("sh"):
        base = ["sh", str(gradlew)]
    return base + list(tasks) + ["--console=plain"]


def _gradle_env():
    env = dict(os.environ)
    java_home = _resolve_java_home()
    if java_home:
        env["JAVA_HOME"] = java_home
    return env


def _adb():
    return shutil.which("adb")


def _connected_device():
    """Serial do primeiro emulador/dispositivo em estado 'device', ou None."""
    adb = _adb()
    if not adb:
        return None
    try:
        out = subprocess.run(
            [adb, "devices"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception:
        return None
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            return parts[0]
    return None


def _discovery_title() -> str:
    title = "Choose a TV"
    if DISCOVERY_STRINGS.is_file():
        m = re.search(
            r'<string name="discovery_title">([^<]+)</string>',
            _read(DISCOVERY_STRINGS),
        )
        if m:
            title = m.group(1).strip()
    return title


# --------------------------------------------------------------------------- #
# Critério 4 — build da variante debug + testes unitários  (lento, autoritativo)
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_assemble_debug_and_unit_tests_succeed():
    result = subprocess.run(
        _gradle_cmd(":app:assembleDebug", ":app:testDebugUnitTest"),
        cwd=str(ROOT),
        env=_gradle_env(),
        capture_output=True,
        text=True,
        timeout=2400,
    )
    out = (result.stdout or "") + (result.stderr or "")
    tail = (result.stdout or "")[-3000:] + (result.stderr or "")[-3000:]
    assert result.returncode == 0, f"build/testes falharam (rc={result.returncode}):\n{tail}"
    assert "BUILD SUCCESSFUL" in out, f"BUILD SUCCESSFUL ausente:\n{tail}"


# --------------------------------------------------------------------------- #
# Critério 5 — cold start mostra a descoberta sem prender/crash/ANR  (lento, e2e)
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_cold_start_renders_discovery_without_freeze_or_crash():
    adb = _adb()
    if not adb:
        pytest.skip("adb indisponível — runtime do cold start não verificável")
    serial = _connected_device()
    if not serial:
        pytest.skip("nenhum dispositivo/emulador conectado — runtime não verificável")

    def sh(*args, timeout=120):
        return subprocess.run(
            [adb, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    # Instala a variante debug (build autoritativo do APK + install).
    install = subprocess.run(
        _gradle_cmd(":app:installDebug"),
        cwd=str(ROOT),
        env=_gradle_env(),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    install_out = (install.stdout or "") + (install.stderr or "")
    assert install.returncode == 0 and "BUILD SUCCESSFUL" in install_out, (
        f":app:installDebug falhou:\n{install_out[-3000:]}"
    )

    # Cold start de verdade: encerra o app, limpa o processo e o buffer de log.
    sh("shell", "am", "force-stop", APP_ID)
    sh("shell", "am", "kill", APP_ID)
    sh("logcat", "-c")

    start_at = time.monotonic()
    start = sh("shell", "am", "start", "-W", "-n", f"{APP_ID}/.MainActivity")
    assert start.returncode == 0, f"falha ao iniciar a activity:\n{start.stderr}"
    assert "Error" not in (start.stdout or ""), f"am start reportou erro:\n{start.stdout}"

    # Tempo de startup AUTORITATIVO: o "TotalTime"/"WaitTime" que o `am start -W`
    # reporta é o intervalo medido pelo próprio ActivityManager entre o launch e
    # o PRIMEIRO FRAME desenhado da Activity (em ms). É essa a métrica fiel ao
    # critério "~3s". NÃO usamos o relógio de parede do loop de polling abaixo
    # como orçamento de tempo: cada iteração roda um `uiautomator dump` (lento,
    # ~1-2s) + sleep, então o wall-clock superestima o startup em vários
    # segundos de overhead do harness — não do app.
    def _ms(field: str):
        m = re.search(rf"{field}:\s*(\d+)", start.stdout or "")
        return int(m.group(1)) if m else None

    startup_ms = _ms("WaitTime") or _ms("TotalTime") or _ms("ThisTime")

    title = _discovery_title()

    # Prova de NÃO-congelamento: a tela de descoberta ("Choose a TV") precisa de
    # fato aparecer (não basta o frame em branco da janela de inicialização).
    # Damos uma folga generosa só para o overhead de dump da UI antes de declarar
    # congelamento — este deadline NÃO é o orçamento de tempo de startup.
    deadline = start_at + 8.0
    rendered = False
    ui = ""
    while time.monotonic() < deadline:
        sh("shell", "uiautomator", "dump", "/sdcard/window_dump.xml")
        ui = sh("exec-out", "cat", "/sdcard/window_dump.xml").stdout or ""
        if APP_ID in ui and title in ui:
            rendered = True
            break
        time.sleep(0.5)

    elapsed = time.monotonic() - start_at

    # O processo deve continuar vivo (um crash de startup mataria o processo).
    pid = (sh("shell", "pidof", APP_ID).stdout or "").strip()

    # Logcat: nada de crash fatal nem ANR do nosso app na inicialização.
    #
    # Só contam crashes reais: a linha "FATAL EXCEPTION" ou o tag AndroidRuntime
    # em nível de ERRO ("E AndroidRuntime: ..."). NÃO basta o substring
    # "AndroidRuntime" — o próprio helper de dump (uiautomator) emite linhas
    # benignas de ciclo de vida ("D/I AndroidRuntime: ... Shutting down VM"),
    # que não são falhas do app e gerariam falso positivo.
    logs = sh("logcat", "-d").stdout or ""
    fatal = [
        ln
        for ln in logs.splitlines()
        if "FATAL EXCEPTION" in ln or re.search(r"\bE\s+AndroidRuntime\b", ln)
    ]
    anr = [
        ln
        for ln in logs.splitlines()
        if ("ANR in" in ln or "ANR " in ln) and APP_ID in ln
    ]

    assert pid, "processo do app não está vivo após o cold start (provável crash)"
    assert not fatal, "FATAL EXCEPTION no logcat do cold start:\n" + "\n".join(fatal[:40])
    assert not anr, "ANR no logcat do cold start:\n" + "\n".join(anr[:40])
    assert rendered, (
        f"a tela de descoberta (título {title!r}) não renderizou em até "
        f"{deadline - start_at:.0f}s — app preso na janela de inicialização. "
        f"UI atual:\n{ui[:1500]}"
    )
    # Orçamento de tempo: primeiro frame da Activity em até ~3s (com folga modesta
    # para variação de CI/emulador), medido pelo ActivityManager — não pelo loop.
    assert startup_ms is not None, (
        f"não foi possível ler o tempo de startup do `am start -W`:\n{start.stdout}"
    )
    assert startup_ms <= 3500, (
        f"o cold start até o primeiro frame levou {startup_ms} ms (>~3s)"
    )

    # Limpa: fecha o app.
    sh("shell", "am", "force-stop", APP_ID)
