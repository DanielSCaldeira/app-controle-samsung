"""Tests for task ca2ec82c — Scaffold do projeto Android + Gradle + DI.

Acceptance criteria verified here:
  1. Project compiles with `./gradlew assembleDebug` (produces a debug APK).
  2. App opens an empty Compose Activity (MainActivity uses setContent + Compose).
  3. Hilt modules installed (Application annotated with @HiltAndroidApp).
  4. Package/directory structure ui/viewmodel/data/network/di created.

The Gradle build is the slow, authoritative check and is exercised by
``test_assemble_debug_succeeds``. The remaining tests are fast structural
assertions over the generated sources/configuration.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_SRC = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"


def _read(rel: Path) -> str:
    return rel.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Criterion 4 — package / directory structure
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "package",
    ["ui", "viewmodel", "data", "network", "di"],
)
def test_architecture_package_exists(package):
    pkg_dir = APP_SRC / package
    assert pkg_dir.is_dir(), f"pacote '{package}' ausente em {APP_SRC}"


# --------------------------------------------------------------------------- #
# Criterion 3 — Hilt Application
# --------------------------------------------------------------------------- #
def test_application_is_hilt_android_app():
    app_kt = APP_SRC / "SamsungRemoteApp.kt"
    assert app_kt.is_file(), "SamsungRemoteApp.kt não encontrado"
    content = _read(app_kt)
    assert "@HiltAndroidApp" in content, "Application não anotada com @HiltAndroidApp"
    assert ": Application" in content, "Application não estende android.app.Application"


def test_hilt_module_installed():
    module = APP_SRC / "di" / "AppModule.kt"
    assert module.is_file(), "di/AppModule.kt não encontrado"
    content = _read(module)
    assert "@Module" in content
    assert "@InstallIn" in content


def test_manifest_registers_application_and_launcher():
    manifest = ROOT / "app" / "src" / "main" / "AndroidManifest.xml"
    content = _read(manifest)
    assert 'android:name=".SamsungRemoteApp"' in content, "Application não registrada no manifest"
    assert 'android:name=".MainActivity"' in content, "MainActivity não registrada no manifest"
    assert "android.intent.action.MAIN" in content and "LAUNCHER" in content, "launcher activity ausente"


# --------------------------------------------------------------------------- #
# Criterion 2 — empty Compose Activity
# --------------------------------------------------------------------------- #
def test_main_activity_is_compose_and_hilt_entrypoint():
    activity = APP_SRC / "MainActivity.kt"
    assert activity.is_file(), "MainActivity.kt não encontrado"
    content = _read(activity)
    assert "setContent" in content, "MainActivity não usa Compose (setContent)"
    assert "ComponentActivity" in content, "MainActivity não estende ComponentActivity"
    assert "@AndroidEntryPoint" in content, "MainActivity não é um @AndroidEntryPoint"


# --------------------------------------------------------------------------- #
# Build configuration sanity (minSdk + required dependencies)
# --------------------------------------------------------------------------- #
def test_min_sdk_is_26():
    build_gradle = _read(ROOT / "app" / "build.gradle.kts")
    assert "minSdk = 26" in build_gradle, "minSdk 26 não configurado"


@pytest.mark.parametrize(
    "marker",
    [
        "androidx.compose",      # Compose
        "okhttp",                # OkHttp
        "kotlinx-coroutines",    # Coroutines / Flow
        "androidx.room",         # Room
        "com.google.dagger",     # Hilt
        "androidx.security",     # Jetpack Security / Tink
    ],
)
def test_required_dependency_present(marker):
    catalog = _read(ROOT / "gradle" / "libs.versions.toml")
    assert marker in catalog, f"dependência '{marker}' ausente no version catalog"


# --------------------------------------------------------------------------- #
# Criterion 1 — `./gradlew assembleDebug` compiles
# --------------------------------------------------------------------------- #
def _resolve_java_home():
    if os.environ.get("JAVA_HOME"):
        return os.environ["JAVA_HOME"]
    studio_jbr = Path("C:/Program Files/Android/Android Studio/jbr")
    if studio_jbr.is_dir():
        return str(studio_jbr)
    return None


@pytest.mark.slow
def test_assemble_debug_succeeds():
    gradlew = ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew")
    assert gradlew.is_file(), "gradle wrapper ausente"

    env = dict(os.environ)
    java_home = _resolve_java_home()
    if java_home:
        env["JAVA_HOME"] = java_home

    if os.name == "nt":
        cmd = [str(gradlew), "assembleDebug", "--console=plain"]
    elif shutil.which("sh"):
        cmd = ["sh", str(gradlew), "assembleDebug", "--console=plain"]
    else:
        cmd = [str(gradlew), "assembleDebug", "--console=plain"]

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    tail = (result.stdout or "")[-3000:] + (result.stderr or "")[-3000:]
    assert result.returncode == 0, f"assembleDebug falhou (rc={result.returncode}):\n{tail}"

    apk = ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    assert apk.is_file(), "app-debug.apk não foi gerado"
