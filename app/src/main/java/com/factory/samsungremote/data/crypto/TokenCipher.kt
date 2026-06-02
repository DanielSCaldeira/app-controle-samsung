package com.factory.samsungremote.data.crypto

/**
 * Symmetric cipher used to protect the Samsung TV pairing token before it is
 * persisted in [com.factory.samsungremote.data.db.KnownTv.tokenEncrypted].
 *
 * The token is sensitive: anyone holding it can control the paired TV. It must
 * therefore never be written to the database (or anywhere on disk) in clear
 * text. Implementations encrypt with a key that lives in the Android Keystore
 * (hardware-backed when available), so the raw key material never leaves the
 * secure container and is never embedded in the app — see
 * [KeystoreTokenCipher].
 *
 * The contract is round-trippable for any non-empty UTF-8 string:
 * `decrypt(encrypt(token)) == token`, while `encrypt(token) != token`.
 */
interface TokenCipher {

    /**
     * Encrypts [plaintext] and returns an opaque, persistable token string
     * (Base64 of the IV concatenated with the AES-GCM ciphertext).
     *
     * The output differs from [plaintext] and is non-deterministic: encrypting
     * the same input twice yields different ciphertexts because a fresh random
     * IV is used each time.
     *
     * @throws TokenCipherException if encryption fails (e.g. the Keystore is
     *         unavailable).
     */
    fun encrypt(plaintext: String): String

    /**
     * Reverses [encrypt], returning the original clear-text token.
     *
     * @param ciphertext a value previously produced by [encrypt].
     * @throws TokenCipherException if [ciphertext] is malformed or cannot be
     *         decrypted with the current Keystore key (e.g. tampered data).
     */
    fun decrypt(ciphertext: String): String
}

/** Raised when a [TokenCipher] operation fails. */
class TokenCipherException(message: String, cause: Throwable? = null) :
    Exception(message, cause)
