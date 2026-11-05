package com.kq.acdos.data

import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.RouteSummaryDto
import com.kq.acdos.data.remote.apiCall

/** How loading the schedule ended. */
sealed interface ScheduleResult {
    data class Loaded(val routes: List<RouteSummaryDto>) : ScheduleResult

    data class Failed(val reason: RefreshResult) : ScheduleResult
}

/**
 * The driver's planned routes, from GET /drivers/me/routes. Not cached in Room: a read-only
 * list of later routes isn't needed at the roadside, and the Route tab keeps the current
 * route offline.
 */
class DriverScheduleRepository(private val api: MeApi) {
    /** Follows every page, so a route is never quietly missing. A driver only has a few. */
    suspend fun routes(): ScheduleResult {
        val routes = mutableListOf<RouteSummaryDto>()
        var cursor: String? = null
        do {
            val after = cursor
            when (val page = apiCall { api.driverRoutes(after, PAGE_SIZE) }) {
                is ApiResult.Success -> {
                    routes += page.body.items
                    cursor = page.body.nextCursor
                }

                is ApiResult.NetworkError -> return ScheduleResult.Failed(RefreshResult.OFFLINE)

                is ApiResult.Error -> return ScheduleResult.Failed(page.asRefreshResult())
            }
        } while (cursor != null)
        return ScheduleResult.Loaded(routes)
    }

    private companion object {
        const val PAGE_SIZE = 20
    }
}
