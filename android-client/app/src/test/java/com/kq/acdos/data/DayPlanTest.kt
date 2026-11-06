package com.kq.acdos.data

import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.PlannedNodeDto
import com.kq.acdos.data.remote.VehicleStatusDto
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** The numbers on the hub, Route detail and Re-plan, all worked out from one day's board. */
class DayPlanTest {
    private val t0 = Instant.parse("2026-11-07T02:00:00Z")

    private fun at(minutes: Long) = t0.plusSeconds(minutes * 60)

    private fun pickup(
        id: String,
        report: Long,
        zone: String? = "Karen, Nairobi",
        status: PickupRequestStatusDto = PickupRequestStatusDto.ASSIGNED
    ) = DispatcherPickupDto(
        id = id,
        crewName = "Crew $id",
        zoneLabel = zone,
        lat = -1.3,
        lon = 36.8,
        reportTime = at(report),
        status = status,
        needsAck = false,
        acknowledgedAt = null
    )

    private fun route(id: String, van: String, leaves: Long, arrives: Long, vararg stops: String) =
        DispatcherRouteDto(
            routeId = id,
            vehicleId = van,
            vehiclePlate = "KDH $van",
            totalDistanceKm = 20.0,
            plannedDeparture = at(leaves),
            plannedArrival = at(arrives),
            nodes = stops.mapIndexed { i, stop -> PlannedNodeDto(stop, i + 1, at(leaves + i)) }
        )

    private fun van(id: String) =
        DispatcherVehicleDto(id, "KDH $id", 14, VehicleStatusDto.AVAILABLE, false)

    private val board = DayBoard(
        pickups = listOf(pickup("p1", 100), pickup("p2", 50), pickup("p3", 200)),
        vehicles = listOf(van("v1"), van("v2"), van("v3")),
        routes = listOf(
            route("late", "v2", 30, 90, "p3", "p2"),
            route("first", "v1", 10, 40, "p1")
        )
    )

    @Test
    fun `a pickup is late when its van reaches JKIA after its report time`() {
        assertEquals(setOf("p2"), latePickups(board))
    }

    @Test
    fun `the summary adds up the vans' time on the road`() {
        assertEquals(
            PlanSummary(plannedDriveMinutes = 90, vansUsed = 2, vans = 3, late = 1),
            planSummary(board)
        )
    }

    @Test
    fun `the window runs from the first report time to the last`() {
        assertEquals(at(50) to at(200), planWindow(board))
        assertNull(planWindow(DayBoard(emptyList(), emptyList(), emptyList())))
    }

    @Test
    fun `routes number from the first to leave`() {
        assertEquals(listOf("first", "late"), orderedRoutes(board).map { it.routeId })
    }

    @Test
    fun `a stop carries its crew member and report time`() {
        val stop = routeStops(board, board.routes[0])[1]

        assertEquals("p2", stop.pickupId)
        assertEquals("Crew p2", stop.crewName)
        assertEquals(at(50), stop.reportTime)
        assertEquals(at(31), stop.pickupAt)
        assertEquals(-1.3, stop.lat!!, 0.0)
        assertEquals(36.8, stop.lon!!, 0.0)
    }

    @Test
    fun `the next stop is the first still to collect`() {
        val picked = PickupRequestStatusDto.PICKED_UP
        val partly = board.copy(
            pickups = listOf(pickup("p3", 200, status = picked), pickup("p2", 50))
        )
        val route = partly.routes[0]

        assertEquals(1, nextStopIndex(partly, routeStops(partly, route)))
    }

    @Test
    fun `no stop is next once the route is finished`() {
        val done = board.copy(
            pickups = board.pickups.map { it.copy(status = PickupRequestStatusDto.PICKED_UP) }
        )

        assertEquals(-1, nextStopIndex(done, routeStops(done, done.routes[0])))
    }

    @Test
    fun `slack is to the first report time on the route, and negative when late`() {
        assertEquals(60L, slackMinutes(board, board.routes[1]))
        assertEquals(-40L, slackMinutes(board, board.routes[0]))
    }
}
