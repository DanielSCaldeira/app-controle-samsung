package com.factory.samsungremote.data.db

import androidx.room.Room
import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Instrumented tests for [KnownTvDao] backed by an in-memory Room database, plus
 * a schema/migration sanity check via [MigrationTestHelper].
 *
 * Covers the task acceptance criteria:
 *  - insert a [KnownTv] and recover it by id,
 *  - update an existing [KnownTv] (upsert REPLACE semantics) and observe the change,
 *  - the exported v1 schema is created successfully (migration baseline defined).
 */
@RunWith(AndroidJUnit4::class)
class KnownTvDaoTest {

    private lateinit var db: AppDatabase
    private lateinit var dao: KnownTvDao

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        // In-memory: nothing persisted to disk, queries run on the test thread.
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        dao = db.knownTvDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    // --- Happy path: insert + recover by id --------------------------------- #
    @Test
    fun upsert_then_getById_returnsInsertedRow() = runTest {
        val tv = KnownTv(
            id = "uuid-1",
            name = "Living Room TV",
            ipAddress = "192.168.0.10",
            macAddress = "AA:BB:CC:DD:EE:FF",
            tokenEncrypted = "enc-token",
            lastConnectedAt = 1_000L,
        )

        dao.upsert(tv)

        val loaded = dao.getById("uuid-1")
        assertEquals(tv, loaded)
    }

    // --- Update: upsert with same id REPLACEs the row ----------------------- #
    @Test
    fun upsert_existingId_updatesRow() = runTest {
        val original = KnownTv(
            id = "uuid-1",
            name = "Living Room TV",
            ipAddress = "192.168.0.10",
        )
        dao.upsert(original)

        val updated = original.copy(
            name = "Bedroom TV",
            ipAddress = "192.168.0.20",
            tokenEncrypted = "fresh-token",
            lastConnectedAt = 2_000L,
        )
        dao.upsert(updated)

        val loaded = dao.getById("uuid-1")
        assertEquals(updated, loaded)
        // Still a single row — REPLACE, not a second insert.
        assertEquals(1, dao.getAll().size)
    }

    // --- getAll ordering + delete (edge cases) ------------------------------ #
    @Test
    fun getAll_isOrderedByLastConnectedDesc_andDeleteRemovesRow() = runTest {
        dao.upsert(KnownTv(id = "a", name = "A", ipAddress = "10.0.0.1", lastConnectedAt = 100L))
        dao.upsert(KnownTv(id = "b", name = "B", ipAddress = "10.0.0.2", lastConnectedAt = 300L))
        dao.upsert(KnownTv(id = "c", name = "C", ipAddress = "10.0.0.3", lastConnectedAt = 200L))

        val ids = dao.getAll().map { it.id }
        assertEquals(listOf("b", "c", "a"), ids)

        dao.delete("b")
        assertNull(dao.getById("b"))
        assertEquals(listOf("c", "a"), dao.getAll().map { it.id })
    }

    @Test
    fun getById_missing_returnsNull() = runTest {
        assertNull(dao.getById("does-not-exist"))
    }

    // --- Migration baseline: exported v1 schema is creatable ---------------- #
    @get:Rule
    val migrationHelper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        AppDatabase::class.java,
        emptyList(),
        FrameworkSQLiteOpenHelperFactory(),
    )

    @Test
    fun createsVersion1Schema() {
        // Creates the database at v1 from the exported schema; validates the
        // exported schema matches the entities and migrations are wired (empty
        // baseline is valid for v1).
        val v1 = migrationHelper.createDatabase(TEST_DB, AppDatabase.DATABASE_VERSION)
        assertTrue(v1.isOpen)
        v1.close()
        assertEquals(0, AppDatabaseMigrations.ALL.size)
    }

    companion object {
        private const val TEST_DB = "migration-test.db"
    }
}
