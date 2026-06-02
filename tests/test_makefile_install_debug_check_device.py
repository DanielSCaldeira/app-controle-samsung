"""Tests for task dfb50262 — Pré-checagem de dispositivo no alvo install-debug.

Acceptance criteria verified here:
  1. Sem device conectado, `make install-debug` exibe a mensagem de orientação
     (conectar/autorizar o celular) e ABORTA, em vez de só o stacktrace do Gradle.
  2. Com um device conectado, `make install-debug` instala o app normalmente
     (o alvo do Gradle :app:installDebug é efetivamente invocado).

Estratégia
----------
Os testes não dependem de um celular real. Eles isolam o comportamento do
Makefile criando:
  * um ``adb`` falso no início do PATH, que imprime uma lista de devices
    controlada (vazia ou com um device "device"); e
  * um ``gradlew`` falso passado via ``GRADLEW=...`` que apenas registra que
    foi chamado (grava um arquivo marcador).

Assim conseguimos validar tanto o caminho "sem device" (deve abortar antes do
Gradle) quanto o caminho "com device" (deve seguir e chamar o Gradle).
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_available() -> bool:
    return shutil.which("make") is not None


requires_make = pytest.mark.skipif(
    not _make_available(), reason="GNU make não disponível no PATH"
)


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fake_adb(devices_block: str) -> str:
    """Script de shell que imita `adb`.

    `adb devices` imprime o cabeçalho seguido do bloco fornecido. Qualquer
    outro subcomando (ex.: `adb version`) sai com sucesso silenciosamente.
    """
    return (
        "#!/bin/sh\n"
        'if [ "$1" = "devices" ]; then\n'
        '  echo "List of devices attached"\n'
        f'  printf "%s" "{devices_block}"\n'
        "  echo\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )


def _fake_gradlew(marker: Path) -> str:
    """gradlew falso: grava os argumentos recebidos no marcador e sai 0."""
    return (
        "#!/bin/sh\n"
        f'echo "$@" > "{marker.as_posix()}"\n'
        "exit 0\n"
    )


def _run_make(target: str, tmp_path: Path, *, devices_block: str):
    """Roda `make <target>` com adb/gradlew falsos.

    Retorna (CompletedProcess, marker_path). O marcador existe se e somente se
    o gradlew falso chegou a ser invocado.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)

    # adb falso no início do PATH
    fake_adb = bindir / "adb"
    _write_exec(fake_adb, _fake_adb(devices_block))

    # gradlew falso fora do PATH, referenciado por GRADLEW=...
    marker = tmp_path / "gradlew_called.txt"
    fake_gradlew = tmp_path / "fake_gradlew"
    _write_exec(fake_gradlew, _fake_gradlew(marker))

    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")

    cmd = [
        "make",
        "-C",
        str(ROOT),
        target,
        f"GRADLEW={fake_gradlew.as_posix()}",
    ]
    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result, marker


def _combined_output(result) -> str:
    return (result.stdout or "") + (result.stderr or "")


# Blocos de saída de `adb devices`
NO_DEVICE = ""
ONE_DEVICE = "emulator-5554\tdevice\n"


# --------------------------------------------------------------------------- #
# Estrutura do Makefile (asserts estáticos, rápidos)
# --------------------------------------------------------------------------- #
def test_makefile_has_check_device_target():
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "check-device:" in content, "alvo auxiliar check-device ausente"
    assert "adb devices" in content, "check-device deve reutilizar `adb devices`"


def test_install_debug_depends_on_check_device():
    content = MAKEFILE.read_text(encoding="utf-8")
    # A linha do alvo install-debug deve listar check-device como pré-requisito.
    lines = [
        ln
        for ln in content.splitlines()
        if ln.startswith("install-debug:")
    ]
    assert lines, "alvo install-debug não encontrado"
    assert any("check-device" in ln for ln in lines), (
        "install-debug não declara check-device como pré-requisito"
    )


# --------------------------------------------------------------------------- #
# Critério 1 — sem device: mensagem amigável e abort (caminho feliz negativo)
# --------------------------------------------------------------------------- #
@requires_make
def test_install_debug_without_device_aborts_with_guidance(tmp_path):
    result, marker = _run_make("install-debug", tmp_path, devices_block=NO_DEVICE)
    out = _combined_output(result)

    assert result.returncode != 0, (
        "install-debug deveria abortar (rc != 0) quando não há device.\n"
        f"saída:\n{out}"
    )
    assert not marker.exists(), (
        "Gradle (:app:installDebug) não deveria ser chamado sem device conectado."
    )

    lowered = out.lower()
    assert "nenhum dispositivo" in lowered or "dispositivo" in lowered, (
        f"mensagem não menciona dispositivo:\n{out}"
    )
    # Orientações exigidas pelo critério de aceite.
    assert "depuracao usb" in lowered or "depuração usb" in lowered, (
        f"mensagem não orienta ativar a depuração USB:\n{out}"
    )
    assert "autoriz" in lowered, (
        f"mensagem não orienta autorizar o prompt na tela:\n{out}"
    )
    assert "adb-devices" in lowered or "doctor" in lowered, (
        f"mensagem não orienta rodar make adb-devices/doctor:\n{out}"
    )
    # Não deve ser apenas um stacktrace do Gradle.
    assert "FAILURE: Build failed" not in out, (
        "sem device deveria mostrar orientação, não um stacktrace do Gradle"
    )


@requires_make
def test_check_device_target_alone_aborts_without_device(tmp_path):
    result, marker = _run_make("check-device", tmp_path, devices_block=NO_DEVICE)
    assert result.returncode != 0, "check-device deveria falhar sem device"
    assert not marker.exists(), "check-device não deve invocar o Gradle"


# --------------------------------------------------------------------------- #
# Critério 2 — com device: instala normalmente (não quebra o fluxo atual)
# --------------------------------------------------------------------------- #
@requires_make
def test_install_debug_with_device_invokes_gradle(tmp_path):
    result, marker = _run_make("install-debug", tmp_path, devices_block=ONE_DEVICE)
    out = _combined_output(result)

    assert result.returncode == 0, (
        f"install-debug deveria suceder com device conectado.\nsaída:\n{out}"
    )
    assert marker.exists(), (
        "Gradle deveria ser chamado quando há device conectado."
    )
    invoked = marker.read_text(encoding="utf-8")
    assert "installDebug" in invoked, (
        f"install-debug deveria chamar :app:installDebug (args: {invoked!r})"
    )


@requires_make
def test_check_device_target_alone_passes_with_device(tmp_path):
    result, _ = _run_make("check-device", tmp_path, devices_block=ONE_DEVICE)
    assert result.returncode == 0, (
        "check-device deveria passar quando há um device conectado.\n"
        f"saída:\n{_combined_output(result)}"
    )
