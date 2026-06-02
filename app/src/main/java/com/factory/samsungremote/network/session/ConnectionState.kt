package com.factory.samsungremote.network.session

/**
 * Lifecycle state of the single [RemoteSession] WebSocket connection.
 *
 * The session is the single source of truth for connectivity (ADR-0003,
 * architecture §3.1): the UI observes this as a `StateFlow` and never reaches a
 * dead end — a dropped link transitions through [Reconnecting] back to
 * [Connected] automatically, and only an exhausted retry budget surfaces as a
 * terminal [Error].
 *
 * Transitions:
 * ```
 * Disconnected ──connect()──▶ Connecting ──socket open──▶ Connected
 *                                  │                          │
 *                                  │ failure              drop/close
 *                                  ▼                          ▼
 *                            Reconnecting(n) ◀──── backoff ───┘
 *                                  │
 *                       retries exhausted ──▶ Error
 *                                  │
 *                          disconnect() ──▶ Disconnected
 * ```
 */
sealed interface ConnectionState {

    /** No connection requested, or explicitly torn down via `disconnect()`. */
    data object Disconnected : ConnectionState

    /** First connection attempt in flight; the socket is not open yet. */
    data object Connecting : ConnectionState

    /** Socket is open; keys/messages can be sent and events are received. */
    data object Connected : ConnectionState

    /**
     * The link dropped and an automatic re-connection is in progress.
     *
     * @property attempt 1-based count of the current reconnection attempt; used
     *                   to drive the exponential backoff and for diagnostics.
     */
    data class Reconnecting(val attempt: Int) : ConnectionState

    /**
     * Terminal failure: the reconnection budget was exhausted without recovering.
     *
     * @property message Human-readable description of what went wrong.
     * @property cause   Underlying transport error, when available.
     */
    data class Error(val message: String, val cause: Throwable? = null) : ConnectionState
}
