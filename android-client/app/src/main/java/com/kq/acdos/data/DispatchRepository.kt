package com.kq.acdos.data

import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.DispatcherApi
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.OptimisationJobAcceptedDto
import com.kq.acdos.data.remote.OptimisationJobCreateDto
import com.kq.acdos.data.remote.OptimisationJobResultDto
import com.kq.acdos.data.remote.OptimisationJobsApi
import com.kq.acdos.data.remote.OptimizationTriggerTypeDto
import com.kq.acdos.data.remote.PickupReportTimeUpdateDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.VehicleStatusDto
import com.kq.acdos.data.remote.VehicleStatusUpdateDto
import com.kq.acdos.data.remote.apiCall
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import retrofit2.Response

/** One Nairobi day as the dispatcher sees it: who reports, the vans, and the plan. */
data class DayBoard(
    val pickups: List<DispatcherPickupDto>,
    val vehicles: List<DispatcherVehicleDto>,
    val routes: List<DispatcherRouteDto>
) {
    /** Route stops carry only pickup ids; their names come from the day's pickups. */
    val crewNames: Map<String, String> get() = pickups.associate { it.id to it.crewName }
}

/** The vans a job may use: not broken down, and not out on a route that has left. */
fun plannableVans(board: DayBoard): List<String> = board.vehicles
    .filter { it.status != VehicleStatusDto.BROKEN_DOWN && !it.onTheRoad }
    .map { it.id }

/** A first plan: the day's pickups not on a route yet. */
fun unplannedPickups(board: DayBoard): List<String> = board.pickups
    .filter { it.status == PickupRequestStatusDto.PENDING }
    .map { it.id }

/**
 * After a breakdown: the pickups on [vehicleId]'s routes that nobody has
 * collected yet. Crew already on board stay where they are (#135).
 */
fun strandedPickups(board: DayBoard, vehicleId: String): List<String> {
    val onVan = board.routes
        .filter { it.vehicleId == vehicleId }
        .flatMap { route -> route.nodes.map { it.pickupRequestId } }
        .toSet()
    return board.pickups.filter { it.id in onVan && it.status in REPLANNABLE }.map { it.id }
}

internal val REPLANNABLE = setOf(PickupRequestStatusDto.PENDING, PickupRequestStatusDto.ASSIGNED)

/** The dispatcher's calls (#137, #51). Online only: nothing is cached. */
class DispatchRepository(
    private val api: DispatcherApi,
    private val jobs: OptimisationJobsApi,
    private val newKey: () -> String = { UUID.randomUUID().toString() }
) {
    /** Every page of the day's pickups, the vans and the day's routes. */
    suspend fun loadDay(date: LocalDate): ApiResult<DayBoard> {
        val pickups = allPages({ api.pickups(date, it, PAGE) }, { it.items }, { it.nextCursor })
            .orReturn { return it }
        val vehicles = allPages({ api.vehicles(it, PAGE) }, { it.items }, { it.nextCursor })
            .orReturn { return it }
        val routes = allPages({ api.routes(date, it, PAGE) }, { it.items }, { it.nextCursor })
            .orReturn { return it }
        return ApiResult.Success(DayBoard(pickups, vehicles, routes))
    }

    /** A flight delay. It doesn't re-plan: the dispatcher does that next. */
    suspend fun delayFlight(pickupId: String, reportTime: Instant): ApiResult<DispatcherPickupDto> =
        apiCall { api.setReportTime(pickupId, PickupReportTimeUpdateDto(reportTime)) }

    /** A breakdown, or a van back in service. It doesn't re-plan either. */
    suspend fun setVehicleStatus(
        vehicleId: String,
        status: VehicleStatusDto
    ): ApiResult<DispatcherVehicleDto> =
        apiCall { api.setVehicleStatus(vehicleId, VehicleStatusUpdateDto(status)) }

    /** A new key per call: each tap is a new job. */
    suspend fun startJob(
        trigger: OptimizationTriggerTypeDto,
        pickupIds: List<String>,
        vehicleIds: List<String>
    ): ApiResult<OptimisationJobAcceptedDto> = apiCall {
        jobs.createJob(newKey(), OptimisationJobCreateDto(trigger, pickupIds, vehicleIds))
    }

    suspend fun job(jobId: String): ApiResult<OptimisationJobResultDto> =
        apiCall { jobs.getJob(jobId) }

    /** Follows next_cursor until the last page. */
    private suspend fun <P : Any, T> allPages(
        page: suspend (cursor: String?) -> Response<P>,
        items: (P) -> List<T>,
        next: (P) -> String?
    ): ApiResult<List<T>> {
        val all = mutableListOf<T>()
        var cursor: String? = null
        do {
            val body = apiCall { page(cursor) }.orReturn { return it }
            all += items(body)
            cursor = next(body)
        } while (cursor != null)
        return ApiResult.Success(all)
    }

    private companion object {
        /** The server's largest page. */
        const val PAGE = 50
    }
}

/** The body, or hands the failure to [fail], which returns from the caller. */
private inline fun <T> ApiResult<T>.orReturn(fail: (ApiResult<Nothing>) -> Nothing): T =
    when (this) {
        is ApiResult.Success -> body
        is ApiResult.Error -> fail(this)
        is ApiResult.NetworkError -> fail(this)
    }
