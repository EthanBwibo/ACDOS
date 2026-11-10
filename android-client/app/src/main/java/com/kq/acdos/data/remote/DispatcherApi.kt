package com.kq.acdos.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import java.time.Instant
import java.time.LocalDate
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * The dispatcher's day board and the two disruptions (#137). Dispatchers
 * only: anyone else gets 403 (ErrorCode.FORBIDDEN). Neither PATCH re-plans;
 * the dispatcher starts that with [OptimisationJobsApi.createJob].
 *
 * Lists are pages: [cursor] is the previous page's next_cursor, null for the
 * first; [limit] is at most 50. [date] is a Nairobi day, null for today.
 */
interface DispatcherApi {
    /** The pickups reporting on [date], in report-time order. */
    @GET("pickup-requests")
    suspend fun pickups(
        @Query("date") date: LocalDate? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null
    ): Response<DispatcherPickupPageDto>

    @GET("vehicles")
    suspend fun vehicles(
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null
    ): Response<DispatcherVehiclePageDto>

    /** The active routes leaving the depot on [date], with their live stops. */
    @GET("routes")
    suspend fun routes(
        @Query("date") date: LocalDate? = null,
        @Query("cursor") cursor: String? = null,
        @Query("limit") limit: Int? = null
    ): Response<DispatcherRoutePageDto>

    /** A flight delay: the crew member's new report time at JKIA. */
    @PATCH("pickup-requests/{pickup_id}")
    suspend fun setReportTime(
        @Path("pickup_id") pickupId: String,
        @Body update: PickupReportTimeUpdateDto
    ): Response<DispatcherPickupDto>

    /** A breakdown, or the van back in service. */
    @PATCH("vehicles/{vehicle_id}")
    suspend fun setVehicleStatus(
        @Path("vehicle_id") vehicleId: String,
        @Body update: VehicleStatusUpdateDto
    ): Response<DispatcherVehicleDto>
}

// DTOs match docs/openapi.json (OpenApiContractTest checks it). Ids stay strings.

enum class VehicleStatusDto {
    @Json(name = "available")
    AVAILABLE,

    @Json(name = "in_service")
    IN_SERVICE,

    @Json(name = "broken_down")
    BROKEN_DOWN,

    /** Out of planning but not broken down, e.g. the test vans during the demo (#198). */
    @Json(name = "unavailable")
    UNAVAILABLE
}

@JsonClass(generateAdapter = true)
data class DispatcherPickupDto(
    val id: String,
    @Json(name = "crew_name") val crewName: String,
    @Json(name = "zone_label") val zoneLabel: String?,
    val lat: Double,
    val lon: Double,
    @Json(name = "report_time") val reportTime: Instant,
    val status: PickupRequestStatusDto,
    /** True while a schedule-change notice is not acknowledged by the crew (#53). */
    @Json(name = "needs_ack") val needsAck: Boolean,
    /** When the latest notice was acknowledged; null with none, or while it is pending. */
    @Json(name = "acknowledged_at") val acknowledgedAt: Instant?
)

@JsonClass(generateAdapter = true)
data class DispatcherPickupPageDto(
    val items: List<DispatcherPickupDto>,
    @Json(name = "next_cursor") val nextCursor: String?
)

@JsonClass(generateAdapter = true)
data class DispatcherVehicleDto(
    val id: String,
    @Json(name = "plate_number") val plateNumber: String,
    val capacity: Int,
    val status: VehicleStatusDto,
    /** Its route has left the depot: a job that includes it gets 409. */
    @Json(name = "on_the_road") val onTheRoad: Boolean
)

@JsonClass(generateAdapter = true)
data class DispatcherVehiclePageDto(
    val items: List<DispatcherVehicleDto>,
    @Json(name = "next_cursor") val nextCursor: String?
)

/** The stops are [PlannedNodeDto]s: pickup ids, named from the day's pickup list. */
@JsonClass(generateAdapter = true)
data class DispatcherRouteDto(
    @Json(name = "route_id") val routeId: String,
    @Json(name = "vehicle_id") val vehicleId: String,
    @Json(name = "vehicle_plate") val vehiclePlate: String,
    @Json(name = "total_distance_km") val totalDistanceKm: Double,
    @Json(name = "planned_departure") val plannedDeparture: Instant,
    @Json(name = "planned_arrival") val plannedArrival: Instant,
    val nodes: List<PlannedNodeDto>
)

@JsonClass(generateAdapter = true)
data class DispatcherRoutePageDto(
    val items: List<DispatcherRouteDto>,
    @Json(name = "next_cursor") val nextCursor: String?
)

@JsonClass(generateAdapter = true)
data class PickupReportTimeUpdateDto(@Json(name = "report_time") val reportTime: Instant)

@JsonClass(generateAdapter = true)
data class VehicleStatusUpdateDto(val status: VehicleStatusDto)
