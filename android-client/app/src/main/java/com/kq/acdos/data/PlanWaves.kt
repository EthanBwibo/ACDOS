package com.kq.acdos.data

import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.VehicleStatusDto
import java.time.Duration
import java.time.Instant

/**
 * The widest span of report times one plan may cover. The server refuses a
 * wider job with planning_window_too_wide. This is the app's only copy of the
 * limit, so a wave never asks for more than the server allows.
 */
val MAX_PLAN_SPAN: Duration = Duration.ofHours(4)

/** A gap longer than this between two report times starts a new wave. */
val WAVE_GAP: Duration = Duration.ofMinutes(60)

/** Pickups planned together: report times from [first] to [last]. */
data class PlanWave(val first: Instant, val last: Instant, val pickupIds: List<String>)

/**
 * [pickups] in waves, earliest first. In report-time order, a pickup starts a
 * new wave when it is more than [WAVE_GAP] after the one before it, or when
 * joining would make the wave span more than [MAX_PLAN_SPAN]. Each pickup is
 * in exactly one wave.
 */
fun planWaves(pickups: List<DispatcherPickupDto>): List<PlanWave> {
    val waves = mutableListOf<PlanWave>()
    for (pickup in pickups.sortedWith(compareBy({ it.reportTime }, { it.id }))) {
        val wave = waves.lastOrNull()
        val at = pickup.reportTime
        if (wave != null &&
            Duration.between(wave.last, at) <= WAVE_GAP &&
            Duration.between(wave.first, at) <= MAX_PLAN_SPAN
        ) {
            waves[waves.lastIndex] = wave.copy(last = at, pickupIds = wave.pickupIds + pickup.id)
        } else {
            waves += PlanWave(at, at, listOf(pickup.id))
        }
    }
    return waves
}

/** The day's unplanned pickups in waves: the ones a first plan takes. */
fun planWaves(board: DayBoard): List<PlanWave> {
    val unplanned = unplannedPickups(board).toSet()
    return planWaves(board.pickups.filter { it.id in unplanned })
}

/**
 * How long after an earlier route is due at JKIA its van may leave on the next
 * one. The app's only copy of the server's REUSE_TURNAROUND (#274).
 */
val REUSE_TURNAROUND: Duration = Duration.ofMinutes(15)

/** Where a van stands for one wave, by the server's rule (#274). */
sealed interface VanStatus {
    /** No route today that touches the wave. */
    data object Free : VanStatus

    /** Its routes reach JKIA before the wave, so it is reused from [at]. */
    data class FreeFrom(val at: Instant) : VanStatus

    /** A route of its overlaps the wave; [first] to [last] are that route's report times. */
    data class OnWave(val first: Instant, val last: Instant) : VanStatus

    /** A route of its leaves after the wave, at [departure]; the server would leave it out. */
    data class LaterRoute(val departure: Instant) : VanStatus
}

/** A van in the picker, with its status for the job's wave. */
data class VanChoice(val vehicle: DispatcherVehicleDto, val status: VanStatus) {
    /** Only a van free for the wave starts ticked; the dispatcher can still tick the others. */
    val tickedByDefault: Boolean
        get() = status == VanStatus.Free || status is VanStatus.FreeFrom
}

/** How one of a van's routes today stands to a wave (#274). */
enum class RouteKind { EARLIER, LATER, OVERLAPPING }

/**
 * The server's rule for a route against the wave from [start] to [end] (its
 * earliest and latest report times), as in store.py's _OVERLAPS_WAVE since
 * 3a14321. [crewReport] holds the report times of the route's crew.
 * - Earlier: in at JKIA before [start], and all its crew report before it too,
 *   so a route of this wave's crew that arrives early is not an earlier wave's.
 * - Later: leaves after [end], and all its crew report after it.
 * - Anything else overlaps.
 */
fun routeKind(
    arrival: Instant,
    departure: Instant,
    crewReport: List<Instant>,
    start: Instant,
    end: Instant
): RouteKind = when {
    arrival < start && crewReport.all { it < start } -> RouteKind.EARLIER
    departure > end && crewReport.all { it > end } -> RouteKind.LATER
    else -> RouteKind.OVERLAPPING
}

/**
 * The vans a job for [pickupIds] may use, each with its status for their wave
 * (the pickups' earliest to latest report time). As on the server, a van's
 * routes that carry the job's own pickups don't count: the job replaces them.
 * The rest are sorted by [routeKind]. An overlapping route outweighs a later
 * one, and a later one an earlier one, since the server leaves out a van with
 * a later route. Broken-down and unavailable vans are not offered; vans on the
 * road are, since an earlier wave's van is reused.
 */
fun vanChoices(board: DayBoard, pickupIds: Collection<String>): List<VanChoice> {
    val ids = pickupIds.toSet()
    val reportTimes = board.pickups.associate { it.id to it.reportTime }
    val times = ids.mapNotNull { reportTimes[it] }
    val plannable = plannableVans(board).toSet()
    return board.vehicles.filter { it.id in plannable }.map { van ->
        val routes = board.routes.filter { route ->
            route.vehicleId == van.id && route.nodes.none { it.pickupRequestId in ids }
        }
        val status = if (times.isEmpty()) {
            VanStatus.Free
        } else {
            vanStatus(routes, times.min(), times.max(), reportTimes)
        }
        VanChoice(van, status)
    }
}

private fun vanStatus(
    routes: List<DispatcherRouteDto>,
    start: Instant,
    end: Instant,
    reportTimes: Map<String, Instant>
): VanStatus {
    val crew = routes.associateWith { route ->
        route.nodes.mapNotNull { reportTimes[it.pickupRequestId] }
    }
    val kinds = routes.groupBy { route ->
        routeKind(route.plannedArrival, route.plannedDeparture, crew.getValue(route), start, end)
    }
    val earlier = kinds[RouteKind.EARLIER].orEmpty()
    val later = kinds[RouteKind.LATER].orEmpty()
    kinds[RouteKind.OVERLAPPING]?.minByOrNull { it.plannedDeparture }?.let { route ->
        val times = crew.getValue(route)
        return if (times.isEmpty()) {
            VanStatus.OnWave(route.plannedDeparture, route.plannedArrival)
        } else {
            VanStatus.OnWave(times.min(), times.max())
        }
    }
    later.minByOrNull { it.plannedDeparture }?.let {
        return VanStatus.LaterRoute(it.plannedDeparture)
    }
    earlier.maxByOrNull { it.plannedArrival }?.let {
        return VanStatus.FreeFrom(it.plannedArrival + REUSE_TURNAROUND)
    }
    return VanStatus.Free
}

/** A broken-down van's route with crew still to collect, waiting for a re-plan. */
data class RouteNeedingVan(
    val plate: String,
    val departure: Instant,
    val arrival: Instant,
    val pickupIds: List<String>
)

/**
 * Routes of broken-down vans that still have crew to collect, earliest first.
 * A breakdown re-plans only the van's current route (strandedPickups), so its
 * later routes wait here until each is re-planned. Routes carrying any of
 * [replanning] (the pending re-plan's or the latest job's pickups) are left
 * out: they are already being dealt with.
 */
fun routesNeedingAVan(board: DayBoard, replanning: Collection<String>): List<RouteNeedingVan> {
    val broken = board.vehicles
        .filter { it.status == VehicleStatusDto.BROKEN_DOWN }
        .map { it.id }
        .toSet()
    val waiting = board.pickups.filter { it.status in REPLANNABLE }.map { it.id }.toSet()
    val dealtWith = replanning.toSet()
    return board.routes
        .filter { it.vehicleId in broken }
        .sortedBy { it.plannedDeparture }
        .mapNotNull { route ->
            val ids = route.nodes.map { it.pickupRequestId }.filter { it in waiting }
            if (ids.isEmpty() || ids.any { it in dealtWith }) {
                null
            } else {
                RouteNeedingVan(
                    route.vehiclePlate,
                    route.plannedDeparture,
                    route.plannedArrival,
                    ids
                )
            }
        }
}
