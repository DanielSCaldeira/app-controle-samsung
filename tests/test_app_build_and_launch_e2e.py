"""Tests for task ebe05cc9 — Verificar build e execução de ponta a ponta do app.

Acceptance criteria verified here:

  1. `gradlew :app:build` termina em BUILD SUCCESSFUL (assemble + unit tests +
     lint da variante padrão).
  2. O app instala e abre direto no fluxo funcional (tela de descoberta), sem
     crash no logcat na inicialização.

Estratégia:

  * Critérios estruturais rápidos garantem que o *contrato de navegação* que
    sustenta o item 2 está presente no código-fonte sem depender de
    dispositivo: a única activity exportada é a `MainActivity` LAUNCHER, e o
    host de navegação parte de `Screen.Discovery`.
  * O item 1 é exercido por ``test_app_build_succeeds`` (marcado ``slow``), que
    roda o build autoritativo e exige ``BUILD SUCCESSFUL``.
  * O item 2 é exercido de ponta a ponta por
    ``test_app_installs_and_opens_discovery_without_crash`` (marcado ``slow``),
    que instala via ``:app:installDebug``, lança a ``MainActivity`` no
    dispositivo/emulador conectado, confirma que ela é a activity resumida, que
    o processo continua vivo, varre o logcat por ``FATAL EXCEPTION`` e valida
    via ``uiautomator`` que a tela de descoberta está renderizada. Sem
    dispositivo conectado o teste é *skipped* (não falha).
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "com.factory.samsungremote"

MANIFEST = ROOT / "app" / "src" / "main" / "AndroidManifest.xml"
APP_BUILD = ROOT / "app" / "build.gradle.kts"
MAIN_ACTIVITY = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"
    / "MainActivity.kt"
)
DISCOVERY_STRINGS = ROOT / "app" / "src" / "main" / "res" / "values" / "strings.xml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Presence
# --------------------------------------------------------------------------- #
def test_sources_present():
    for path in (MANIFEST, APP_BUILD, MAIN_ACTIVITY):
        assert path.is_file(), f"fonte ausente: {path}"


# --------------------------------------------------------------------------- #
# Criterion 2 (estrutural) — único ponto de entrada é a MainActivity LAUNCHER
# --------------------------------------------------------------------------- #
def test_manifest_single_exported_launcher_activity():
    tree = ET.parse(MANIFEST)
    ns = {"android": "http://schemas.android.com/apk/res/android"}
    activities = tree.findall(".//application/activity")
    assert activities, "manifest não declara nenhuma activity"

    launchers = []
    for act in activities:
        name = act.get(f"{{{ns['android']}}}name")
        has_main = act.find(
            "./intent-filter/action[@android:name='android.intent.action.MAIN']", ns
        )
        has_launcher = act.find(
            "./intent-filter/category"
            "[@android:name='android.intent.category.LAUNCHER']",
            ns,
        )
        if has_main is not None and has_launcher is not None:
            assert act.get(f"{{{ns['android']}}}exported") == "true", (
                f"activity LAUNCHER {name} precisa ser exported=true para abrir"
            )
            launchers.append(name)

    assert launchers == [".MainActivity"], (
        f"esperava exatamente uma activity LAUNCHER (.MainActivity), obtive {launchers}"
    )


def test_application_id_matches_app_id():
    build = _read(APP_BUILD)
    assert re.search(rf'applicationId\s*=\s*"{re.escape(APP_ID)}"', build), (
        f"applicationId esperado ({APP_ID}) ausente em app/build.gradle.kts"
    )


# --------------------------------------------------------------------------- #
# Criterion 2 (estrutural) — fluxo de navegação parte da descoberta
# --------------------------------------------------------------------------- #
def test_navigation_starts_on_discovery():
    src = _read(MAIN_ACTIVITY)
    # O estado inicial do host de navegação deve ser a tela de descoberta.
    assert re.search(
        r"mutableStateOf<\s*Screen\s*>\s*\(\s*Screen\.Discovery\s*\)", src
    ), "o host de navegação não inicia em Screen.Discovery"
    # E a descoberta deve renderizar a rota de descoberta.
    assert "DiscoveryRoute(" in src, "MainActivity não monta DiscoveryRoute"


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


# --------------------------------------------------------------------------- #
# Criterion 1 — gradlew :app:build → BUILD SUCCESSFUL  (lento, autoritativo)
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_app_build_succeeds():
    result = subprocess.run(
        _gradle_cmd(":app:build"),
        cwd=str(ROOT),
        env=_gradle_env(),
        capture_output=True,
        text=True,
        timeout=2400,
    )
    out = (result.stdout or "") + (result.stderr or "")
    tail = (result.stdout or "")[-3000:] + (result.stderr or "")[-3000:]
    assert result.returncode == 0, f":app:build falhou (rc={result.returncode}):\n{tail}"
    assert "BUILD SUCCESSFUL" in out, f"BUILD SUCCESSFUL ausente:\n{tail}"


# --------------------------------------------------------------------------- #
# Criterion 2 — instala, abre na descoberta e não crasha  (lento, e2e)
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_app_installs_and_opens_discovery_without_crash():
    adb = _adb()
    if not adb:
        pytest.skip("adb indisponível — não é possível verificar runtime")
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

    # Estado limpo: para o app e limpa o buffer de log.
    sh("shell", "am", "force-stop", APP_ID)
    sh("logcat", "-c")

    # Lança a activity de entrada.
    start = sh("shell", "am", "start", "-n", f"{APP_ID}/.MainActivity")
    assert start.returncode == 0, f"falha ao iniciar a activity:\n{start.stderr}"
    assert "Error" not in (start.stdout or ""), f"am start reportou erro:\n{start.stdout}"

    # Aguarda a inicialização estabilizar (poll por activity resumida).
    resumed = ""
    for _ in range(15):
        dump = sh("shell", "dumpsys", "activity", "activities").stdout or ""
        m = re.search(r"(?:topResumedActivity|ResumedActivity)[^\n]*", dump)
        resumed = m.group(0) if m else ""
        if f"{APP_ID}/.MainActivity" in resumed:
            break
        subprocess.run(["sleep", "1"], timeout=5)
    assert f"{APP_ID}/.MainActivity" in resumed, (
        f"MainActivity não é a activity resumida; topo atual: {resumed!r}"
    )

    # Processo deve continuar vivo (um crash mataria o processo).
    pid = (sh("shell", "pidof", APP_ID).stdout or "").strip()
    assert pid, "processo do app não está vivo após a inicialização (provável crash)"

    # Logcat não pode conter crash fatal do nosso app.
    logs = sh("logcat", "-d").stdout or ""
    fatal = [
        ln
        for ln in logs.splitlines()
        if "FATAL EXCEPTION" in ln or "AndroidRuntime" in ln
    ]
    assert not fatal, "crash detectado no logcat na inicialização:\n" + "\n".join(
        fatal[:40]
    )

    # A tela renderizada deve ser a de descoberta. Confirmamos via uiautomator
    # procurando o título da descoberta declarado em strings.xml.
    title = "Choose a TV"
    if DISCOVERY_STRINGS.is_file():
        m = re.search(
            r'<string name="discovery_title">([^<]+)</string>',
            _read(DISCOVERY_STRINGS),
        )
        if m:
            title = m.group(1).strip()

    sh("shell", "uiautomator", "dump", "/sdcard/window_dump.xml")
    ui = sh("exec-out", "cat", "/sdcard/window_dump.xml").stdout or ""
    assert APP_ID in ui, "o dump da UI não pertence ao app esperado"
    assert title in ui, (
        f"a tela de descoberta (título {title!r}) não está renderizada na "
        f"inicialização"
    )

    # Limpa: fecha o app.
    sh("shell", "am", "force-stop", APP_ID)
