package com.kq.acdos.data

import com.kq.acdos.data.remote.CrewPickupResponseDto
import com.kq.acdos.data.remote.DriverRouteResponseDto
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.PickupEventBatchDto
import com.kq.acdos.data.remote.PickupEventResultsDto
import com.kq.acdos.data.remote.RouteSummaryPageDto
import retrofit2.Response

/** Answers driverRoute() with [next] and crewPickup() with [nextCrew]; counts the calls. */
class FakeMeApi : MeApi {
    var calls = 0
    var next: suspend () -> Response<DriverRouteResponseDto> = { error("no answer set") }

    override suspend fun driverRoute(): Response<DriverRouteResponseDto> {
        calls++
        return next()
    }

    override suspend fun driverRoutes(cursor: String?, limit: Int?): Response<RouteSummaryPageDto> =
        error("not used")

    var nextCrew: suspend () -> Response<CrewPickupResponseDto> = { error("no answer set") }

    override suspend fun crewPickup(): Response<CrewPickupResponseDto> {
        calls++
        return nextCrew()
    }

    override suspend fun uploadPickupEvents(
        batch: PickupEventBatchDto
    ): Response<PickupEventResultsDto> = error("not used")
}
