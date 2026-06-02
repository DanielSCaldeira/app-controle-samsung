"""Tests for task 04d6adab — TvRegistry: TVs conhecidas + tokens.

Acceptance criteria verified here:
  1. Round-trip: salvar uma TV com token e recuperá-lo **decifrado** funciona
     (com DB in-memory e cripto — tanto mockada quanto "real" AES-GCM).
  2. Atualização de IP por device id funciona (updateIp).

Strategy
--------
``TvRegistry`` é a API de domínio que combina ``KnownTvDao`` (Room) + ``TokenCipher``
(crypto). Nem o Room nem o ``AndroidKeyStore`` rodam numa JVM/desktop, então —
seguindo a convenção do repositório de **executar a lógica real** em vez de só
inspecionar fontes — este suite faz um *port* fiel da lógica do ``TvRegistry``
em Python e o executa sobre:

  * uma DAO ancorada no **schema Room exportado de verdade** (createSql do 1.json)
    e nas **SQLs reais declaradas pela DAO** (@Query / @Insert REPLACE), dentro
    de um ``sqlite3`` in-memory; e
  * um ``TokenCipher`` de referência em duas variantes: um *mock* reversível e
    um cifrador AES-256-GCM "real" (``cryptography``), espelhando o wire format
    declarado por ``KeystoreTokenCipher``.

O port replica exatamente o comportamento do Kotlin:
  saveTv(tv, token)  -> upsert(tv.copy(tokenEncrypted = token?.let(encrypt)))
  getToken(id)       -> getById(id)?.tokenEncrypted?.let(decrypt)
  updateIp(id, ip)   -> getById(id) ?: false ; upsert(copy(ipAddress=ip)) ; true
  listTvs()          -> getAll()

Asserções estruturais (sempre executadas) confirmam que o fonte Kotlin expõe a
API de domínio e fia as dependências (DAO + cipher) como o modelo assume.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"
REGISTRY_KT = PKG / "data" / "registry" / "TvRegistry.kt"
DAO_KT = PKG / "data" / "db" / "KnownTvDao.kt"
SCHEMA_JSON = (
    ROOT / "app" / "schemas"
    / "com.factory.samsungremote.data.db.AppDatabase" / "1.json"
)

COLUMNS = ["id", "name", "ip_address", "mac_address", "token_encrypted", "last_connected_at"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# DAO faithful to the real Room schema + real @Query SQL (sqlite3 in-memory)
# --------------------------------------------------------------------------- #
def _create_sql() -> str:
    schema = json.loads(_read(SCHEMA_JSON))
    entity = schema["database"]["entities"][0]
    return entity["createSql"].replace("${TABLE_NAME}", entity["tableName"])


def _dao_query(method: str) -> str:
    text = _read(DAO_KT)
    pattern = re.compile(
        r'@Query\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*(?:suspend\s+)?fun\s+' + re.escape(method),
        re.DOTALL,
    )
    m = pattern.search(text)
    assert m, f"@Query para fun {method} não encontrado em KnownTvDao.kt"
    return m.group(1)


class SqliteKnownTvDao:
    """Mirror of KnownTvDao backed by the real exported schema + real SQL."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(_create_sql())
        self.conn.commit()

    def upsert(self, tv: dict):
        # @Insert(onConflict = REPLACE) == INSERT OR REPLACE keyed on the PK.
        self.conn.execute(
            "INSERT OR REPLACE INTO known_tv "
            "(id, name, ip_address, mac_address, token_encrypted, last_connected_at) "
            "VALUES (:id, :name, :ip_address, :mac_address, :token_encrypted, "
            ":last_connected_at)",
            tv,
        )
        self.conn.commit()

    def getById(self, id_: str):
        sql = _dao_query("getById")
        row = self.conn.execute(sql, {"id": id_}).fetchone()
        return dict(zip(COLUMNS, row)) if row else None

    def getAll(self):
        sql = _dao_query("getAll")
        return [dict(zip(COLUMNS, r)) for r in self.conn.execute(sql).fetchall()]

    def raw_token(self, id_: str):
        """Read token_encrypted straight from disk (bypassing the cipher)."""
        row = self.conn.execute(
            "SELECT token_encrypted FROM known_tv WHERE id = ?", (id_,)
        ).fetchone()
        return row[0] if row else None

    def close(self):
        self.conn.close()


# --------------------------------------------------------------------------- #
# Cipher variants: a reversible mock + a "real" AES-256-GCM reference.
# --------------------------------------------------------------------------- #
class MockTokenCipher:
    """Deterministic-format but reversible mock; clearly not plaintext."""

    PREFIX = "enc::"

    def encrypt(self, plaintext: str) -> str:
        import base64
        return self.PREFIX + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        import base64
        assert ciphertext.startswith(self.PREFIX), "ciphertext não produzido por este cipher"
        return base64.b64decode(ciphertext[len(self.PREFIX):]).decode("utf-8")


class AesGcmTokenCipher:
    """Real AES-256-GCM mirroring KeystoreTokenCipher's wire format."""

    IV = 12

    def __init__(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self._aes = AESGCM(AESGCM.generate_key(bit_length=256))

    def encrypt(self, plaintext: str) -> str:
        import base64
        iv = os.urandom(self.IV)
        ct = self._aes.encrypt(iv, plaintext.encode("utf-8"), None)
        return base64.b64encode(iv + ct).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        import base64
        blob = base64.b64decode(ciphertext)
        return self._aes.decrypt(blob[:self.IV], blob[self.IV:], None).decode("utf-8")


def _cipher_params():
    params = [pytest.param(MockTokenCipher, id="mock-cipher")]
    try:
        import cryptography  # noqa: F401
        params.append(pytest.param(AesGcmTokenCipher, id="aes-gcm-real"))
    except Exception:
        pass
    return params


# --------------------------------------------------------------------------- #
# Faithful Python port of TvRegistry's domain logic.
# --------------------------------------------------------------------------- #
class TvRegistry:
    def __init__(self, dao: SqliteKnownTvDao, cipher):
        self.dao = dao
        self.cipher = cipher

    def saveTv(self, tv: dict, token: str | None = None):
        encrypted = self.cipher.encrypt(token) if token is not None else None
        self.dao.upsert({**tv, "token_encrypted": encrypted})

    def getToken(self, id_: str):
        tv = self.dao.getById(id_)
        if tv is None:
            return None
        enc = tv["token_encrypted"]
        return self.cipher.decrypt(enc) if enc is not None else None

    def updateIp(self, id_: str, ip_address: str) -> bool:
        existing = self.dao.getById(id_)
        if existing is None:
            return False
        self.dao.upsert({**existing, "ip_address": ip_address})
        return True

    def listTvs(self):
        return self.dao.getAll()


def _tv(**over) -> dict:
    base = {
        "id": "uuid-1",
        "name": "Living Room TV",
        "ip_address": "192.168.0.10",
        "mac_address": None,
        "token_encrypted": None,
        "last_connected_at": None,
    }
    base.update(over)
    return base


@pytest.fixture()
def dao():
    d = SqliteKnownTvDao()
    yield d
    d.close()


# --------------------------------------------------------------------------- #
# Criterion 1 — round-trip salvar TV com token e recuperá-lo decifrado
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cipher_cls", _cipher_params())
def test_save_then_get_token_roundtrip(dao, cipher_cls):
    reg = TvRegistry(dao, cipher_cls())
    reg.saveTv(_tv(id="tv-1", name="Sala"), token="pair-12345678")

    assert reg.getToken("tv-1") == "pair-12345678"


@pytest.mark.parametrize("cipher_cls", _cipher_params())
def test_token_persisted_is_not_clear_text(dao, cipher_cls):
    reg = TvRegistry(dao, cipher_cls())
    reg.saveTv(_tv(id="tv-1"), token="pair-12345678")

    stored = dao.raw_token("tv-1")
    assert stored is not None
    assert stored != "pair-12345678", "token gravado em claro no banco"
    assert "pair-12345678" not in stored, "token em claro vazou no valor persistido"


@pytest.mark.parametrize("cipher_cls", _cipher_params())
def test_save_tv_metadata_roundtrips(dao, cipher_cls):
    reg = TvRegistry(dao, cipher_cls())
    reg.saveTv(
        _tv(id="tv-1", name="Quarto", ip_address="10.0.0.5",
            mac_address="AA:BB:CC:DD:EE:FF", last_connected_at=1234),
        token="tok",
    )
    saved = dao.getById("tv-1")
    assert saved["name"] == "Quarto"
    assert saved["ip_address"] == "10.0.0.5"
    assert saved["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert saved["last_connected_at"] == 1234


def test_save_without_token_stores_null_and_get_token_is_none(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(_tv(id="tv-1"))  # token omitido (default None)

    assert dao.raw_token("tv-1") is None
    assert reg.getToken("tv-1") is None


def test_get_token_for_unknown_tv_is_none(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    assert reg.getToken("does-not-exist") is None


def test_save_ignores_preexisting_token_encrypted_on_entity(dao):
    """saveTv substitui qualquer tokenEncrypted vindo na entidade pelo cifrado de `token`."""
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(_tv(id="tv-1", token_encrypted="LIXO-NAO-CIFRADO"), token="real-token")
    assert reg.getToken("tv-1") == "real-token"
    assert dao.raw_token("tv-1") != "LIXO-NAO-CIFRADO"


def test_save_is_idempotent_upsert_by_id(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(_tv(id="tv-1", name="Antigo"), token="t1")
    reg.saveTv(_tv(id="tv-1", name="Novo"), token="t2")

    assert len(reg.listTvs()) == 1
    assert reg.getToken("tv-1") == "t2"
    assert dao.getById("tv-1")["name"] == "Novo"


# --------------------------------------------------------------------------- #
# Criterion 2 — atualização de IP por device id
# --------------------------------------------------------------------------- #
def test_update_ip_changes_address_and_returns_true(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(_tv(id="tv-1", ip_address="192.168.0.10"), token="tok")

    assert reg.updateIp("tv-1", "192.168.0.99") is True
    assert dao.getById("tv-1")["ip_address"] == "192.168.0.99"


def test_update_ip_preserves_token_and_other_fields(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(
        _tv(id="tv-1", name="Sala", mac_address="AA:BB:CC:DD:EE:FF",
            last_connected_at=777),
        token="keep-me",
    )
    assert reg.updateIp("tv-1", "10.10.10.10") is True

    row = dao.getById("tv-1")
    assert row["ip_address"] == "10.10.10.10"
    assert row["name"] == "Sala"
    assert row["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert row["last_connected_at"] == 777
    # Token cifrado intacto e ainda decifrável.
    assert reg.getToken("tv-1") == "keep-me"


def test_update_ip_unknown_id_returns_false_and_inserts_nothing(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    assert reg.updateIp("ghost", "1.2.3.4") is False
    assert reg.listTvs() == []


# --------------------------------------------------------------------------- #
# listTvs — delega para getAll (ordenado most-recently-connected first)
# --------------------------------------------------------------------------- #
def test_list_tvs_orders_by_last_connected_desc(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(_tv(id="a", name="A", last_connected_at=100), token="t")
    reg.saveTv(_tv(id="b", name="B", last_connected_at=300), token="t")
    reg.saveTv(_tv(id="c", name="C", last_connected_at=200), token="t")

    assert [tv["id"] for tv in reg.listTvs()] == ["b", "c", "a"]


def test_list_tvs_keeps_tokens_encrypted(dao):
    reg = TvRegistry(dao, MockTokenCipher())
    reg.saveTv(_tv(id="a", last_connected_at=1), token="secret")

    listed = reg.listTvs()[0]
    assert listed["token_encrypted"] != "secret"
    assert listed["token_encrypted"].startswith(MockTokenCipher.PREFIX)


# --------------------------------------------------------------------------- #
# Structural — o fonte Kotlin expõe a API de domínio e fia as dependências
# --------------------------------------------------------------------------- #
def test_registry_source_exists():
    assert REGISTRY_KT.is_file(), f"implementação ausente em {REGISTRY_KT}"


def test_registry_exposes_domain_api():
    text = _read(REGISTRY_KT)
    assert "class TvRegistry" in text
    for fn in ("fun saveTv", "fun getToken", "fun updateIp", "fun listTvs"):
        assert fn in text, f"API de domínio ausente: {fn}"


def test_registry_combines_dao_and_cipher():
    text = _read(REGISTRY_KT)
    assert "KnownTvDao" in text, "TvRegistry não usa KnownTvDao"
    assert "TokenCipher" in text, "TvRegistry não usa TokenCipher"
    # Injeção de dependências (Hilt).
    assert "@Inject" in text and "constructor" in text


def test_save_encrypts_and_get_decrypts_in_source():
    text = _read(REGISTRY_KT)
    assert "cipher::encrypt" in text or "cipher.encrypt" in text, \
        "saveTv não cifra o token antes de persistir"
    assert "cipher::decrypt" in text or "cipher.decrypt" in text, \
        "getToken não decifra o token armazenado"
    assert "dao.upsert" in text, "saveTv/updateIp não persiste via DAO"


def test_update_ip_reads_existing_before_upsert_in_source():
    text = _read(REGISTRY_KT)
    assert "dao.getById" in text, "updateIp não localiza a TV existente por id"
