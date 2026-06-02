package com.factory.samsungremote.data.crypto

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * [TokenCipher] backed by an AES-256-GCM key stored in the Android Keystore.
 *
 * Rationale (security): the AES key is generated *inside* the Keystore
 * ("AndroidKeyStore" provider) under a fixed alias and never leaves it — the
 * app only ever references the key by alias, so there is no key material in the
 * source, resources or shared preferences (acceptance criterion: "nenhuma chave
 * em hardcode"). This is the same hardware-backed primitive that Jetpack
 * Security's `MasterKey`/`EncryptedFile` rely on; we use it directly here
 * because we need to encrypt a single short string in/out rather than a whole
 * file or preferences store.
 *
 * Wire format of the value returned by [encrypt] (and expected by [decrypt]):
 * ```
 * Base64( IV[12 bytes] || GCM-ciphertext-with-tag )
 * ```
 * A fresh random 12-byte IV is generated per [encrypt] call (GCM requires a
 * unique IV per encryption under the same key) and prepended to the ciphertext
 * so [decrypt] is self-contained.
 */
class KeystoreTokenCipher(
    private val keyAlias: String = DEFAULT_KEY_ALIAS,
) : TokenCipher {

    override fun encrypt(plaintext: String): String {
        try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())

            val iv = cipher.iv
            val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))

            val combined = ByteArray(iv.size + ciphertext.size)
            System.arraycopy(iv, 0, combined, 0, iv.size)
            System.arraycopy(ciphertext, 0, combined, iv.size, ciphertext.size)

            return Base64.getEncoder().encodeToString(combined)
        } catch (e: Exception) {
            throw TokenCipherException("Failed to encrypt token", e)
        }
    }

    override fun decrypt(ciphertext: String): String {
        try {
            val combined = Base64.getDecoder().decode(ciphertext)
            require(combined.size > IV_LENGTH_BYTES) { "Ciphertext too short" }

            val iv = combined.copyOfRange(0, IV_LENGTH_BYTES)
            val payload = combined.copyOfRange(IV_LENGTH_BYTES, combined.size)

            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateKey(),
                GCMParameterSpec(GCM_TAG_LENGTH_BITS, iv),
            )

            return String(cipher.doFinal(payload), Charsets.UTF_8)
        } catch (e: TokenCipherException) {
            throw e
        } catch (e: Exception) {
            throw TokenCipherException("Failed to decrypt token", e)
        }
    }

    /**
     * Returns the Keystore-resident AES key for [keyAlias], generating it on
     * first use. The generated key is non-exportable and bound to AES/GCM with
     * no padding, matching [TRANSFORMATION].
     */
    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

        (keyStore.getEntry(keyAlias, null) as? KeyStore.SecretKeyEntry)
            ?.let { return it.secretKey }

        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            ANDROID_KEYSTORE,
        )
        val spec = KeyGenParameterSpec.Builder(
            keyAlias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(KEY_SIZE_BITS)
            .setRandomizedEncryptionRequired(true)
            .build()
        keyGenerator.init(spec, SecureRandom())
        return keyGenerator.generateKey()
    }

    companion object {
        /** Default Keystore alias under which the token key is stored. */
        const val DEFAULT_KEY_ALIAS = "samsung_remote_token_key"

        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"

        private const val KEY_SIZE_BITS = 256
        private const val GCM_TAG_LENGTH_BITS = 128

        /** AES-GCM standard nonce length used by the Keystore provider. */
        private const val IV_LENGTH_BYTES = 12
    }
}
