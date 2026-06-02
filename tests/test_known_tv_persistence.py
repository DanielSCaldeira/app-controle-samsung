"""Tests for task 15ad45c5 — Persistência Room: KnownTv + DAO.

Acceptance criteria verified here:
  1. An in-memory database insert + recover-by-id round-trips a KnownTv.
  2. Updating (upsert) an existing KnownTv replaces the row in place.
  3. A migration baseline is defined (schema exported, version + registry wired).

Strategy
--------
Room 2.6.1 DAOs cannot be exercised on a desktop JVM (Room requires Android's
SQLite + KSP-generated code). The companion *instrumented* test
``app/src/androidTest/.../data/db/KnownTvDaoTest.kt`` runs on a device/emulator
with ``Room.inMemoryDatabaseBuilder`` and is the canonical acceptance artifact.

To genuinely *execute* the persistence contract on the desktop (mirroring the
repo convention of running real code rather than only inspecting sources), this
suite builds the table from the **real exported Room schema** (createSql in
``app/schemas/.../1.json``) inside an in-memory ``sqlite3`` database and replays
the **real SQL declared by the DAO** (@Query strings + @Insert REPLACE
strategy). Insert / getById / update / getAll-ordering / delete are asserted
against that, so the entity columns and DAO queries are checked behaviourally.

Structural fallbacks (always run) assert the Kotlin sources expose the required
API and configuration.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = (
    ROOT / "app" / "src" / "main" / "java" / "com" / "factory"
    / "samsungremote" / "data" / "db"
)
ENTITY_KT = DB_DIR / "KnownTv.kt"
DAO_KT = DB_DIR / "KnownTvDao.kt"
DATABASE_KT = DB_DIR / "AppDatabase.kt"
MIGRATIONS_KT = DB_DIR / "AppDatabaseMigrations.kt"
SCHEMA_JSON = (
    ROOT / "app" / "schemas"
    / "com.factory.samsungremote.data.db.AppDatabase" / "1.json"
)
INSTRUMENTED_TEST = (
    ROOT / "app" / "src" / "androidTest" / "java" / "com" / "factory"
    / "samsungremote" / "data" / "db" / "KnownTvDaoTest.kt"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Helpers — pull the real schema + DAO SQL and apply Room semantics in sqlite3
# --------------------------------------------------------------------------- #
def _create_sql() -> str:
    schema = json.loads(_read(SCHEMA_JSON))
    entity = schema["database"]["entities"][0]
    # Room templates the real table name as ${TABLE_NAME}.
    return entity["createSql"].replace("${TABLE_NAME}", entity["tableName"])


def _dao_query(method: str) -> str:
    """Extract the SQL of a @Query-annotated DAO method by function name."""
    text = _read(DAO_KT)
    # @Query("...")\n ... fun <method>(
    pattern = re.compile(
        r'@Query\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*(?:suspend\s+)?fun\s+' + re.escape(method),
        re.DOTALL,
    )
    m = pattern.search(text)
    assert m, f"@Query para fun {method} não encontrado em KnownTvDao.kt"
    return m.group(1)


def _to_named(sql: str) -> str:
    """Convert Room ``:param`` placeholders to sqlite3 ``:param`` (already compatible)."""
    return sql


COLUMNS = ["id", "name", "ip_address", "mac_address", "token_encrypted", "last_connected_at"]


def _row_to_dict(row):
    return dict(zip(COLUMNS, row)) if row else None


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute(_create_sql())
    yield c
    c.close()


def _upsert(conn, tv: dict):
    # Mirrors @Insert(onConflict = REPLACE): INSERT OR REPLACE on the PK.
    conn.execute(
        "INSERT OR REPLACE INTO known_tv "
        "(id, name, ip_address, mac_address, token_encrypted, last_connected_at) "
        "VALUES (:id, :name, :ip_address, :mac_address, :token_encrypted, :last_connected_at)",
        tv,
    )
    conn.commit()


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


# --------------------------------------------------------------------------- #
# Criterion 1 — insert + recover by id (behavioural, real schema + DAO SQL)
# --------------------------------------------------------------------------- #
def test_insert_and_get_by_id_roundtrip(conn):
    tv = _tv(
        mac_address="AA:BB:CC:DD:EE:FF",
        token_encrypted="enc-token",
        last_connected_at=1_000,
    )
    _upsert(conn, tv)

    sql = _to_named(_dao_query("getById"))
    row = conn.execute(sql, {"id": "uuid-1"}).fetchone()
    assert _row_to_dict(row) == tv


def test_get_by_id_missing_returns_none(conn):
    sql = _to_named(_dao_query("getById"))
    assert conn.execute(sql, {"id": "nope"}).fetchone() is None


# --------------------------------------------------------------------------- #
# Criterion 2 — update via upsert REPLACE keeps a single, updated row
# --------------------------------------------------------------------------- #
def test_upsert_updates_existing_row_in_place(conn):
    _upsert(conn, _tv())
    updated = _tv(
        name="Bedroom TV",
        ip_address="192.168.0.20",
        token_encrypted="fresh-token",
        last_connected_at=2_000,
    )
    _upsert(conn, updated)

    get_by_id = _to_named(_dao_query("getById"))
    row = conn.execute(get_by_id, {"id": "uuid-1"}).fetchone()
    assert _row_to_dict(row) == updated

    # REPLACE, not a duplicate insert.
    count = conn.execute("SELECT COUNT(*) FROM known_tv").fetchone()[0]
    assert count == 1


# --------------------------------------------------------------------------- #
# DAO completeness — getAll ordering and delete behave as declared
# --------------------------------------------------------------------------- #
def test_get_all_orders_by_last_connected_desc(conn):
    _upsert(conn, _tv(id="a", name="A", ip_address="10.0.0.1", last_connected_at=100))
    _upsert(conn, _tv(id="b", name="B", ip_address="10.0.0.2", last_connected_at=300))
    _upsert(conn, _tv(id="c", name="C", ip_address="10.0.0.3", last_connected_at=200))

    sql = _dao_query("getAll")
    ids = [r[0] for r in conn.execute(sql).fetchall()]
    assert ids == ["b", "c", "a"]


def test_delete_removes_only_the_targeted_row(conn):
    _upsert(conn, _tv(id="a", name="A", ip_address="10.0.0.1"))
    _upsert(conn, _tv(id="b", name="B", ip_address="10.0.0.2"))

    delete_sql = _to_named(_dao_query("delete"))
    conn.execute(delete_sql, {"id": "a"})
    conn.commit()

    ids = [r[0] for r in conn.execute("SELECT id FROM known_tv").fetchall()]
    assert ids == ["b"]


# --------------------------------------------------------------------------- #
# Criterion 3 — migration baseline / exported schema
# --------------------------------------------------------------------------- #
def test_schema_is_exported_for_version_1():
    assert SCHEMA_JSON.is_file(), f"schema Room v1 não exportado em {SCHEMA_JSON}"
    schema = json.loads(_read(SCHEMA_JSON))
    assert schema["database"]["version"] == 1
    entity = schema["database"]["entities"][0]
    assert entity["tableName"] == "known_tv"
    exported_cols = {f["columnName"] for f in entity["fields"]}
    assert exported_cols == set(COLUMNS)


def test_database_declares_version_and_export():
    text = _read(DATABASE_KT)
    assert "entities = [KnownTv::class]" in text
    assert "exportSchema = true" in text
    assert "DATABASE_VERSION = 1" in text
    assert "abstract fun knownTvDao(): KnownTvDao" in text


def test_migrations_registry_is_defined():
    assert MIGRATIONS_KT.is_file(), "AppDatabaseMigrations.kt ausente"
    text = _read(MIGRATIONS_KT)
    # A migration registry must exist and be wired; v1 baseline is empty.
    assert "AppDatabaseMigrations" in text
    assert "Array<Migration>" in text
    assert "ALL" in text


# --------------------------------------------------------------------------- #
# Structural — entity / DAO API present
# --------------------------------------------------------------------------- #
def test_entity_declares_required_fields():
    text = _read(ENTITY_KT)
    assert "@Entity" in text and 'tableName = "known_tv"' in text
    assert "@PrimaryKey" in text
    for field in ("id", "name", "ipAddress", "macAddress", "tokenEncrypted", "lastConnectedAt"):
        assert field in text, f"campo '{field}' ausente em KnownTv"
    # Optional fields are nullable.
    assert "macAddress: String? = null" in text
    assert "tokenEncrypted: String? = null" in text
    assert "lastConnectedAt: Long? = null" in text


def test_dao_declares_required_operations():
    text = _read(DAO_KT)
    assert "@Dao" in text
    assert "@Insert(onConflict = OnConflictStrategy.REPLACE)" in text
    for fn in ("fun upsert", "fun getById", "fun getAll", "fun delete"):
        assert fn in text, f"operação ausente no DAO: {fn}"


# --------------------------------------------------------------------------- #
# Instrumented test artifact present and uses in-memory Room
# --------------------------------------------------------------------------- #
def test_instrumented_test_exists_and_uses_in_memory_room():
    assert INSTRUMENTED_TEST.is_file(), f"teste instrumentado ausente em {INSTRUMENTED_TEST}"
    text = _read(INSTRUMENTED_TEST)
    assert "inMemoryDatabaseBuilder" in text, "teste instrumentado não usa Room in-memory"
    assert "@RunWith(AndroidJUnit4::class)" in text
    assert "MigrationTestHelper" in text, "teste de migração/esquema ausente"
    assert "getById" in text and "upsert" in text
