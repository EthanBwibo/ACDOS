package com.kq.acdos.ui.dispatcher

import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.PlannedNodeDto
import com.kq.acdos.data.routeStops
import com.kq.acdos.ui.driver.MapPoint
import com.kq.acdos.ui.driver.StopMark
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

/** The dispatcher's read-only route map (#227) marks stops from the day's board. */
class RouteMapStopsTest {
    private val t0 = Instant.parse("2026-11-07T02:00:00Z")

    private fun pickup(id: String, lat: Double, status: PickupRequestStatusDto) =
        DispatcherPickupDto(
            id = id,
            crewName = "Crew $id",
            zoneLabel = "Karen, Nairobi",
            lat = lat,
            lon = 36.8,
            reportTime = t0,
            status = status,
            needsAck = false,
            acknowledgedAt = null
        )

    private val route = DispatcherRouteDto(
        routeId = "r1",
        vehicleId = "v1",
        vehiclePlate = "KDH v1",
        totalDistanceKm = 20.0,
        plannedDeparture = t0,
        plannedArrival = t0,
        nodes = listOf("p1", "p2", "p3", "p4").mapIndexed { i, id ->
            PlannedNodeDto(id, i + 1, t0)
        }
    )

    private fun board(vararg pickups: DispatcherPickupDto) =
        DayBoard(pickups = pickups.toList(), vehicles = emptyList(), routes = listOf(route))

    @Test
    fun `picked up stops are grey and the first still waiting is next`() {
        val board = board(
            pickup("p1", -1.30, PickupRequestStatusDto.PICKED_UP),
            pickup("p2", -1.29, PickupRequestStatusDto.MISSED),
            pickup("p3", -1.28, PickupRequestStatusDto.ASSIGNED),
            pickup("p4", -1.27, PickupRequestStatusDto.ASSIGNED)
        )

        val stops = dispatcherMapStops(board, routeStops(board, route))

        assertEquals(
            listOf(StopMark.PICKED_UP, StopMark.AHEAD, StopMark.NEXT, StopMark.AHEAD),
            stops.map { it.mark }
        )
        assertEquals(listOf(1, 2, 3, 4), stops.map { it.number })
        assertEquals(MapPoint(-1.28, 36.8), stops[2].point)
    }
}
