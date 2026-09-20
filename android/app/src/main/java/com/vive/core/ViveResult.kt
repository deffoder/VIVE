package com.vive.core

/**
 * Result of an operation that can fail in a typed way.
 *
 * Repositories return this rather than throwing, so callers are forced to
 * handle failure and the UI can never crash on a missing model output
 * (docs/UI_SPEC.md 8).
 */
sealed interface ViveResult<out T> {
    data class Success<out T>(val data: T) : ViveResult<T>
    data class Failure(val error: ViveError) : ViveResult<Nothing>
}

inline fun <T, R> ViveResult<T>.map(transform: (T) -> R): ViveResult<R> = when (this) {
    is ViveResult.Success -> ViveResult.Success(transform(data))
    is ViveResult.Failure -> this
}

inline fun <T> ViveResult<T>.onSuccess(action: (T) -> Unit): ViveResult<T> = apply {
    if (this is ViveResult.Success) action(data)
}

inline fun <T> ViveResult<T>.onFailure(action: (ViveError) -> Unit): ViveResult<T> = apply {
    if (this is ViveResult.Failure) action(error)
}

fun <T> ViveResult<T>.getOrNull(): T? = (this as? ViveResult.Success)?.data
