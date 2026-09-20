package com.vive.data.remote

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import com.vive.core.ViveError
import com.vive.core.ViveResult
import com.vive.data.remote.dto.ErrorResponseDto
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Response
import retrofit2.Retrofit
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Network stack construction and the HTTP-to-[ViveError] mapping.
 *
 * `ignoreUnknownKeys` is deliberate: the backend may add fields, and an older
 * client must keep parsing (docs/API_SPEC.md 4.1 says extensions are additive).
 */
object NetworkModule {

    val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
        coerceInputValues = true
    }

    fun okHttp(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        // Keeps the WebSocket alive through NAT/idle timeouts; the server also
        // emits its own heartbeat frames.
        .pingInterval(20, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    fun service(baseUrl: String, client: OkHttpClient = okHttp()): ViveService =
        Retrofit.Builder()
            .baseUrl(if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/")
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(ViveService::class.java)
}

/**
 * Runs a Retrofit call and maps failure onto a typed result.
 *
 * Nothing throws past this boundary: repositories return [ViveResult] so the UI
 * can never crash on a transport error (docs/UI_SPEC.md 8).
 */
suspend fun <T> apiCall(block: suspend () -> Response<T>): ViveResult<T> = try {
    val response = block()
    val body = response.body()
    when {
        response.isSuccessful && body != null -> ViveResult.Success(body)
        response.isSuccessful -> @Suppress("UNCHECKED_CAST")
        ViveResult.Success(Unit as T)
        else -> ViveResult.Failure(response.toViveError())
    }
} catch (e: IOException) {
    // No connectivity, DNS failure, refused connection: recoverable.
    ViveResult.Failure(ViveError.Offline(cause = e))
} catch (e: Exception) {
    ViveResult.Failure(ViveError.Unexpected(cause = e))
}

private fun <T> Response<T>.toViveError(): ViveError {
    val parsed = runCatching {
        errorBody()?.string()?.let { NetworkModule.json.decodeFromString<ErrorResponseDto>(it) }
    }.getOrNull()

    val message = parsed?.error?.message ?: "Request failed"
    return when (parsed?.error?.code ?: code().toString()) {
        "UNAUTHENTICATED", "401" -> ViveError.Unauthenticated(message)
        "FORBIDDEN", "403" -> ViveError.Unauthenticated(message)
        "SESSION_NOT_FOUND", "PACKET_NOT_FOUND", "404" -> ViveError.NotFound(message)
        "VALIDATION_ERROR", "400" -> ViveError.Validation(message)
        "ADAPTER_UNAVAILABLE", "503" -> ViveError.AdapterUnavailable("backend", message)
        else -> ViveError.Unexpected(message)
    }
}
