package com.kq.acdos.data

import com.kq.acdos.data.remote.DispatcherRouteDto
import java.time.Duration
import java.time.Instant

/** The day's plan in the numbers the dispatcher compares before and after a re-plan. */
data class PlanSummary(
    /**
     * Each route's departure to arrival, added up, waiting at stops included.
     * Not the solver's objective: jobs don't store that.
     */
    val plannedDriveMinutes: Long,
    val vansUsed: Int,
    val vans: Int,
    val late: Int
)

/** The pickups whose van reaches JKIA after their report time. */
fun latePickups(board: DayBoard): Set<String> {
    val reportTimes = board.pickups.associate { it.id to it.reportTime }
    return board.routes.flatMap { route ->
        route.nodes.map { it.pickupRequestId }.filter { pickup ->
            reportTimes[pickup]?.let { route.plannedArrival > it } == true
        }
    }.toSet()
}

fun planSummary(board: DayBoard) = PlanSummary(
    plannedDriveMinutes = board.routes.sumOf {
        Duration.between(it.plannedDeparture, it.plannedArrival).toMinutes()
    },
    vansUsed = board.routes.map { it.vehicleId }.distinct().size,
    vans = board.vehicles.size,
    late = latePickups(board).size
)

/** The earliest and latest report times, or null with no pickups. */
fun planWindow(board: DayBoard): Pair<Instant, Instant>? {
    val times = board.pickups.map { it.reportTime }
    return if (times.isEmpty()) null else times.min() to times.max()
}

/** First to leave first, so a route's "R1" number holds through the day. */
fun orderedRoutes(board: DayBoard): List<DispatcherRouteDto> =
    board.routes.sortedWith(compareBy({ it.plannedDeparture }, { it.vehiclePlate }))

/** One stop on a route, with its crew member from the day's pickups. */
data class RouteStop(
    val seqOrder: Int,
    val pickupId: String,
    val zoneLabel: String?,
    val crewName: String?,
    /** Where the stop is on the map; null if its pickup isn't on the day's board. */
    val lat: Double?,
    val lon: Double?,
    val pickupAt: Instant,
    val reportTime: Instant?
)

fun routeStops(board: DayBoard, route: DispatcherRouteDto): List<RouteStop> {
    val pickups = board.pickups.associateBy { it.id }
    return route.nodes.sortedBy { it.seqOrder }.map { node ->
        val pickup = pickups[node.pickupRequestId]
        RouteStop(
            seqOrder = node.seqOrder,
            pickupId = node.pickupRequestId,
            zoneLabel = pickup?.zoneLabel,
            crewName = pickup?.crewName,
            lat = pickup?.lat,
            lon = pickup?.lon,
            pickupAt = node.estimatedArrival,
            reportTime = pickup?.reportTime
        )
    }
}

/** Position in [stops] of the first pickup still to collect, or -1 when none is left. */
fun nextStopIndex(board: DayBoard, stops: List<RouteStop>): Int {
    val waiting = board.pickups.filter { it.status in REPLANNABLE }.map { it.id }.toSet()
    return stops.indexOfFirst { it.pickupId in waiting }
}

/** Minutes between reaching JKIA and the first report time; negative when late. */
fun slackMinutes(board: DayBoard, route: DispatcherRouteDto): Long? {
    val first = routeStops(board, route).mapNotNull { it.reportTime }.minOrNull() ?: return null
    return Duration.between(route.plannedArrival, first).toMinutes()
}
