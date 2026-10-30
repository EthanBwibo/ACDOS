package com.kq.acdos.ui.driver

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.kq.acdos.data.local.DriverRouteDao
import java.time.Instant
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
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
    val lon: Double
)

sealed interface RouteUiState {
    data object Loading : RouteUiState

    data object NoRoute : RouteUiState

    data class Route(val plate: String, val updatedAt: Instant, val stops: List<StopRow>) :
        RouteUiState
}

/**
 * The cached route as the Route tab shows it, in stop order. Room re-runs the
 * query whenever either table changes; repeats of the same state are dropped.
 */
fun routeState(dao: DriverRouteDao): Flow<RouteUiState> = dao.observeRouteWithStops()
    .map { cached ->
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
                        lon = it.pickupLon
                    )
                }
            )
        }
    }
    .distinctUntilChanged()

class RouteViewModel(dao: DriverRouteDao) : ViewModel() {
    val state: StateFlow<RouteUiState> = routeState(dao)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), RouteUiState.Loading)
}
