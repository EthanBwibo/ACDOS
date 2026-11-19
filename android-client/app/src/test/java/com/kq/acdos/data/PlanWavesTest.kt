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

    private fun van(id: String, status: VehicleStatusDto = VehicleStatusDto.AVAILABLE) =
        DispatcherVehicleDto(id, "KDA $id", 8, status, onTheRoad = false)

    private fun route(vehicleId: String, vararg pickupIds: String) = DispatcherRouteDto(
        routeId = "route-$vehicleId-${pickupIds.first()}",
        vehicleId = vehicleId,
        vehiclePlate = "KDA $vehicleId",
        totalDistanceKm = 30.0,
        plannedDeparture = at("02:30"),
        plannedArrival = at("03:45"),
        nodes = pickupIds.mapIndexed { i, id -> PlannedNodeDto(id, i + 1, at("03:00")) }
    )

    @Test
    fun aVanWithARouteToday_isOnItsWave_andStartsUnticked() {
        val assigned = PickupRequestStatusDto.ASSIGNED
        val board = DayBoard(
            listOf(
                pickup("a", "04:00", assigned),
                pickup("b", "06:30", assigned),
                pickup("c", "08:00", assigned),
                pickup("d", "09:15", assigned),
                pickup("e", "11:30")
            ),
            listOf(van("v1"), van("v2"), van("v3"), van("v4", VehicleStatusDto.BROKEN_DOWN)),
            listOf(route("v1", "a", "b"), route("v2", "d", "c"), route("v2", "a"))
        )

        val choices = vanChoices(board).associateBy { it.vehicle.id }

        // v4 is broken down, so it isn't offered at all.
        assertEquals(setOf("v1", "v2", "v3"), choices.keys)
        assertEquals(listOf(at("04:00") to at("06:30")), choices.getValue("v1").waves)
        // Two routes: two waves, earliest first.
        assertEquals(
            listOf(at("04:00") to at("04:00"), at("08:00") to at("09:15")),
            choices.getValue("v2").waves
        )
        assertEquals(emptyList<Pair<Instant, Instant>>(), choices.getValue("v3").waves)
        assertEquals(
            mapOf("v1" to false, "v2" to false, "v3" to true),
            choices.mapValues { it.value.tickedByDefault }
        )
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
