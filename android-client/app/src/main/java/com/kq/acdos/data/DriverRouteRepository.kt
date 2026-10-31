package com.kq.acdos.data

import com.kq.acdos.data.local.DriverRouteDao
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.DriverRouteDto
import com.kq.acdos.data.remote.ErrorCode
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.RouteStatusDto
import com.kq.acdos.data.remote.apiCall
import java.time.Duration
import java.time.Instant
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** How a refresh ended. Only the failures change what the driver is told. */
enum class RefreshResult {
    /** The active route is saved. */
    UPDATED,

    /** No active route on the server; the cached one is gone. */
    NO_ROUTE,

    /** Skipped: the last attempt was under [DriverRouteRepository.THROTTLE] ago. */
    THROTTLED,

    /** No answer from the server. */
    OFFLINE,

    /** A 401 that the token refresh (#26) couldn't fix. */
    SIGN_IN_AGAIN,

    /** 403: the account isn't a driver. */
    NOT_ALLOWED,

    /** Any other error, or an answer the app can't read. */
    FAILED
}

/**
 * Keeps the Room copy of the driver's route (#28) in step with
 * GET /drivers/me/route (#52). Whatever goes wrong, the cached route stays
 * as it was, so the Route tab still works with no signal.
 */
class DriverRouteRepository(
    private val api: MeApi,
    private val dao: DriverRouteDao,
    private val clock: () -> Instant = Instant::now
) {
    private val lock = Mutex()

    /** When the last refresh started, whatever its result. Guarded by [lock]. */
    private var lastAttempt: Instant? = null

    /**
     * The only way the cached route is refreshed. Callers:
     * - the driver home on start, with force = false, so a driver coming back
     *   from Maps sees a re-plan without pulling;
     * - pull to refresh on the Route tab, with force = true;
     * - #55's FCM handler, with force = true, when the dispatcher re-plans.
     *
     * Without [force], it is skipped when the last attempt was under
     * [THROTTLE] ago. Calls run one at a time.
     */
    suspend fun refresh(force: Boolean): RefreshResult = lock.withLock {
        val now = clock()
        val last = lastAttempt
        if (!force && last != null && Duration.between(last, now) < THROTTLE) {
            return RefreshResult.THROTTLED
        }
        lastAttempt = now

        when (val result = apiCall { api.driverRoute() }) {
            is ApiResult.Success -> save(result.body.route, now)

            is ApiResult.NetworkError -> RefreshResult.OFFLINE

            is ApiResult.Error -> when (result.code) {
                ErrorCode.UNAUTHORIZED -> RefreshResult.SIGN_IN_AGAIN
                ErrorCode.FORBIDDEN -> RefreshResult.NOT_ALLOWED
                else -> RefreshResult.FAILED
            }
        }
    }

    /**
     * Only an active route is kept. A completed or superseded one is deleted
     * with its stops; pending pickup events are separate rows and stay (#29
     * still uploads them).
     */
    private suspend fun save(route: DriverRouteDto?, fetchedAt: Instant): RefreshResult {
        if (route == null || route.status != RouteStatusDto.ACTIVE) {
            dao.deleteAllRoutes()
            return RefreshResult.NO_ROUTE
        }
        dao.saveActiveRoute(
            RouteEntity(route.routeId, route.vehiclePlate, fetchedAt),
            route.stops.map { stop ->
                RouteStopEntity(
                    routeNodeId = stop.routeNodeId,
                    routeId = route.routeId,
                    seqOrder = stop.seqOrder,
                    crewName = stop.crewName,
                    zoneLabel = stop.zoneLabel,
                    scheduledPickup = stop.scheduledPickup,
                    eta = stop.eta,
                    pickupLat = stop.lat,
                    pickupLon = stop.lon
                )
            }
        )
        return RefreshResult.UPDATED
    }

    companion object {
        val THROTTLE: Duration = Duration.ofSeconds(60)
    }
}
