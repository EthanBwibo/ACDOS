package com.kq.acdos.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import java.time.Instant
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Crew-to-dispatcher messages (#147, #57): crew send a preset, never free
 * text, and the dispatcher reads them. Crew list only their own messages; the
 * dispatcher lists everyone's.
 */
interface MessagesApi {
    /** The presets crew may send. A fixed set, so not paginated. */
    @GET("preset-messages")
    suspend fun presets(): Response<PresetMessageListDto>

    /** Safe to retry with the same [idempotencyKey]: the retry gets the message already sent. */
    @POST("messages")
    suspend fun send(
        @Header("Idempotency-Key") idempotencyKey: String,
        @Body body: CrewMessageCreateDto
    ): Response<CrewMessageDto>

    /** Newest first. [cursor] is the previous page's next_cursor; [limit] is at most 50. */
    @GET("messages")
    suspend fun messages(
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null
    ): Response<CrewMessagePageDto>

    /** The dispatcher has read a message. Safe to retry. */
    @POST("messages/{message_id}/ack")
    suspend fun markRead(@Path("message_id") messageId: String): Response<CrewMessageReadDto>

    /** The dispatcher's preset reply; it also marks the message read. Safe to retry. */
    @POST("messages/{message_id}/replies")
    suspend fun reply(
        @Path("message_id") messageId: String,
        @Header("Idempotency-Key") idempotencyKey: String,
        @Body body: MessageReplyCreateDto
    ): Response<MessageReplyDto>
}

// DTOs match docs/openapi.json (OpenApiContractTest checks it). Ids stay strings.

@JsonClass(generateAdapter = true)
data class CrewMessageReadDto(val id: String, @Json(name = "read_at") val readAt: Instant)

@JsonClass(generateAdapter = true)
data class PresetMessageDto(val code: String, val label: String)

@JsonClass(generateAdapter = true)
data class PresetMessageListDto(val items: List<PresetMessageDto>)

@JsonClass(generateAdapter = true)
data class CrewMessageCreateDto(@Json(name = "preset_code") val presetCode: String)

@JsonClass(generateAdapter = true)
data class CrewMessageDto(
    val id: String,
    @Json(name = "crew_member_id") val crewMemberId: String,
    @Json(name = "crew_name") val crewName: String,
    @Json(name = "preset_code") val presetCode: String,
    val label: String,
    @Json(name = "sent_at") val sentAt: Instant,
    /** Null until the dispatcher has read it. */
    @Json(name = "read_at") val readAt: Instant?,
    /** The dispatcher's preset replies, oldest first. */
    val replies: List<MessageReplyDto>
)

@JsonClass(generateAdapter = true)
data class MessageReplyCreateDto(@Json(name = "preset_code") val presetCode: String)

@JsonClass(generateAdapter = true)
data class MessageReplyDto(
    val id: String,
    @Json(name = "preset_code") val presetCode: String,
    val label: String,
    @Json(name = "sent_at") val sentAt: Instant
)

@JsonClass(generateAdapter = true)
data class CrewMessagePageDto(
    val items: List<CrewMessageDto>,
    @Json(name = "next_cursor") val nextCursor: String?
)
