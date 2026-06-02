"""Tests for task "Acessibilidade e TalkBack".

Acceptance criterion:
    "Teste de acessibilidade Compose verifica que todos os botões têm descrição
     não vazia e tamanho mínimo de 48 dp."

What is verified here
---------------------
The remote-control screen is a stateless Compose UI. Compose has no runtime on
the desktop JVM, so — following the repository convention (see
``test_remote_screen.py``) — the accessibility *behaviour* is asserted by a real
instrumented Compose test (``RemoteAccessibilityTest.kt``, validated structurally
below to be genuine), while the wiring that guarantees it is asserted directly
against the sources here:

  1. **Every button carries a non-empty contentDescription.** Each button-
     rendering composable applies ``Modifier.semantics { contentDescription = … }``
     resolved from a string resource, and every such ``remote_cd_*`` string is
     present in ``strings.xml`` and non-empty (so TalkBack never announces an
     empty label). Every ``remote_cd_*`` string defined is also actually wired
     into the screen — none is dead.
  2. **Every button has a touch target ≥ 48 dp.** The screen defines a single
     ``MinTouchTarget`` ≥ 48 dp and applies it to every button via
     ``Modifier.sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)``.

These checks require no toolchain and always run.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"

SCREEN_KT = PKG / "ui" / "remote" / "RemoteScreen.kt"
STRINGS_XML = ROOT / "app" / "src" / "main" / "res" / "values" / "strings.xml"

UI_TEST_KT = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "ui" / "remote" / "RemoteAccessibilityTest.kt"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The button-rendering composables on the screen. Each MUST apply both the
# minimum touch target and a contentDescription for TalkBack.
# --------------------------------------------------------------------------- #
BUTTON_COMPOSABLES = [
    "DirButton",     # D-pad arrows (up/down/left/right)
    "OkButton",      # center OK / ENTER
    "NavButton",     # RETURN/HOME/MENU, VOL/CH, media transport
    "DigitButton",   # numeric keypad 0..9
    "ShortcutButton",  # streaming app shortcuts
]


def _composable_body(text: str, name: str) -> str:
    """Return the source slice of a private @Composable fun `name`(...) body.

    Spans from the function signature to the start of the next top-level
    ``@Composable`` declaration (or end of file).
    """
    start = text.index(f"private fun {name}(")
    rest = text[start + 1:]
    nxt = rest.find("@Composable")
    end = (start + 1 + nxt) if nxt != -1 else len(text)
    return text[start:end]


# --------------------------------------------------------------------------- #
# strings.xml parsing.
# --------------------------------------------------------------------------- #
def _string_resources() -> dict:
    root = ET.parse(STRINGS_XML).getroot()
    out = {}
    for node in root.findall("string"):
        name = node.get("name")
        # ElementTree joins text; treat None as empty.
        out[name] = (node.text or "").strip()
    return out


# --------------------------------------------------------------------------- #
# Presence.
# --------------------------------------------------------------------------- #
def test_sources_present():
    assert SCREEN_KT.is_file(), f"RemoteScreen ausente: {SCREEN_KT}"
    assert STRINGS_XML.is_file(), f"strings.xml ausente: {STRINGS_XML}"


# --------------------------------------------------------------------------- #
# Criterion 2 — minimum touch target ≥ 48 dp, applied to every button.
# --------------------------------------------------------------------------- #
def test_min_touch_target_is_at_least_48dp():
    text = _read(SCREEN_KT)
    m = re.search(r"MinTouchTarget\s*=\s*(\d+(?:\.\d+)?)\s*\.dp", text)
    assert m, "a tela deve definir um MinTouchTarget em dp"
    value = float(m.group(1))
    assert value >= 48, f"alvo de toque mínimo deve ser >= 48 dp, mas é {value} dp"


@pytest.mark.parametrize("name", BUTTON_COMPOSABLES)
def test_each_button_applies_min_touch_target(name):
    body = _composable_body(_read(SCREEN_KT), name)
    assert "sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)" in body, (
        f"o botão {name} deve aplicar o alvo mínimo via "
        f"Modifier.sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)"
    )


def test_power_icon_button_applies_min_touch_target():
    # POWER is an inline IconButton in the TopAppBar, not one of the helpers.
    text = _read(SCREEN_KT)
    start = text.index("testTag(RemoteTestTags.POWER)")
    window = text[start - 400:start + 200]
    assert "sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)" in window, (
        "o botão POWER deve aplicar o alvo mínimo de 48 dp via Modifier.sizeIn"
    )


def test_text_send_button_applies_min_touch_target():
    text = _read(SCREEN_KT)
    start = text.index("testTag(RemoteTestTags.TEXT_SEND)")
    window = text[start - 400:start + 200]
    assert "sizeIn(minWidth = MinTouchTarget, minHeight = MinTouchTarget)" in window, (
        "o botão de envio de texto deve aplicar o alvo mínimo de 48 dp"
    )


# --------------------------------------------------------------------------- #
# Criterion 1 — every button carries a (non-empty) contentDescription.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", BUTTON_COMPOSABLES)
def test_each_button_sets_content_description(name):
    body = _composable_body(_read(SCREEN_KT), name)
    assert ".semantics" in body and "contentDescription" in body, (
        f"o botão {name} deve definir um contentDescription via "
        f"Modifier.semantics {{ contentDescription = … }} para o TalkBack"
    )


def test_power_icon_button_sets_content_description():
    text = _read(SCREEN_KT)
    start = text.index("testTag(RemoteTestTags.POWER)")
    window = text[start:start + 200]
    assert "semantics" in window and "contentDescription = powerDescription" in window, (
        "o botão POWER deve expor um contentDescription para o TalkBack"
    )


def test_text_send_button_sets_content_description():
    text = _read(SCREEN_KT)
    start = text.index("testTag(RemoteTestTags.TEXT_SEND)")
    window = text[start:start + 200]
    assert "semantics" in window and "contentDescription = sendDescription" in window, (
        "o botão de envio de texto deve expor um contentDescription para o TalkBack"
    )


def test_screen_imports_semantics_apis():
    text = _read(SCREEN_KT)
    assert "androidx.compose.ui.semantics.contentDescription" in text
    assert "androidx.compose.ui.semantics.semantics" in text


# --------------------------------------------------------------------------- #
# contentDescription strings exist, are non-empty, and are all wired.
# --------------------------------------------------------------------------- #
def test_all_referenced_cd_strings_exist_and_are_non_empty():
    text = _read(SCREEN_KT)
    resources = _string_resources()
    referenced = sorted(set(re.findall(r"R\.string\.(remote_cd_\w+)", text)))
    assert referenced, "a tela não referencia nenhuma string de contentDescription"
    for key in referenced:
        assert key in resources, f"string de acessibilidade ausente em strings.xml: {key}"
        assert resources[key] != "", f"contentDescription vazio para a string: {key}"


def test_every_defined_cd_string_is_wired_into_the_screen():
    text = _read(SCREEN_KT)
    resources = _string_resources()
    defined = sorted(k for k in resources if k.startswith("remote_cd_"))
    assert defined, "nenhuma string remote_cd_* definida em strings.xml"
    referenced = set(re.findall(r"R\.string\.(remote_cd_\w+)", text))
    dead = [k for k in defined if k not in referenced]
    assert not dead, f"strings de acessibilidade definidas mas não usadas: {dead}"


def test_expected_buttons_have_dedicated_descriptions():
    # The control families called out by the task all have a description string.
    resources = _string_resources()
    expected = [
        "remote_cd_up", "remote_cd_down", "remote_cd_left", "remote_cd_right",
        "remote_cd_ok", "remote_cd_return", "remote_cd_home", "remote_cd_menu",
        "remote_cd_power",
        "remote_cd_vol_up", "remote_cd_vol_down", "remote_cd_mute",
        "remote_cd_ch_up", "remote_cd_ch_down",
        "remote_cd_rew", "remote_cd_play", "remote_cd_pause", "remote_cd_stop",
        "remote_cd_ff",
        "remote_cd_text_send", "remote_cd_digit", "remote_cd_app_launch",
    ]
    missing = [k for k in expected if not resources.get(k)]
    assert not missing, f"descrições de acessibilidade ausentes/vazias: {missing}"


# --------------------------------------------------------------------------- #
# The instrumented Compose accessibility test exists and is genuine.
# --------------------------------------------------------------------------- #
def test_compose_accessibility_test_authored():
    assert UI_TEST_KT.is_file(), f"teste de acessibilidade Compose ausente: {UI_TEST_KT}"
    text = _read(UI_TEST_KT)
    assert "createComposeRule" in text, "deve usar createComposeRule"
    assert "RemoteScreen(" in text and "setContent" in text, "deve renderizar RemoteScreen"
    # Asserts a non-empty contentDescription for every button.
    assert "SemanticsProperties.ContentDescription" in text, (
        "o teste deve inspecionar o contentDescription do nó"
    )
    assert "isNotBlank" in text, "o teste deve exigir contentDescription NÃO vazio"
    # Asserts the ≥ 48 dp touch target for every button.
    assert "assertWidthIsAtLeast(48.dp)" in text and "assertHeightIsAtLeast(48.dp)" in text, (
        "o teste deve verificar alvos de toque >= 48 dp"
    )
    assert text.count("@Test") >= 2, "deve haver testes de descrição e de tamanho"


def test_compose_accessibility_test_covers_all_button_families():
    text = _read(UI_TEST_KT)
    # Representative tags from every button family must be exercised.
    for tag in [
        "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "OK",
        "RETURN", "HOME", "MENU", "POWER",
        "VOL_UP", "VOL_DOWN", "MUTE", "CH_UP", "CH_DOWN",
        "REW", "PLAY", "PAUSE", "STOP", "FF",
        "APP_NETFLIX", "APP_PRIME", "APP_DISNEY", "APP_YOUTUBE",
        "TEXT_SEND",
    ]:
        assert f"RemoteTestTags.{tag}" in text, (
            f"o teste de acessibilidade não exercita o botão {tag}"
        )
    # The ten numeric digits are covered via the digit(n) helper.
    assert "RemoteTestTags.digit(it)" in text or "RemoteTestTags.digit(" in text, (
        "o teste de acessibilidade deve cobrir os dígitos do teclado numérico"
    )
