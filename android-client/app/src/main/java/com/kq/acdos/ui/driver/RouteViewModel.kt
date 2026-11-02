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
import com.kq.acdos.data.outbox.PickupEventOutbox
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
import kotlinx.coroutines.launch

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
    val progress: StopProgress? = null
)

/** The latest thing the driver recorded at a stop, from the outbox. */
data class StopProgress(
    val type: PickupEventType,
    val exception: PickupExceptionType?,
    /** False until the server has accepted it. */
    val sent: Boolean,
    /** The server's code when it refused the event for good. */
    val conflict: String?,
    /** Picked up or a no-show, and not refused: nothing more to record here. */
    val done: Boolean
)

/** Each stop's progress by route node id, from the driver's events, oldest first. */
fun stopProgress(events: List<PendingPickupEventEntity>): Map<String, StopProgress> =
    events.groupBy { it.routeNodeId }.mapValues { (_, atStop) ->
        val latest = atStop.last()
        StopProgress(
            type = latest.eventType,
            exception = latest.exceptionType,
            sent = latest.syncedAt != null,
            conflict = latest.conflict,
            done = atStop.any { it.conflict == null && it.endsTheStop() }
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

private fun PendingPickupEventEntity.endsTheStop() =
    eventType == PickupEventType.PICKUP_CONFIRMED || exceptionType == PickupExceptionType.NO_SHOW

sealed interface RouteUiState {
    data object Loading : RouteUiState

    data object NoRoute : RouteUiState

    data class Route(val plate: String, val updatedAt: Instant, val stops: List<StopRow>) :
        RouteUiState
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
        RouteUiState.Route(
            plate = cached.route.plateNumber,
            updatedAt = cached.route.fetchedAt,
            stops = cached.stops.sortedBy { it.seqOrder }.map {
                StopRow(
                    routeNodeId = it.routeNodeId,
                    number = it.seqOrder,
                    crewName = it.crewName,
                    zoneLabel = it.zoneLabel,
                    pickupTime = it.eta ?: it.scheduledPickup,
                    lat = it.pickupLat,
                    lon = it.pickupLon,
                    progress = progress[it.routeNodeId]
                )
            }
        )
    }
}.distinctUntilChanged()

/** The signed-in driver's outbox events; none when nobody is signed in. */
private fun driverEvents(
    dao: PendingPickupEventDao,
    driverId: suspend () -> String?
): Flow<List<PendingPickupEventEntity>> = flow {
    val id = driverId()
    if (id == null) emit(emptyList()) else emitAll(dao.observeAll(id))
}

/**
 * [upload] starts an upload that outlives this screen; it runs after every
 * pickup the driver records.
 */
class RouteViewModel(
    dao: DriverRouteDao,
    outboxDao: PendingPickupEventDao,
    driverId: suspend () -> String?,
    private val outbox: PickupEventOutbox,
    private val upload: () -> Unit
) : ViewModel() {
    val state: StateFlow<RouteUiState> = routeState(dao, driverEvents(outboxDao, driverId))
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), RouteUiState.Loading)

    fun confirmPickup(stop: StopRow) = record { outbox.recordConfirmation(stop.routeNodeId) }

    fun reportProblem(stop: StopRow, type: PickupExceptionType) =
        record { outbox.recordException(stop.routeNodeId, type) }

    private fun record(event: suspend () -> Unit) {
        viewModelScope.launch {
            event()
            upload()
        }
    }
}
