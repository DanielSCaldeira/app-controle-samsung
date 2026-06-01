"""Tests for task 0f3b5ecd — Catálogo estático de AppShortcut.

Acceptance criteria verified here:
  1. O catálogo confirma a presença dos 4 apps (Netflix, Prime Video,
     Disney+, YouTube) com appId não vazio.
  2. O catálogo é facilmente extensível: uma única lista imutável declarada
     em um único arquivo.

The catalog is implemented in Kotlin (Android module). Following the
established test convention in this repository (pytest assertions over the
generated Kotlin sources), these tests parse ``AppShortcut.kt`` and
``AppShortcutCatalog.kt`` and assert the structural properties required by the
acceptance criteria.
"""

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = (
    ROOT
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "factory"
    / "samsungremote"
    / "data"
    / "registry"
)
APP_SHORTCUT_KT = REGISTRY / "AppShortcut.kt"
CATALOG_KT = REGISTRY / "AppShortcutCatalog.kt"

# AppShortcut(appId = "11101200001", name = "Netflix")  (deepLinkKey optional)
_ENTRY_RE = re.compile(
    r'AppShortcut\(\s*'
    r'appId\s*=\s*"(?P<appId>[^"]*)"\s*,\s*'
    r'name\s*=\s*"(?P<name>[^"]*)"\s*'
    r'(?:,\s*deepLinkKey\s*=\s*(?:"(?P<deepLinkKey>[^"]*)"|null)\s*)?'
    r',?\s*\)'
)
# val shortcuts: List<AppShortcut> = listOf( ... )
_LIST_RE = re.compile(
    r"val\s+shortcuts\s*:\s*List<AppShortcut>\s*=\s*listOf\(",
)

EXPECTED_APPS = ["Netflix", "Prime Video", "Disney+", "YouTube"]


def _source_files_exist():
    assert APP_SHORTCUT_KT.is_file(), f"AppShortcut.kt não encontrado em {REGISTRY}"
    assert CATALOG_KT.is_file(), f"AppShortcutCatalog.kt não encontrado em {REGISTRY}"


def _parse_entries():
    text = CATALOG_KT.read_text(encoding="utf-8")
    return [m.groupdict() for m in _ENTRY_RE.finditer(text)]


def test_source_files_present():
    _source_files_exist()


def test_app_shortcut_is_immutable_data_class():
    """AppShortcut é uma data class imutável (appId, name, deepLinkKey? val)."""
    text = APP_SHORTCUT_KT.read_text(encoding="utf-8")
    assert "data class AppShortcut" in text, "AppShortcut não é uma data class"
    assert re.search(r"val\s+appId\s*:", text), "campo 'appId' deve ser val (imutável)"
    assert re.search(r"val\s+name\s*:", text), "campo 'name' deve ser val (imutável)"
    assert re.search(r"val\s+deepLinkKey\s*:\s*String\?", text), (
        "campo opcional 'deepLinkKey: String?' deve existir e ser val"
    )
    assert not re.search(r"\bvar\s+(appId|name|deepLinkKey)\b", text), (
        "AppShortcut não deve ter campos mutáveis (var)"
    )


def test_catalog_has_the_four_expected_apps():
    """Critério 1: presença dos 4 apps esperados."""
    _source_files_exist()
    names = {e["name"] for e in _parse_entries()}
    missing = [app for app in EXPECTED_APPS if app not in names]
    assert not missing, f"apps esperados ausentes do catálogo: {missing}"


@pytest.mark.parametrize("app_name", EXPECTED_APPS)
def test_each_expected_app_has_non_empty_appid(app_name):
    """Critério 1: cada app esperado possui appId não vazio."""
    _source_files_exist()
    by_name = {e["name"]: e for e in _parse_entries()}
    assert app_name in by_name, f"app esperado ausente: {app_name}"
    app_id = by_name[app_name]["appId"].strip()
    assert app_id, f"appId vazio para o app {app_name!r}"


def test_netflix_app_id_matches_tizen_id():
    """Netflix usa o appId Tizen documentado (11101200001)."""
    _source_files_exist()
    by_name = {e["name"]: e for e in _parse_entries()}
    assert by_name.get("Netflix", {}).get("appId") == "11101200001", (
        "Netflix deve usar o appId Tizen 11101200001"
    )


def test_all_app_ids_non_empty_and_unique():
    """Caso de borda: nenhum appId vazio e nenhum duplicado em todo o catálogo."""
    _source_files_exist()
    app_ids = [e["appId"].strip() for e in _parse_entries()]
    assert app_ids, "nenhum AppShortcut encontrado no catálogo"
    assert all(app_ids), "há AppShortcut com appId vazio"
    dups = [a for a, n in Counter(app_ids).items() if n > 1]
    assert not dups, f"appIds duplicados encontrados: {dups}"


def test_catalog_is_single_extensible_list():
    """Critério 2: catálogo é uma única lista imutável em um único arquivo."""
    _source_files_exist()
    text = CATALOG_KT.read_text(encoding="utf-8")
    matches = _LIST_RE.findall(text)
    assert len(matches) == 1, (
        "o catálogo deve expor exatamente uma lista 'shortcuts: List<AppShortcut>'"
    )
    assert "var shortcuts" not in text, "a lista do catálogo deve ser imutável (val)"


def test_catalog_has_configurable_fallback():
    """A descrição da tarefa pede fallback configurável."""
    _source_files_exist()
    text = CATALOG_KT.read_text(encoding="utf-8")
    assert re.search(r"\bfallback\b", text), "catálogo deve declarar um fallback"
