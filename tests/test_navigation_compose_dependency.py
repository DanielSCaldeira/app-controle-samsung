"""Tests for task 2c48831e — Adicionar dependência navigation-compose.

Acceptance criteria verified here:
  1. O catálogo (`gradle/libs.versions.toml`) declara a dependência
     `androidx.navigation:navigation-compose`: uma versão dedicada e um alias
     de *library* que a referencia.
  2. `app/build.gradle.kts` consome esse alias como `implementation(...)`.
  3. `gradlew :app:assembleDebug` continua terminando em BUILD SUCCESSFUL com a
     dependência resolvida (teste lento, autoritativo).

Os critérios 1 e 2 são verificados por assertivas estruturais rápidas sobre o
catálogo e o build script. O critério 3 é exercido por
``test_assemble_debug_resolves_navigation_compose`` (marcado ``slow``).
"""

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "gradle" / "libs.versions.toml"
APP_BUILD = ROOT / "app" / "build.gradle.kts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _catalog() -> dict:
    with CATALOG.open("rb") as fh:
        return tomllib.load(fh)


# --------------------------------------------------------------------------- #
# Presence
# --------------------------------------------------------------------------- #
def test_sources_present():
    assert CATALOG.is_file(), f"catálogo ausente: {CATALOG}"
    assert APP_BUILD.is_file(), f"build script ausente: {APP_BUILD}"


# --------------------------------------------------------------------------- #
# Criterion 1 — catálogo declara navigation-compose (versão + alias library)
# --------------------------------------------------------------------------- #
def test_catalog_declares_navigation_compose_library():
    cat = _catalog()
    libraries = cat.get("libraries", {})

    # Encontra o(s) alias(es) que apontam para androidx.navigation:navigation-compose
    matches = {
        alias: spec
        for alias, spec in libraries.items()
        if isinstance(spec, dict)
        and spec.get("group") == "androidx.navigation"
        and spec.get("name") == "navigation-compose"
    }
    assert matches, (
        "nenhum alias de library aponta para "
        "androidx.navigation:navigation-compose no catálogo"
    )

    versions = cat.get("versions", {})
    for alias, spec in matches.items():
        ref = spec.get("version", {})
        # Aceita tanto version.ref quanto version literal embutida.
        if isinstance(ref, dict) and "ref" in ref:
            version_key = ref["ref"]
            assert version_key in versions, (
                f"alias '{alias}' referencia versão '{version_key}' "
                f"inexistente em [versions]"
            )
            assert str(versions[version_key]).strip(), (
                f"versão '{version_key}' está vazia"
            )
        else:
            # version literal (string) — deve ser não vazia
            assert str(spec.get("version", "")).strip(), (
                f"alias '{alias}' não declara uma versão válida"
            )


def test_navigation_compose_distinct_from_hilt_navigation():
    """O alias hilt-navigation-compose já existia e NÃO fornece NavHost/NavController.
    A nova dependência deve ser o artefato androidx.navigation:navigation-compose,
    distinto de androidx.hilt:hilt-navigation-compose."""
    libraries = _catalog().get("libraries", {})

    nav = [
        a for a, s in libraries.items()
        if isinstance(s, dict)
        and s.get("group") == "androidx.navigation"
        and s.get("name") == "navigation-compose"
    ]
    hilt_nav = [
        a for a, s in libraries.items()
        if isinstance(s, dict)
        and s.get("group") == "androidx.hilt"
        and s.get("name") == "hilt-navigation-compose"
    ]
    assert nav, "androidx.navigation:navigation-compose ausente"
    assert hilt_nav, "androidx.hilt:hilt-navigation-compose deveria continuar presente"
    assert set(nav).isdisjoint(set(hilt_nav)), (
        "navigation-compose e hilt-navigation-compose não podem ser o mesmo alias"
    )


# --------------------------------------------------------------------------- #
# Criterion 2 — app/build.gradle.kts consome o alias como implementation
# --------------------------------------------------------------------------- #
def test_app_build_references_navigation_compose_as_implementation():
    libraries = _catalog().get("libraries", {})
    aliases = [
        a for a, s in libraries.items()
        if isinstance(s, dict)
        and s.get("group") == "androidx.navigation"
        and s.get("name") == "navigation-compose"
    ]
    assert aliases, "pré-condição: alias navigation-compose deve existir no catálogo"

    build = _read(APP_BUILD)

    # Aliases do catálogo são acessados em Kotlin DSL com '.' no lugar de '-'.
    def accessor(alias: str) -> str:
        return "libs." + alias.replace("-", ".")

    used = [
        a for a in aliases
        if re.search(
            r"implementation\(\s*" + re.escape(accessor(a)) + r"\s*\)",
            build,
        )
    ]
    assert used, (
        "app/build.gradle.kts não declara "
        f"implementation({accessor(aliases[0])}) "
        "(ou equivalente para o alias navigation-compose)"
    )


# --------------------------------------------------------------------------- #
# Criterion 3 — assembleDebug resolve a dependência (BUILD SUCCESSFUL)
# --------------------------------------------------------------------------- #
def _resolve_java_home():
    if os.environ.get("JAVA_HOME"):
        return os.environ["JAVA_HOME"]
    studio_jbr = Path("C:/Program Files/Android/Android Studio/jbr")
    if studio_jbr.is_dir():
        return str(studio_jbr)
    return None


@pytest.mark.slow
def test_assemble_debug_resolves_navigation_compose():
    gradlew = ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew")
    assert gradlew.is_file(), "gradle wrapper ausente"

    env = dict(os.environ)
    java_home = _resolve_java_home()
    if java_home:
        env["JAVA_HOME"] = java_home

    if os.name == "nt":
        cmd = [str(gradlew), ":app:assembleDebug", "--console=plain"]
    elif shutil.which("sh"):
        cmd = ["sh", str(gradlew), ":app:assembleDebug", "--console=plain"]
    else:
        cmd = [str(gradlew), ":app:assembleDebug", "--console=plain"]

    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    out = (result.stdout or "") + (result.stderr or "")
    tail = (result.stdout or "")[-3000:] + (result.stderr or "")[-3000:]
    assert result.returncode == 0, f":app:assembleDebug falhou (rc={result.returncode}):\n{tail}"
    assert "BUILD SUCCESSFUL" in out, f"BUILD SUCCESSFUL ausente na saída:\n{tail}"

    apk = ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    assert apk.is_file(), "app-debug.apk não foi gerado"
