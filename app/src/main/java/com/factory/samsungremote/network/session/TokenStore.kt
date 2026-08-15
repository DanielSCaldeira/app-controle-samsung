package com.factory.samsungremote.network.session

import com.factory.samsungremote.network.discovery.DiscoveredTv

/**
 * Sink for the authorization token a Samsung TV issues **while a session is
 * live**, not only during the explicit pairing handshake.
 *
 * Tizen firmware re-emits `data.token` on the `ms.channel.connect` event of a
 * control connection, and that value is not always the one the client replayed:
 * several firmwares rotate the token when the client reconnects. Before this
 * seam existed only
 * [com.factory.samsungremote.network.pairing.PairingManager] persisted tokens,
 * so a rotation received on the session socket was dropped — the next launch
 * replayed a token the TV no longer recognised and the set showed its
 * "allow this device?" prompt again, every single time.
 *
 * The session therefore writes every token it sees through this interface, and
 * clears the stored one when the TV explicitly answers `ms.channel.unauthorized`
 * (the token is dead; a full handshake is needed next time).
 *
 * Implemented by [com.factory.samsungremote.data.registry.RegistryTokenStore],
 * which encrypts before touching the database. Kept as an interface here so the
 * session layer stays free of persistence/crypto details and unit tests can pass
 * a recording fake (or nothing at all — the session tolerates a `null` store).
 */
interface TokenStore {

    /** Persists [token] (encrypted) as the current authorization token of [tv]. */
    suspend fun save(tv: DiscoveredTv, token: String)

    /** Drops the stored token of the TV identified by [tvId]. */
    suspend fun clear(tvId: String)
}
