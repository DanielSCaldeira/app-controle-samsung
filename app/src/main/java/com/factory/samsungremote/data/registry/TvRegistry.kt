package com.factory.samsungremote.data.registry

import com.factory.samsungremote.data.crypto.TokenCipher
import com.factory.samsungremote.data.crypto.TokenCipherException
import com.factory.samsungremote.data.db.KnownTv
import com.factory.samsungremote.data.db.KnownTvDao
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Domain-level registry for the Samsung TVs the user has discovered and/or
 * paired with.
 *
 * It is the single entry point the rest of the app uses to remember TVs: it
 * combines the persistence layer ([KnownTvDao]) with the crypto layer
 * ([TokenCipher]) so that callers never have to deal with encryption or Room
 * details directly. Pairing tokens are *always* encrypted before they touch the
 * database and are only decrypted on demand via [getToken]; they are never kept
 * in clear text on disk.
 *
 * All operations are `suspend` functions and delegate their I/O to the DAO,
 * which performs the actual database access off the main thread.
 */
@Singleton
class TvRegistry @Inject constructor(
    private val dao: KnownTvDao,
    private val cipher: TokenCipher,
) {

    /**
     * Persists [tv], (re)setting its pairing token to [token].
     *
     * The supplied [tv] should carry the clear-text-free metadata (id, name,
     * ip, mac, …); any [KnownTv.tokenEncrypted] value already on it is ignored
     * and replaced by the encrypted form of [token]:
     *  - when [token] is non-`null`, it is encrypted with [cipher] and stored,
     *  - when [token] is `null`, the stored token is cleared.
     *
     * Insertion is an idempotent upsert keyed on [KnownTv.id]: saving a TV whose
     * id already exists replaces the existing row in place.
     */
    suspend fun saveTv(tv: KnownTv, token: String? = null) {
        val encrypted = token?.let(cipher::encrypt)
        dao.upsert(tv.copy(tokenEncrypted = encrypted))
    }

    /**
     * (Re)sets only the pairing token of an already-stored TV, leaving every
     * other field — name, ip, `mac_address`, `last_connected_at` — untouched.
     *
     * This is what the live session uses when the TV rotates its token
     * mid-connection (see
     * [com.factory.samsungremote.network.session.TokenStore]): unlike [saveTv],
     * it cannot silently blank out fields the caller does not know about.
     *
     * @return `true` when a matching TV was found and updated, `false` when no TV
     *         with that id is stored (the caller can then insert one).
     */
    suspend fun saveToken(id: String, token: String): Boolean {
        val existing = dao.getById(id) ?: return false
        dao.upsert(existing.copy(tokenEncrypted = cipher.encrypt(token)))
        return true
    }

    /**
     * Clears the stored token of the TV identified by [id], keeping the TV
     * itself registered. Used when the TV answers `ms.channel.unauthorized`: the
     * token is dead, so the next connection must run a full handshake instead of
     * replaying a value the TV will keep rejecting.
     */
    suspend fun clearToken(id: String) {
        val existing = dao.getById(id) ?: return
        if (existing.tokenEncrypted == null) return
        dao.upsert(existing.copy(tokenEncrypted = null))
    }

    /**
     * Returns the decrypted pairing token for the TV with the given [id], or
     * `null` if the TV is unknown or has no token stored.
     *
     * A stored token that cannot be decrypted (Keystore key regenerated after a
     * restore/reinstall, tampered row) is treated as "no token" rather than an
     * error: it is dropped from the row and `null` is returned, so the flow falls
     * back to a normal pairing handshake instead of failing on every attempt.
     */
    suspend fun getToken(id: String): String? {
        val encrypted = dao.getById(id)?.tokenEncrypted ?: return null
        return try {
            cipher.decrypt(encrypted)
        } catch (_: TokenCipherException) {
            clearToken(id)
            null
        }
    }

    /**
     * Updates the last-known [ipAddress] of the TV identified by [id], leaving
     * every other field (including the encrypted token) untouched.
     *
     * @return `true` if a matching TV was found and updated, `false` if no TV
     *         with that id is stored.
     */
    suspend fun updateIp(id: String, ipAddress: String): Boolean {
        val existing = dao.getById(id) ?: return false
        dao.upsert(existing.copy(ipAddress = ipAddress))
        return true
    }

    /**
     * Returns all stored TVs, ordered most-recently-connected first.
     *
     * The returned [KnownTv] records keep their tokens in encrypted form; use
     * [getToken] to obtain a decrypted token for a specific TV.
     */
    suspend fun listTvs(): List<KnownTv> = dao.getAll()
}
