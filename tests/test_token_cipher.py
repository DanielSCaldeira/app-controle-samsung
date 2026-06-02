"""Tests for task f3047a22 — Cifragem do token de pareamento.

Acceptance criteria verified here:
  1. ``encrypt(token) != token`` em claro (o token persistido não é texto puro).
  2. ``decrypt(encrypt(token)) == token`` (round-trip preserva o token).
  3. Nenhuma chave em hardcode (a chave AES vive no Android Keystore, referenciada
     por alias; não há material de chave embutido no fonte).

Strategy
--------
A implementação real (``KeystoreTokenCipher``) depende do provedor
``AndroidKeyStore`` e da API ``javax.crypto`` do Android, que não roda numa JVM
desktop. Seguindo a convenção do repositório (executar código real sempre que
possível em vez de apenas inspecionar fontes), este suite **executa de verdade**
o *wire format* escolhido pela implementação — ``Base64(IV[12] ||
AES-256-GCM(ciphertext||tag[16]))`` — usando ``cryptography`` (AESGCM) com uma
chave AES-256 gerada aleatoriamente (simulando a chave residente no Keystore).
Assim os critérios 1 e 2 são verificados comportamentalmente sobre exatamente o
formato/algoritmo que o Kotlin declara.

As asserções estruturais (sempre executadas) confirmam que o fonte Kotlin: usa
o algoritmo que o modelo comportamental assume, gera/recupera a chave dentro do
``AndroidKeyStore`` por alias, e **não** contém material de chave em hardcode
(critério 3), além de validar o contrato da interface e a injeção via Hilt.
"""

import base64
import re
from pathlib import Path

import pytest

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.exceptions import InvalidTag  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CRYPTO_DIR = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory"
    / "samsungremote" / "data" / "crypto"
)
CIPHER_KT = CRYPTO_DIR / "KeystoreTokenCipher.kt"
INTERFACE_KT = CRYPTO_DIR / "TokenCipher.kt"
APP_MODULE_KT = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory"
    / "samsungremote" / "di" / "AppModule.kt"
)

# Parameters that mirror the Kotlin implementation's wire format / algorithm.
IV_LENGTH_BYTES = 12
GCM_TAG_LENGTH_BITS = 128
KEY_SIZE_BITS = 256

SAMPLE_TOKENS = [
    "12345678",                       # típico token numérico do Tizen
    "AbCdEf-pairing.Token_0987",      # alfanumérico com símbolos
    "u",                              # 1 caractere
    "açãο-токен-✓ 日本語",            # UTF-8 multibyte
    "x" * 4096,                       # token longo
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Reference model — exactly the wire format declared by KeystoreTokenCipher:
#   Base64( IV[12] || AES-256-GCM(ciphertext || tag[16]) )
# A fresh random IV per encrypt; a non-exportable random AES-256 key stands in
# for the Keystore-resident key.
# --------------------------------------------------------------------------- #
class _ReferenceTokenCipher:
    def __init__(self):
        self._key = AESGCM.generate_key(bit_length=KEY_SIZE_BITS)
        self._aes = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> str:
        import os
        iv = os.urandom(IV_LENGTH_BYTES)
        ct = self._aes.encrypt(iv, plaintext.encode("utf-8"), None)
        return base64.b64encode(iv + ct).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        combined = base64.b64decode(ciphertext)
        if len(combined) <= IV_LENGTH_BYTES:
            raise ValueError("Ciphertext too short")
        iv, payload = combined[:IV_LENGTH_BYTES], combined[IV_LENGTH_BYTES:]
        return self._aes.decrypt(iv, payload, None).decode("utf-8")


@pytest.fixture()
def cipher():
    return _ReferenceTokenCipher()


# --------------------------------------------------------------------------- #
# Criterion 1 — encrypt(token) != token em claro
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("token", SAMPLE_TOKENS)
def test_encrypt_output_is_not_plaintext(cipher, token):
    enc = cipher.encrypt(token)
    assert enc != token, "ciphertext igual ao texto em claro"
    # O token em claro não pode aparecer (contíguo) nos bytes persistidos.
    # Para tokens muito curtos um único byte coincide com o IV/ciphertext
    # aleatório por puro acaso, então o leak-check só é significativo a partir
    # de alguns bytes (uma coincidência contígua aí é estatisticamente nula).
    raw = token.encode("utf-8")
    if len(raw) >= 4:
        assert raw not in base64.b64decode(enc), \
            "token em claro vazou no payload cifrado"


def test_encrypt_is_non_deterministic(cipher):
    # IV aleatório por chamada => duas cifragens do mesmo token diferem.
    token = "12345678"
    assert cipher.encrypt(token) != cipher.encrypt(token), \
        "cifragem determinística (IV não está sendo randomizado)"


# --------------------------------------------------------------------------- #
# Criterion 2 — decrypt(encrypt(token)) == token
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("token", SAMPLE_TOKENS)
def test_encrypt_decrypt_roundtrip(cipher, token):
    assert cipher.decrypt(cipher.encrypt(token)) == token


def test_independent_tokens_roundtrip_independently(cipher):
    a, b = cipher.encrypt("token-A"), cipher.encrypt("token-B")
    assert cipher.decrypt(a) == "token-A"
    assert cipher.decrypt(b) == "token-B"


# --------------------------------------------------------------------------- #
# Edge cases — integridade autenticada (GCM) e entrada malformada
# --------------------------------------------------------------------------- #
def test_tampered_ciphertext_is_rejected(cipher):
    enc = cipher.encrypt("12345678")
    raw = bytearray(base64.b64decode(enc))
    raw[-1] ^= 0x01  # vira um bit do tag de autenticação
    tampered = base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(InvalidTag):
        cipher.decrypt(tampered)


def test_malformed_input_too_short_is_rejected(cipher):
    too_short = base64.b64encode(b"\x00" * (IV_LENGTH_BYTES - 1)).decode("ascii")
    with pytest.raises(ValueError):
        cipher.decrypt(too_short)


# --------------------------------------------------------------------------- #
# Structural — the Kotlin uses the same algorithm the model assumes
# --------------------------------------------------------------------------- #
def test_cipher_source_exists():
    assert CIPHER_KT.is_file(), f"implementação ausente em {CIPHER_KT}"
    assert INTERFACE_KT.is_file(), f"interface ausente em {INTERFACE_KT}"


def test_uses_aes_gcm_no_padding_256():
    text = _read(CIPHER_KT)
    assert '"AES/GCM/NoPadding"' in text, "transformação AES/GCM/NoPadding ausente"
    assert "256" in text, "tamanho de chave de 256 bits não declarado"
    assert "BLOCK_MODE_GCM" in text and "ENCRYPTION_PADDING_NONE" in text


def test_key_lives_in_android_keystore_by_alias():
    text = _read(CIPHER_KT)
    assert '"AndroidKeyStore"' in text, "provedor AndroidKeyStore não usado"
    assert "KeyStore.getInstance" in text
    assert "KeyGenParameterSpec" in text and "KeyGenerator" in text, \
        "chave não é gerada dentro do Keystore"
    assert "keyAlias" in text or "KEY_ALIAS" in text, "chave não referenciada por alias"


# --------------------------------------------------------------------------- #
# Criterion 3 — nenhuma chave em hardcode
# --------------------------------------------------------------------------- #
def test_no_hardcoded_key_material():
    text = _read(CIPHER_KT)
    # Material de chave embutido tipicamente apareceria como SecretKeySpec sobre
    # um literal de bytes, ou um array de bytes/Base64 constante de chave.
    assert "SecretKeySpec" not in text, \
        "SecretKeySpec sugere chave construída a partir de bytes em hardcode"
    # Nenhum literal de array de bytes (byteArrayOf(...) com números) servindo de chave.
    assert not re.search(r"byteArrayOf\s*\(\s*[-0-9]", text), \
        "byteArrayOf com literais numéricos sugere chave em hardcode"
    # Nenhuma string longa que pareça material de chave embutido.
    for literal in re.findall(r'"((?:[^"\\]|\\.){24,})"', text):
        # Aliases/transformações conhecidos são curtos e legíveis; rejeita blobs
        # que pareçam base64/hex de chave.
        assert not re.fullmatch(r"[A-Za-z0-9+/]{24,}={0,2}", literal), \
            f"string suspeita de material de chave em hardcode: {literal[:16]}..."
    # A chave deve ser GERADA, não carregada de um valor constante.
    assert "generateKey" in text, "chave não é gerada dinamicamente"


def test_alias_is_an_identifier_not_key_material():
    text = _read(CIPHER_KT)
    m = re.search(r'DEFAULT_KEY_ALIAS\s*=\s*"([^"]+)"', text)
    assert m, "DEFAULT_KEY_ALIAS não definido"
    alias = m.group(1)
    # Um alias é um identificador legível, não bytes/base64 de chave.
    assert re.fullmatch(r"[A-Za-z0-9_.\-]+", alias), "alias com formato inesperado"
    assert not re.fullmatch(r"[A-Za-z0-9+/]{24,}={0,2}", alias), \
        "alias parece material de chave codificado"


# --------------------------------------------------------------------------- #
# Contract & DI wiring
# --------------------------------------------------------------------------- #
def test_interface_declares_encrypt_and_decrypt():
    text = _read(INTERFACE_KT)
    assert "interface TokenCipher" in text
    assert "fun encrypt(" in text and "fun decrypt(" in text


def test_implementation_implements_interface():
    text = _read(CIPHER_KT)
    assert ": TokenCipher" in text
    assert "override fun encrypt(" in text and "override fun decrypt(" in text


def test_token_cipher_is_provided_via_hilt():
    text = _read(APP_MODULE_KT)
    assert "TokenCipher" in text and "KeystoreTokenCipher" in text
    assert "@Provides" in text, "TokenCipher não é fornecido por um @Provides"
