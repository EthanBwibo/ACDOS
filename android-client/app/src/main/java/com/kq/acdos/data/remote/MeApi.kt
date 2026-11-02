package com.kq.acdos.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import java.time.Instant
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Query

/**
 * The signed-in driver's and crew member's own data (#52). The role comes
 * from the token: the wrong role gets 403, a missing or bad token 401.
 */
interface MeApi {
    @GET("drivers/me/route")
    suspend fun driverRoute(): Response<DriverRouteResponseDto>

    /** [cursor] is the previous page's next_cursor; null for the first page. */
    @GET("drivers/me/routes")
    suspend fun driverRoutes(
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null
    ): Response<RouteSummaryPageDto>

    @GET("crew/me/pickup")
    suspend fun crewPickup(): Response<CrewPickupResponseDto>

    /** The outbox's pickup events (#29), 1 to 50 per call; one result per event. */
    @POST("drivers/me/pickup-events")
    suspend fun uploadPickupEvents(
        @Body batch: PickupEventBatchDto
    ): Response<PickupEventResultsDto>
}

// DTOs match docs/openapi.json (OpenApiContractTest checks it). Ids stay strings.

enum class RouteStatusDto {
    @Json(name = "active")
    ACTIVE,

    @Json(name = "completed")
    COMPLETED,

    @Json(name = "superseded")
    SUPERSEDED
}

enum class PickupRequestStatusDto {
    @Json(name = "pending")
    PENDING,

    @Json(name = "assigned")
    ASSIGNED,

    @Json(name = "picked_up")
    PICKED_UP,

    @Json(name = "missed")
    MISSED,

    @Json(name = "cancelled")
    CANCELLED
}

@JsonClass(generateAdapter = true)
data class DriverStopDto(
    /** What a pickup confirmation (#29) refers to. */
    @Json(name = "route_node_id") val routeNodeId: String,
    @Json(name = "seq_order") val seqOrder: Int,
    @Json(name = "crew_name") val crewName: String,
    @Json(name = "zone_label") val zoneLabel: String?,
    @Json(name = "scheduled_pickup") val scheduledPickup: Instant,
    /** Always null until live tracking (#52). */
    val eta: Instant? = null,
    /** Rounded to 5 decimal places. Drivers only: crew get no coordinates. */
    val lat: Double,
    val lon: Double
)

@JsonClass(generateAdapter = true)
data class DriverRouteDto(
    @Json(name = "route_id") val routeId: String,
    val status: RouteStatusDto,
    @Json(name = "vehicle_plate") val vehiclePlate: String,
    val stops: List<DriverStopDto>
)

/** [route] is null when the driver has no active route. */
@JsonClass(generateAdapter = true)
data class DriverRouteResponseDto(val route: DriverRouteDto?)

@JsonClass(generateAdapter = true)
data class RouteSummaryDto(
    @Json(name = "route_id") val routeId: String,
    val status: RouteStatusDto,
    @Json(name = "vehicle_plate") val vehiclePlate: String,
    @Json(name = "first_pickup") val firstPickup: Instant,
    @Json(name = "stop_count") val stopCount: Int,
    @Json(name = "total_distance_km") val totalDistanceKm: Double
)

/** [nextCursor] is null on the last page. */
@JsonClass(generateAdapter = true)
data class RouteSummaryPageDto(
    val items: List<RouteSummaryDto>,
    @Json(name = "next_cursor") val nextCursor: String?
)

@JsonClass(generateAdapter = true)
data class CrewPickupDto(
    @Json(name = "pickup_request_id") val pickupRequestId: String,
    val status: PickupRequestStatusDto,
    /** The deadline at JKIA. */
    @Json(name = "report_time") val reportTime: Instant,
    /** Null until a route plans the pickup, like [vehiclePlate]. */
    @Json(name = "scheduled_pickup") val scheduledPickup: Instant?,
    val eta: Instant? = null,
    @Json(name = "vehicle_plate") val vehiclePlate: String?
)

/** [pickup] is null when nothing is coming up. needs_ack arrives with #53. */
@JsonClass(generateAdapter = true)
data class CrewPickupResponseDto(val pickup: CrewPickupDto?)

enum class PickupEventTypeDto {
    @Json(name = "pickup_confirmed")
    PICKUP_CONFIRMED,

    @Json(name = "exception")
    EXCEPTION
}

enum class PickupExceptionTypeDto {
    @Json(name = "no_show")
    NO_SHOW,

    @Json(name = "vehicle_issue")
    VEHICLE_ISSUE,

    @Json(name = "traffic_delay")
    TRAFFIC_DELAY
}

enum class PickupEventOutcomeDto {
    @Json(name = "accepted")
    ACCEPTED,

    /** The key was already stored: an earlier upload got through. */
    @Json(name = "duplicate")
    DUPLICATE,

    /** Final: retrying can't fix it. */
    @Json(name = "rejected")
    REJECTED
}

@JsonClass(generateAdapter = true)
data class PickupEventInDto(
    @Json(name = "idempotency_key") val idempotencyKey: String,
    @Json(name = "route_node_id") val routeNodeId: String,
    /** As stored with the event, not whoever is signed in now. */
    @Json(name = "driver_id") val driverId: String,
    @Json(name = "event_type") val eventType: PickupEventTypeDto,
    @Json(name = "exception_type") val exceptionType: PickupExceptionTypeDto? = null,
    /** When the driver tapped, from the device clock. */
    @Json(name = "occurred_at") val occurredAt: Instant
)

@JsonClass(generateAdapter = true)
data class PickupEventBatchDto(val events: List<PickupEventInDto>)

/**
 * One event's outcome. The optional fields are left out, never null, when
 * they don't apply, hence the defaults.
 */
@JsonClass(generateAdapter = true)
data class PickupEventResultDto(
    @Json(name = "idempotency_key") val idempotencyKey: String,
    val status: PickupEventOutcomeDto,
    @Json(name = "event_id") val eventId: String = "",
    /** The stop was re-planned after the event; not shown yet (#135). */
    @Json(name = "stop_replanned") val stopReplanned: Boolean = false,
    /** Only for [PickupEventOutcomeDto.REJECTED]. */
    val code: ErrorCode = ErrorCode.UNKNOWN,
    val detail: String = ""
)

@JsonClass(generateAdapter = true)
data class PickupEventResultsDto(val results: List<PickupEventResultDto>)
