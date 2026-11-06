package com.kq.acdos.ui.driver

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.kq.acdos.R
import com.kq.acdos.data.local.DriverRouteDao
import com.kq.acdos.data.local.PendingPickupEventDao
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import java.time.Duration
import java.time.Instant
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn

/** One row of the Route tab. */
data class StopRow(
    val routeNodeId: String,
    val number: Int,
    val crewName: String,
    val zoneLabel: String?,
    /** The ETA when the backend has one, otherwise the planned time. */
    val pickupTime: Instant,
    val lat: Double,
    val lon: Double,
    /** Null until the driver records something here. */
    val progress: StopProgress? = null,
    /** Planned minutes from the stop before. Null for the first stop or under a minute. */
    val minutesFromPrevious: Int? = null
)

/** The latest thing the driver recorded at a stop, from the outbox. */
data class StopProgress(
    val type: PickupEventType,
    val exception: PickupExceptionType?,
    /** False until the server has accepted it. */
    val sent: Boolean,
    /** The server's code when it refused the event for good. */
    val conflict: String?,
    /** Picked up or a no-show, and not refused: not the next pickup any more. */
    val done: Boolean,
    /** Marked a no-show and not picked up since, so a late arrival can still be recorded. */
    val noShow: Boolean = false
)

/** Each stop's progress by route node id, from the driver's events, oldest first. */
fun stopProgress(events: List<PendingPickupEventEntity>): Map<String, StopProgress> =
    events.groupBy { it.routeNodeId }.mapValues { (_, atStop) ->
        val latest = atStop.last()
        val accepted = atStop.filter { it.conflict == null }
        val confirmed = accepted.any { it.eventType == PickupEventType.PICKUP_CONFIRMED }
        val noShow = !confirmed && accepted.any { it.exceptionType == PickupExceptionType.NO_SHOW }
        StopProgress(
            type = latest.eventType,
            exception = latest.exceptionType,
            sent = latest.syncedAt != null,
            conflict = latest.conflict,
            done = confirmed || noShow,
            noShow = noShow
        )
    }

/** What the stop's status line says, before " · not sent yet" or a refusal. */
@StringRes
fun progressLabel(progress: StopProgress): Int = when (progress.exception) {
    null -> R.string.route_status_picked_up
    PickupExceptionType.NO_SHOW -> R.string.route_status_no_show
    PickupExceptionType.VEHICLE_ISSUE -> R.string.route_status_vehicle_issue
    PickupExceptionType.TRAFFIC_DELAY -> R.string.route_status_traffic_delay
}

/**
 * Whole minutes between two planned stop times, or null under a minute (two crew at the same
 * address). The plan's gap, so it includes any wait at the earlier stop.
 */
fun legMinutes(from: Instant, to: Instant): Int? {
    val minutes = Duration.between(from, to).plusSeconds(30).toMinutes().toInt()
    return minutes.takeIf { it > 0 }
}

sealed interface RouteUiState {
    data object Loading : RouteUiState

    data object NoRoute : RouteUiState

    data class Route(
        val plate: String,
        val updatedAt: Instant,
        val arriveBy: Instant,
        val stops: List<StopRow>,
        /** Events waiting to upload, on this route or an older one. */
        val queued: Int = 0
    ) : RouteUiState
}

/** The Route tab's one job at a time: the next pickup, and what follows it. */
data class RouteProgress(
    val next: StopRow?,
    val then: List<StopRow>,
    val pickedUp: Int,
    /** Still reachable, because the crew member may yet turn up. */
    val noShows: List<StopRow> = emptyList()
)

/**
 * A stop stays open until it is done, so one the server refused comes back as the next
 * pickup. A no-show is done but isn't counted as picked up.
 */
fun routeProgress(stops: List<StopRow>): RouteProgress {
    val open = stops.filter { it.progress?.done != true }
    val pickedUp = stops.count { it.progress?.done == true && !it.progress.noShow }
    val noShows = stops.filter { it.progress?.noShow == true }
    return RouteProgress(open.firstOrNull(), open.drop(1), pickedUp, noShows)
}

/** "Westlands" from "Westlands, Nairobi". */
fun shortZone(label: String): String = label.substringBefore(',')

/** The sync chip is always on screen, so the driver knows queued events are safe. */
@StringRes
fun syncChipText(online: Boolean, queued: Int): Int = when {
    !online -> R.string.sync_chip_offline
    queued > 0 -> R.string.sync_chip_online
    else -> R.string.sync_chip_all_sent
}

/**
 * The cached route as the Route tab shows it, in stop order, with what the
 * driver has recorded at each stop ([events], oldest first). Room re-runs the
 * queries whenever the tables change; repeats of the same state are dropped.
 */
fun routeState(
    dao: DriverRouteDao,
    events: Flow<List<PendingPickupEventEntity>> = flowOf(emptyList())
): Flow<RouteUiState> = combine(dao.observeRouteWithStops(), events) { cached, recorded ->
    val progress = stopProgress(recorded)
    if (cached == null) {
        RouteUiState.NoRoute
    } else {
        val inOrder = cached.stops.sortedBy { it.seqOrder }
        RouteUiState.Route(
            plate = cached.route.plateNumber,
            updatedAt = cached.route.fetchedAt,
            arriveBy = cached.route.plannedArrival,
            stops = inOrder.mapIndexed { index, stop ->
                StopRow(
                    routeNodeId = stop.routeNodeId,
                    number = stop.seqOrder,
                    crewName = stop.crewName,
                    zoneLabel = stop.zoneLabel,
                    pickupTime = stop.eta ?: stop.scheduledPickup,
                    lat = stop.pickupLat,
                    lon = stop.pickupLon,
                    progress = progress[stop.routeNodeId],
                    minutesFromPrevious = inOrder.getOrNull(index - 1)?.let { previous ->
                        legMinutes(previous.scheduledPickup, stop.scheduledPickup)
                    }
                )
            },
            queued = recorded.count { it.syncedAt == null && it.conflict == null }
        )
    }
}.distinctUntilChanged()

/** The signed-in driver's outbox events, oldest first; none when nobody is signed in. */
fun driverEvents(
    dao: PendingPickupEventDao,
    driverId: suspend () -> String?
): Flow<List<PendingPickupEventEntity>> = flow {
    val id = driverId()
    if (id == null) emit(emptyList()) else emitAll(dao.observeAll(id))
}

class RouteViewModel(
    dao: DriverRouteDao,
    outboxDao: PendingPickupEventDao,
    driverId: suspend () -> String?
) : ViewModel() {
    val state: StateFlow<RouteUiState> = routeState(dao, driverEvents(outboxDao, driverId))
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), RouteUiState.Loading)
}
