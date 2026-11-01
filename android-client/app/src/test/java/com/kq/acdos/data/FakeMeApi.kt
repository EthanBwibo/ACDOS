package com.kq.acdos.data

import com.kq.acdos.data.remote.CrewPickupResponseDto
import com.kq.acdos.data.remote.DriverRouteResponseDto
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.RouteSummaryPageDto
import retrofit2.Response

/** Answers driverRoute() with [next] and counts the calls. */
class FakeMeApi : MeApi {
    var calls = 0
    var next: suspend () -> Response<DriverRouteResponseDto> = { error("no answer set") }

    override suspend fun driverRoute(): Response<DriverRouteResponseDto> {
        calls++
        return next()
    }

    override suspend fun driverRoutes(
        cursor: String?,
        limit: Int?
    ): Response<RouteSummaryPageDto> = error("not used")

    override suspend fun crewPickup(): Response<CrewPickupResponseDto> = error("not used")
}
