package com.factory.samsungremote.network.pairing

/**
 * Why a pairing handshake failed, in terms the UI/ViewModel layer can act on.
 *
 * Pairing is a user-facing flow (the TV shows an on-screen "allow this device?"
 * prompt), so failures must be *treatable* rather than opaque: the caller needs
 * to tell "the user denied access" apart from "the TV was unreachable" to show
 * the right message and decide whether retrying makes sense.
 */
enum class PairingFailureReason {
    /** The TV explicitly rejected the device (user denied the on-screen prompt). */
    UNAUTHORIZED,

    /** The WebSocket could not be established or dropped before completing. */
    CONNECTION_FAILED,

    /** The handshake completed but the TV never delivered a `data.token`. */
    NO_TOKEN,
}

/**
 * Thrown by [PairingManager] when the handshake does not yield a usable token.
 *
 * It carries a coarse [reason] for branching in the UI while keeping the
 * underlying [cause] (e.g. the OkHttp [Throwable]) for logging/diagnostics.
 *
 * @property reason Coarse, user-actionable classification of the failure.
 */
class PairingException(
    val reason: PairingFailureReason,
    message: String,
    cause: Throwable? = null,
) : Exception(message, cause)
