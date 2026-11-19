package com.kq.acdos.data

import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.PlannedNodeDto
import com.kq.acdos.data.remote.VehicleStatusDto
import java.time.Duration
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Plan tab's waves: a gap over 60 min or a span over 4 h starts a new one. */
class PlanWavesTest {
    /** [hhmm] on the defence day, Nairobi time. */
    private fun at(hhmm: String) = Instant.parse("2026-11-20T$hhmm:00+03:00")

    private fun pickup(
        id: String,
        hhmm: String,
        status: PickupRequestStatusDto = PickupRequestStatusDto.PENDING
    ) = DispatcherPickupDto(
        id,
        "Crew $id",
        "Kilimani, Nairobi",
        -1.3,
        36.8,
        at(hhmm),
        status,
        needsAck = false,
        acknowledgedAt = null
    )

    /** Pickups every [stepMinutes] from [from] to [to], both included. */
    private fun run(from: String, to: String, stepMinutes: Long): List<DispatcherPickupDto> {
        val times = generateSequence(at(from)) { it.plus(Duration.ofMinutes(stepMinutes)) }
            .takeWhile { it <= at(to) }
        return times.mapIndexed { i, t -> pickup("$from-$i", "00:00").copy(reportTime = t) }
            .toList()
    }

    private fun ranges(waves: List<PlanWave>) = waves.map { it.first to it.last }

    @Test
    fun a0020To0245Group_isItsOwnWave() {
        val pickups = listOf(
            pickup("a", "00:20"),
            pickup("b", "01:05"),
            pickup("c", "02:00"),
            pickup("d", "02:45"),
            // 75 min after the last one.
            pickup("e", "04:00"),
            pickup("f", "04:30")
        )

        val waves = planWaves(pickups)

        assertEquals(
            listOf(at("00:20") to at("02:45"), at("04:00") to at("04:30")),
            ranges(waves)
        )
        assertEquals(listOf("a", "b", "c", "d"), waves.first().pickupIds)
    }

    @Test
    fun aFiveHourRunWithNoGaps_splitsIntoTwoWaves() {
        // Every 15 minutes from 04:00 to 09:00: no gap, but 5 h is more than one plan covers.
        val waves = planWaves(run("04:00", "09:00", 15))

        assertEquals(
            listOf(at("04:00") to at("08:00"), at("08:15") to at("09:00")),
            ranges(waves)
        )
        assertEquals(listOf(17, 4), waves.map { it.pickupIds.size })
    }

    @Test
    fun aSpanOfExactly4h_isOneWave_asTheServerAllows() {
        val waves = planWaves(run("04:00", "08:00", 30))

        assertEquals(listOf(at("04:00") to at("08:00")), ranges(waves))
    }

    @Test
    fun aGapOf61Minutes_splits_andOf60_doesNot() {
        assertEquals(2, planWaves(listOf(pickup("a", "05:00"), pickup("b", "06:01"))).size)
        assertEquals(1, planWaves(listOf(pickup("a", "05:00"), pickup("b", "06:00"))).size)
    }

    @Test
    fun theDefenceDay_givesItsFiveBands() {
        val day = run("04:00", "06:30", 10) + run("08:00", "10:00", 10) +
            run("11:30", "13:30", 10) + run("15:00", "17:30", 10) + run("20:00", "23:00", 10)

        assertEquals(
            listOf(
                at("04:00") to at("06:30"),
                at("08:00") to at("10:00"),
                at("11:30") to at("13:30"),
                at("15:00") to at("17:30"),
                at("20:00") to at("23:00")
            ),
            ranges(planWaves(day.shuffled(java.util.Random(7))))
        )
    }

    @Test
    fun everyPickup_landsInExactlyOneWave() {
        // Uneven gaps, a long run and two at the same time, in no order.
        val pickups = (
            run("00:20", "02:45", 25) + run("03:50", "09:30", 20) +
                listOf(pickup("x", "11:00"), pickup("y", "11:00"), pickup("z", "23:59"))
            ).shuffled(java.util.Random(11))

        val waves = planWaves(pickups)
        val placed = waves.flatMap { it.pickupIds }

        assertEquals(pickups.size, placed.size)
        assertEquals(pickups.map { it.id }.toSet(), placed.toSet())
        // In report-time order, and none wider than the server allows.
        assertEquals(waves.sortedBy { it.first }, waves)
        assertTrue(waves.all { Duration.between(it.first, it.last) <= MAX_PLAN_SPAN })
    }

    private fun van(
        id: String,
        status: VehicleStatusDto = VehicleStatusDto.AVAILABLE,
        onTheRoad: Boolean = false
    ) = DispatcherVehicleDto(id, "KDA $id", 8, status, onTheRoad)

    private fun route(vehicleId: String, from: String, to: String, vararg pickupIds: String) =
        DispatcherRouteDto(
            routeId = "route-$vehicleId-$from",
            vehicleId = vehicleId,
            vehiclePlate = "KDA $vehicleId",
            totalDistanceKm = 30.0,
            plannedDeparture = at(from),
            plannedArrival = at(to),
            nodes = pickupIds.mapIndexed { i, id -> PlannedNodeDto(id, i + 1, at(from)) }
        )

    private val assigned = PickupRequestStatusDto.ASSIGNED

    /** The 08:00–09:30 wave to plan, and vans in each of the server's cases. */
    private val day = DayBoard(
        listOf(
            pickup("w1", "08:00"),
            pickup("w2", "09:30"),
            pickup("e1", "06:00", assigned),
            pickup("o1", "08:30", assigned),
            pickup("o2", "09:00", assigned),
            pickup("l1", "12:00", assigned)
        ),
        listOf(
            van("free"),
            van("early", onTheRoad = true),
            van("on"),
            van("later"),
            van("both"),
            van("broken", VehicleStatusDto.BROKEN_DOWN)
        ),
        listOf(
            route("early", "04:30", "06:15", "e1"),
            route("on", "07:00", "09:15", "o1", "o2"),
            route("later", "10:30", "11:45", "l1"),
            route("both", "04:30", "05:45", "e1"),
            route("both", "10:30", "11:45", "l1")
        )
    )

    private fun statuses(board: DayBoard, vararg pickupIds: String) =
        vanChoices(board, pickupIds.toList()).associate { it.vehicle.id to it.status }

    @Test
    fun eachVan_getsTheServersStatusForTheWave() {
        assertEquals(
            mapOf(
                "free" to VanStatus.Free,
                // Due in at 06:15, so free 15 minutes later, even while still on the road.
                "early" to VanStatus.FreeFrom(at("06:30")),
                // The overlapping route's crew report 08:30 to 09:00.
                "on" to VanStatus.OnWave(at("08:30"), at("09:00")),
                "later" to VanStatus.LaterRoute(at("10:30")),
                // The server leaves out a van with a later route even if it is also reused.
                "both" to VanStatus.LaterRoute(at("10:30"))
            ),
            statuses(day, "w1", "w2")
        )
    }

    @Test
    fun onlyFreeVans_startTicked() {
        val ticked = vanChoices(day, listOf("w1", "w2"))
            .filter { it.tickedByDefault }
            .map { it.vehicle.id }

        assertEquals(listOf("free", "early"), ticked)
    }

    @Test
    fun theTurnaround_isTheServers15Minutes() {
        assertEquals(Duration.ofMinutes(15), REUSE_TURNAROUND)
    }

    @Test
    fun aRouteDueInAtTheWavesFirstReportTime_overlapsIt() {
        // An earlier route arrives strictly before the wave's first report time.
        val board = day.copy(routes = listOf(route("early", "06:30", "08:00", "e1")))

        assertEquals(
            VanStatus.OnWave(at("06:00"), at("06:00")),
            statuses(board, "w1", "w2")["early"]
        )
    }

    @Test
    fun theRouteCarryingTheJobsOwnPickups_doesntCount() {
        // A flight-delay re-plan of o1: the route it is on is the one being replaced.
        assertEquals(VanStatus.Free, statuses(day, "o1")["on"])
    }

    // The cases of #275's test_van_reuse_postgres.py, wave 10:00–10:15.
    private fun kind(depart: String, arrive: String, vararg crew: String) = routeKind(
        arrival = at(arrive),
        departure = at(depart),
        crewReport = crew.map(::at),
        start = at("10:00"),
        end = at("10:15")
    )

    @Test
    fun aVanIsReusedAcrossTwoWaves_itsEarlyRouteIsEarlier() {
        // The early wave's route: crew 05:00 and 05:15, in at JKIA well before 10:00.
        assertEquals(RouteKind.EARLIER, kind("03:45", "04:50", "05:00", "05:15"))
    }

    @Test
    fun aRouteInAt1030_overlapsTheWave_andIsReplaced() {
        assertEquals(RouteKind.OVERLAPPING, kind("09:00", "10:30", "10:20"))
    }

    @Test
    fun aRouteLeavingAt1430_isLater_andItsVanIsLeftOut() {
        assertEquals(RouteKind.LATER, kind("14:30", "15:20", "15:30"))
    }

    @Test
    fun aRouteOfThisWavesCrew_isNeverEarlier_evenIfItArrivesEarly() {
        // 3a14321: in at 09:50, but its crew reports at 10:05, inside the wave.
        assertEquals(RouteKind.OVERLAPPING, kind("08:40", "09:50", "10:05"))
        // A crew member reporting exactly at the wave's start is not before it.
        assertEquals(RouteKind.OVERLAPPING, kind("08:40", "09:50", "10:00"))
    }

    @Test
    fun aLaterRoute_needsAllItsCrewAfterTheWave() {
        // Leaves after 10:15, but one of its crew reports at 10:15.
        assertEquals(RouteKind.OVERLAPPING, kind("10:30", "11:20", "10:15", "11:30"))
    }

    @Test
    fun aBrokenVansLaterRoutes_needAVan_untilEachIsReplanned() {
        val board = day.copy(
            pickups = day.pickups + listOf(
                pickup("b1", "08:15", assigned),
                pickup("b2", "15:00", assigned),
                pickup("b3", "20:00", PickupRequestStatusDto.PICKED_UP)
            ),
            routes = listOf(
                route("broken", "06:45", "08:00", "b1"),
                route("broken", "13:30", "14:45", "b2"),
                // All collected: nothing left to re-plan.
                route("broken", "18:30", "19:45", "b3")
            )
        )

        // b1's route is the pending re-plan; only the later one is waiting.
        assertEquals(
            listOf(RouteNeedingVan("KDA broken", at("13:30"), at("14:45"), listOf("b2"))),
            routesNeedingAVan(board, replanning = listOf("b1"))
        )
        assertEquals(emptyList<RouteNeedingVan>(), routesNeedingAVan(board, listOf("b1", "b2")))
    }

    @Test
    fun onlyUnplannedPickups_goIntoWaves() {
        val board = DayBoard(
            listOf(
                pickup("p1", "05:00"),
                pickup("p2", "05:10", PickupRequestStatusDto.ASSIGNED),
                pickup("p3", "05:20")
            ),
            emptyList(),
            emptyList()
        )

        assertEquals(listOf(listOf("p1", "p3")), planWaves(board).map { it.pickupIds })
    }
}
