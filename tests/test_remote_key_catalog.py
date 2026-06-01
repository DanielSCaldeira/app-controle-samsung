"""Tests for task 2ee68fec — Catálogo estático de RemoteKey.

Acceptance criteria verified here:
  1. O catálogo contém >= 30 teclas.
  2. Todos os códigos (RemoteKey.code) são únicos.
  3. Cada categoria (KeyCategory) tem ao menos uma entrada.

The catalog is implemented in Kotlin (Android module). Following the
established test convention in this repository (pytest assertions over the
generated Kotlin sources), these tests parse ``RemoteKey.kt`` and
``RemoteKeyCatalog.kt`` and assert the structural properties required by the
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
REMOTE_KEY_KT = REGISTRY / "RemoteKey.kt"
CATALOG_KT = REGISTRY / "RemoteKeyCatalog.kt"

# RemoteKey("KEY_X", KeyCategory.NAV, "Label")
_ENTRY_RE = re.compile(
    r'RemoteKey\(\s*"(?P<code>[^"]+)"\s*,\s*KeyCategory\.(?P<category>\w+)\s*,'
    r'\s*"(?P<label>[^"]*)"\s*,?\s*\)'
)
# enum class KeyCategory { NAV, MEDIA, ... }
_ENUM_RE = re.compile(r"enum\s+class\s+KeyCategory\s*\{(?P<body>.*?)\}", re.DOTALL)


def _source_files_exist():
    assert REMOTE_KEY_KT.is_file(), f"RemoteKey.kt não encontrado em {REGISTRY}"
    assert CATALOG_KT.is_file(), f"RemoteKeyCatalog.kt não encontrado em {REGISTRY}"


def _parse_entries():
    text = CATALOG_KT.read_text(encoding="utf-8")
    return [m.groupdict() for m in _ENTRY_RE.finditer(text)]


def _parse_categories():
    text = REMOTE_KEY_KT.read_text(encoding="utf-8")
    m = _ENUM_RE.search(text)
    assert m, "enum class KeyCategory não encontrada em RemoteKey.kt"
    body = m.group("body")
    # strip kdoc/line comments, then collect bare identifiers ending with comma
    names = []
    for raw in body.splitlines():
        line = raw.split("//", 1)[0].strip().rstrip(",").strip()
        if line and re.fullmatch(r"[A-Z_][A-Z0-9_]*", line):
            names.append(line)
    return names


def test_source_files_present():
    _source_files_exist()


def test_remote_key_is_immutable_data_class():
    """RemoteKey é uma data class imutável (campos val: code, category, label)."""
    text = REMOTE_KEY_KT.read_text(encoding="utf-8")
    assert "data class RemoteKey" in text, "RemoteKey não é uma data class"
    assert re.search(r"val\s+code\s*:", text), "campo 'code' deve ser val (imutável)"
    assert re.search(r"val\s+category\s*:", text), "campo 'category' deve ser val (imutável)"
    assert re.search(r"val\s+label\s*:", text), "campo 'label' deve ser val (imutável)"
    assert not re.search(r"\bvar\s+(code|category|label)\b", text), (
        "RemoteKey não deve ter campos mutáveis (var)"
    )


def test_catalog_has_at_least_30_keys():
    _source_files_exist()
    entries = _parse_entries()
    assert len(entries) >= 30, (
        f"catálogo deve conter >= 30 teclas, encontrado {len(entries)}"
    )


def test_catalog_codes_are_unique():
    _source_files_exist()
    codes = [e["code"] for e in _parse_entries()]
    dups = [c for c, n in Counter(codes).items() if n > 1]
    assert not dups, f"códigos duplicados encontrados: {dups}"


def test_every_category_has_at_least_one_entry():
    _source_files_exist()
    categories = set(_parse_categories())
    assert categories, "nenhuma categoria declarada em KeyCategory"
    used = Counter(e["category"] for e in _parse_entries())
    # toda categoria usada deve ser uma categoria declarada
    unknown = set(used) - categories
    assert not unknown, f"categorias usadas mas não declaradas no enum: {unknown}"
    # cada categoria declarada deve ter >= 1 entrada
    missing = [cat for cat in categories if used.get(cat, 0) == 0]
    assert not missing, f"categorias sem nenhuma tecla no catálogo: {missing}"


@pytest.mark.parametrize(
    "code",
    [
        "KEY_VOLUP", "KEY_VOLDOWN", "KEY_MUTE",
        "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_ENTER",
        "KEY_HOME", "KEY_RETURN", "KEY_MENU", "KEY_POWER",
        "KEY_CHUP", "KEY_CHDOWN",
        "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
        "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9",
        "KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_REW", "KEY_FF",
        "KEY_SOURCE", "KEY_INFO",
    ],
)
def test_expected_samsung_key_present(code):
    """Cada tecla Samsung enumerada na descrição da tarefa está no catálogo."""
    _source_files_exist()
    codes = {e["code"] for e in _parse_entries()}
    assert code in codes, f"tecla esperada ausente do catálogo: {code}"
