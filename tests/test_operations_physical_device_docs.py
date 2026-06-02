"""Tests for task 096d2e8a — Documentar instalação em celular físico e
resolver 'No connected devices!'.

Acceptance criteria verified here:
  1. docs/operations.md tem instruções claras para conectar um celular físico
     por **USB** (Opções do desenvolvedor + Depuração USB + autorização RSA) e
     **sem fio** (adb pair / adb connect em Android 11+).
  2. Há verificação do device com `make doctor` / `make adb-devices` antes de
     instalar, e o fluxo termina em `make install-debug` + `make app-start`.
  3. A tabela de Troubleshooting (§6/§7) tem uma entrada para
     'No connected devices!' citando `make doctor`/`make adb-devices` e
     `make install-debug`, deixando claro que o build já funcionou.

São checagens estruturais sobre o texto do guia; como reforço (caso de borda),
confirmamos que os alvos do Makefile referenciados pela doc realmente existem,
de modo que seguir os passos com um aparelho conectado executa comandos válidos.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPERATIONS = ROOT / "docs" / "operations.md"
MAKEFILE = ROOT / "Makefile"

DEVICE_EXCEPTION = "com.android.builder.testing.api.DeviceException: No connected devices!"


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert OPERATIONS.is_file(), f"{OPERATIONS} não encontrado"
    return OPERATIONS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc_lower(doc_text) -> str:
    return doc_text.lower()


# --------------------------------------------------------------------------- #
# Criterion 1 — instruções de conexão por USB
# --------------------------------------------------------------------------- #
def test_doc_mentions_developer_options_and_usb_debugging(doc_lower):
    assert "opções do desenvolvedor" in doc_lower, "doc não cita 'Opções do desenvolvedor'"
    assert "depuração usb" in doc_lower, "doc não cita 'Depuração USB'"


def test_doc_mentions_rsa_authorization_prompt(doc_lower):
    # A autorização RSA / prompt "Permitir depuração USB" no aparelho.
    assert "rsa" in doc_lower, "doc não menciona a autorização/impressão digital RSA"
    assert "permitir" in doc_lower, "doc não orienta aceitar o prompt de autorização"


def test_doc_explains_unauthorized_state(doc_lower):
    assert "unauthorized" in doc_lower, "doc não explica o status 'unauthorized' do adb"


# --------------------------------------------------------------------------- #
# Criterion 1 — instruções de conexão sem fio (Android 11+)
# --------------------------------------------------------------------------- #
def test_doc_documents_wireless_debugging(doc_text, doc_lower):
    assert "adb pair" in doc_lower, "doc não documenta `adb pair`"
    assert "adb connect" in doc_lower, "doc não documenta `adb connect`"
    # Deixar claro que é recurso de Android 11+.
    assert "android 11" in doc_lower, "doc não indica que o pareamento sem fio é Android 11+"


# --------------------------------------------------------------------------- #
# Criterion 2 — verificar device antes de instalar e fluxo final
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "command",
    ["make doctor", "make adb-devices", "make install-debug", "make app-start"],
)
def test_doc_references_required_make_commands(doc_lower, command):
    assert command in doc_lower, f"doc não referencia `{command}`"


def test_verification_precedes_install_in_doc(doc_text):
    """`make doctor`/`make adb-devices` devem aparecer antes do `make install-debug`."""
    install_idx = doc_text.find("make install-debug")
    doctor_idx = doc_text.find("make doctor")
    devices_idx = doc_text.find("make adb-devices")
    assert install_idx != -1, "`make install-debug` ausente na doc"
    first_check = min(i for i in (doctor_idx, devices_idx) if i != -1)
    assert first_check < install_idx, (
        "a verificação do device (doctor/adb-devices) deve ser documentada "
        "antes do passo de instalação"
    )


# --------------------------------------------------------------------------- #
# Criterion 3 — troubleshooting da 'No connected devices!'
# --------------------------------------------------------------------------- #
def test_doc_contains_device_exception_string(doc_text):
    assert DEVICE_EXCEPTION in doc_text, (
        "doc não cita a mensagem de erro exata 'No connected devices!'"
    )


def test_troubleshooting_table_has_no_connected_devices_entry(doc_text):
    """A entrada de troubleshooting (linha de tabela `|`) deve citar o erro e
    apontar para doctor/adb-devices + install-debug."""
    table_rows = [
        ln for ln in doc_text.splitlines()
        if ln.strip().startswith("|") and "No connected devices!" in ln
    ]
    assert table_rows, "nenhuma linha da tabela de troubleshooting cita 'No connected devices!'"
    row = " ".join(table_rows).lower()
    assert "make doctor" in row or "make adb-devices" in row, (
        "entrada de troubleshooting não cita `make doctor`/`make adb-devices`"
    )
    assert "make install-debug" in row, (
        "entrada de troubleshooting não cita `make install-debug`"
    )


def test_doc_clarifies_build_works_without_device(doc_lower):
    """Deixar claro que o build já funciona e o erro é só ausência de device."""
    # procura uma frase que conecte 'build' a 'sucesso/funciona/gerado' e a
    # ausência de device/emulador.
    assert "build" in doc_lower
    assert ("emulador" in doc_lower or "device" in doc_lower)
    assert any(
        kw in doc_lower for kw in ("sucesso", "funciona", "gerado", "não exige", "nao exige")
    ), "doc não deixa claro que o build em si funcionou apesar do erro"


# --------------------------------------------------------------------------- #
# Caso de borda — os alvos do Makefile citados pela doc existem de fato
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "target",
    ["doctor", "adb-devices", "install-debug", "app-start"],
)
def test_referenced_make_targets_exist(target):
    assert MAKEFILE.is_file(), "Makefile não encontrado"
    content = MAKEFILE.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(target)}:", re.MULTILINE)
    assert pattern.search(content), (
        f"alvo `{target}` referenciado na doc não existe no Makefile"
    )
