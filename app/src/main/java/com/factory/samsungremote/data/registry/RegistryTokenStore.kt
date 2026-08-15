package com.factory.samsungremote.data.registry

import com.factory.samsungremote.data.db.KnownTv
import com.factory.samsungremote.network.discovery.DiscoveredTv
import com.factory.samsungremote.network.session.TokenStore
import javax.inject.Inject
import javax.inject.Singleton

/**
 * [TokenStore] backed by the [TvRegistry], so tokens the live session receives
 * land in the same encrypted store the pairing handshake writes to.
 *
 * Writing goes through [TvRegistry.saveToken] first: it updates only the token
 * column of an existing row, preserving the fields the session does not know
 * about (notably [KnownTv.macAddress], which Wake-on-LAN depends on). Only when
 * no row exists yet — a TV whose token arrived before it was ever registered —
 * does it fall back to inserting a fresh record.
 */
@Singleton
class RegistryTokenStore @Inject constructor(
    private val registry: TvRegistry,
) : TokenStore {

    override suspend fun save(tv: DiscoveredTv, token: String) {
        if (registry.saveToken(tv.id, token)) return
        registry.saveTv(
            KnownTv(id = tv.id, name = tv.name, ipAddress = tv.ipAddress),
            token = token,
        )
    }

    override suspend fun clear(tvId: String) = registry.clearToken(tvId)
}
