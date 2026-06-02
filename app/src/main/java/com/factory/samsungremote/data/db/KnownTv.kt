package com.factory.samsungremote.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Persisted record of a Samsung Smart TV that the user has discovered and/or
 * paired with, so it can be reconnected to without re-running discovery.
 *
 * @property id              Stable identifier of the TV (e.g. the device UUID
 *                           reported during discovery). Primary key.
 * @property name            Human-readable TV name for UI display.
 * @property ipAddress       Last known IPv4/IPv6 address of the TV on the LAN.
 * @property macAddress      Optional hardware MAC address, used for Wake-on-LAN.
 *                           `null` when it could not be resolved.
 * @property tokenEncrypted  Optional encrypted pairing token returned by the TV.
 *                           Stored already-encrypted; `null` until paired.
 * @property lastConnectedAt Epoch millis of the last successful connection, or
 *                           `null` if the TV has never been connected to.
 */
@Entity(tableName = "known_tv")
data class KnownTv(
    @PrimaryKey
    @ColumnInfo(name = "id")
    val id: String,
    @ColumnInfo(name = "name")
    val name: String,
    @ColumnInfo(name = "ip_address")
    val ipAddress: String,
    @ColumnInfo(name = "mac_address")
    val macAddress: String? = null,
    @ColumnInfo(name = "token_encrypted")
    val tokenEncrypted: String? = null,
    @ColumnInfo(name = "last_connected_at")
    val lastConnectedAt: Long? = null,
)
