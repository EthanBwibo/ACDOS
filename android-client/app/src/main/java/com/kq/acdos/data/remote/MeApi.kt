package com.kq.acdos.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import java.time.Instant
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * The signed-in driver's and crew member's own data (#52). The role comes
 * from the token: the wrong role gets 403, a missing or bad token 401.
 */
interface MeApi {
    /** The driver's van, for the Profile screen (#231). */
    @GET("drivers/me")
    suspend fun driverMe(): Response<DriverMeDto>

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

    /** The crew member's role and home zone, for the Profile screen (#231). */
    @GET("crew/me")
    suspend fun crewMe(): Response<CrewMeDto>

    /** Safe to retry: a notice already acknowledged keeps its first time (#53). */
    @POST("crew/me/notices/{notice_id}/acknowledge")
    suspend fun acknowledgeNotice(
        @Path("notice_id") noticeId: String
    ): Response<NoticeAcknowledgedDto>

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
    val lon: Double,
    /** What the server has recorded, from any phone (#196). */
    @Json(name = "pickup_status") val pickupStatus: PickupRequestStatusDto,
    /**
     * +2547XXXXXXXX, only from 30 minutes before [scheduledPickup] until the pickup is
     * settled (#255); the server leaves it out otherwise. Never stored on the phone.
     */
    @Json(name = "crew_phone") val crewPhone: String? = null
)

@JsonClass(generateAdapter = true)
data class DriverRouteDto(
    @Json(name = "route_id") val routeId: String,
    val status: RouteStatusDto,
    @Json(name = "vehicle_plate") val vehiclePlate: String,
    @Json(name = "planned_arrival") val plannedArrival: Instant,
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
    @Json(name = "vehicle_plate") val vehiclePlate: String?,
    /** True while a re-plan's change to this pickup is not acknowledged (#53). */
    @Json(name = "needs_ack") val needsAck: Boolean,
    /** The latest unacknowledged change; null when there is none. */
    val notice: ScheduleChangeNoticeDto?,
    /** Set once a route plans the pickup, like [vehiclePlate] (#255). */
    @Json(name = "driver_first_name") val driverFirstName: String? = null,
    /**
     * +2547XXXXXXXX, only from 30 minutes before [scheduledPickup] until the pickup is
     * settled (#255); the server leaves it out otherwise. Never stored on the phone.
     */
    @Json(name = "driver_phone") val driverPhone: String? = null
)

/** A re-plan changed the pickup (#53). [newPickupTime] is null when it was left unassigned. */
@JsonClass(generateAdapter = true)
data class ScheduleChangeNoticeDto(
    val id: String,
    val reason: OptimizationTriggerTypeDto,
    @Json(name = "previous_pickup_time") val previousPickupTime: Instant,
    @Json(name = "new_pickup_time") val newPickupTime: Instant?,
    @Json(name = "issued_at") val issuedAt: Instant
)

@JsonClass(generateAdapter = true)
data class NoticeAcknowledgedDto(
    val id: String,
    @Json(name = "acknowledged_at") val acknowledgedAt: Instant
)

/** [pickup] is null when nothing is coming up. */
@JsonClass(generateAdapter = true)
data class CrewPickupResponseDto(val pickup: CrewPickupDto?)

/** Both null for a crew account not yet linked to a crew record. */
@JsonClass(generateAdapter = true)
data class CrewMeDto(
    /** As the roster has it, e.g. cabin_crew. */
    @Json(name = "crew_role") val crewRole: String?,
    /** The pickup zone nearest the home location. Crew get no coordinates. */
    @Json(name = "home_zone") val homeZone: String?
)

@JsonClass(generateAdapter = true)
data class DriverVehicleDto(
    @Json(name = "plate_number") val plateNumber: String,
    /** Seats. */
    val capacity: Int,
    val status: VehicleStatusDto
)

/** [vehicle] is null when no van is assigned to the driver. */
@JsonClass(generateAdapter = true)
data class DriverMeDto(val vehicle: DriverVehicleDto?)

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
