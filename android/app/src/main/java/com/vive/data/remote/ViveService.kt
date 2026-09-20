package com.vive.data.remote

import com.vive.data.remote.dto.AlertDto
import com.vive.data.remote.dto.CreateSessionRequestDto
import com.vive.data.remote.dto.CreateSessionResponseDto
import com.vive.data.remote.dto.ModelInfoDto
import com.vive.data.remote.dto.PacketDto
import com.vive.data.remote.dto.ReadyDto
import com.vive.data.remote.dto.SessionDto
import com.vive.data.remote.dto.TranscriptLineDto
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit description of the backend REST surface (docs/API_SPEC.md 3, 5).
 *
 * Returns `Response<T>` rather than bare bodies so the caller can map HTTP
 * status and the structured error envelope onto typed [com.vive.core.ViveError]
 * values instead of catching exceptions.
 */
interface ViveService {

    @GET("api/v1/ready")
    suspend fun ready(): Response<ReadyDto>

    @POST("api/v1/sessions")
    suspend fun createSession(@Body body: CreateSessionRequestDto): Response<CreateSessionResponseDto>

    @GET("api/v1/sessions")
    suspend fun listSessions(
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0,
    ): Response<List<SessionDto>>

    @GET("api/v1/sessions/{id}")
    suspend fun getSession(@Path("id") sessionId: String): Response<SessionDto>

    @POST("api/v1/sessions/{id}/end")
    suspend fun endSession(@Path("id") sessionId: String): Response<SessionDto>

    @GET("api/v1/sessions/{id}/packets")
    suspend fun listPackets(
        @Path("id") sessionId: String,
        @Query("since_seq") sinceSeq: Int? = null,
        @Query("limit") limit: Int = 200,
    ): Response<List<PacketDto>>

    @GET("api/v1/sessions/{id}/packets/{packetId}")
    suspend fun getPacket(
        @Path("id") sessionId: String,
        @Path("packetId") packetId: String,
    ): Response<PacketDto>

    @GET("api/v1/sessions/{id}/transcript")
    suspend fun getTranscript(@Path("id") sessionId: String): Response<List<TranscriptLineDto>>

    @DELETE("api/v1/sessions/{id}")
    suspend fun deleteSession(@Path("id") sessionId: String): Response<Unit>

    @GET("api/v1/alerts")
    suspend fun listAlerts(@Query("session_id") sessionId: String? = null): Response<List<AlertDto>>

    @POST("api/v1/alerts/{id}/ack")
    suspend fun acknowledgeAlert(@Path("id") alertId: String): Response<AlertDto>

    @GET("api/v1/models")
    suspend fun listModels(): Response<List<ModelInfoDto>>
}
