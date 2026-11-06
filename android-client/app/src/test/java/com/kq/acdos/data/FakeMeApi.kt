package com.kq.acdos.data

import com.kq.acdos.data.remote.CrewPickupResponseDto
import com.kq.acdos.data.remote.DriverRouteResponseDto
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.NoticeAcknowledgedDto
import com.kq.acdos.data.remote.PickupEventBatchDto
import com.kq.acdos.data.remote.PickupEventResultsDto
import com.kq.acdos.data.remote.RouteSummaryPageDto
import retrofit2.Response

/**
 * Answers driverRoute() with [next], crewPickup() with [nextCrew] and
 * acknowledgeNotice() with [nextAck]; counts the route and pickup calls.
 */
class FakeMeApi : MeApi {
    var calls = 0
    var next: suspend () -> Response<DriverRouteResponseDto> = { error("no answer set") }

    override suspend fun driverRoute(): Response<DriverRouteResponseDto> {
        calls++
        return next()
    }

    var nextRoutes: suspend (String?) -> Response<RouteSummaryPageDto> = { error("no answer set") }

    override suspend fun driverRoutes(cursor: String?, limit: Int?): Response<RouteSummaryPageDto> =
        nextRoutes(cursor)

    var nextCrew: suspend () -> Response<CrewPickupResponseDto> = { error("no answer set") }

    override suspend fun crewPickup(): Response<CrewPickupResponseDto> {
        calls++
        return nextCrew()
    }

    val acknowledged = mutableListOf<String>()
    var nextAck: suspend (String) -> Response<NoticeAcknowledgedDto> = { error("no answer set") }

    override suspend fun acknowledgeNotice(noticeId: String): Response<NoticeAcknowledgedDto> {
        acknowledged += noticeId
        return nextAck(noticeId)
    }

    override suspend fun uploadPickupEvents(
        batch: PickupEventBatchDto
    ): Response<PickupEventResultsDto> = error("not used")
}
