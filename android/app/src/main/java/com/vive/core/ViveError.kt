package com.vive.core

/**
 * Typed application errors.
 *
 * Mirrors the backend error contract (docs/API_SPEC.md 7) plus the client-side
 * conditions the UI must distinguish. Screens map these onto the state set in
 * docs/UI_SPEC.md 8 - notably [Offline] is recoverable and distinct from a
 * general failure, and [AdapterUnavailable] is expected while adapters load
 * rather than fatal.
 */
sealed class ViveError(
    open val message: String,
    open val cause: Throwable? = null,
) {
    /** No connectivity, or the stream dropped. Recoverable; show cached data. */
    data class Offline(
        override val message: String = "No connection",
        override val cause: Throwable? = null,
    ) : ViveError(message, cause)

    /** Request rejected for lack of valid credentials. */
    data class Unauthenticated(
        override val message: String = "Sign in required",
    ) : ViveError(message)

    /** Requested session, packet or alert does not exist or is not ours. */
    data class NotFound(
        override val message: String = "Not found",
    ) : ViveError(message)

    /** Backend reached but a model adapter is not loaded. Expected, not fatal. */
    data class AdapterUnavailable(
        val adapter: String,
        override val message: String = "Analysis unavailable",
    ) : ViveError(message)

    /** Request or payload rejected as invalid. */
    data class Validation(
        override val message: String,
    ) : ViveError(message)

    /** Anything else, including unexpected transport failures. */
    data class Unexpected(
        override val message: String = "Something went wrong",
        override val cause: Throwable? = null,
    ) : ViveError(message, cause)
}
