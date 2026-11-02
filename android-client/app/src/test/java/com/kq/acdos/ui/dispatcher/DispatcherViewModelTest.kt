package com.kq.acdos.ui.dispatcher

import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.plannableVans
import com.kq.acdos.data.remote.DispatcherApi
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherPickupPageDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.remote.DispatcherRoutePageDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.DispatcherVehiclePageDto
import com.kq.acdos.data.remote.OptimisationJobAcceptedDto
import com.kq.acdos.data.remote.OptimisationJobCreateDto
import com.kq.acdos.data.remote.OptimisationJobResultDto
import com.kq.acdos.data.remote.OptimisationJobsApi
import com.kq.acdos.data.remote.OptimizationJobStatusDto
import com.kq.acdos.data.remote.OptimizationTriggerTypeDto
import com.kq.acdos.data.remote.PickupReportTimeUpdateDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.PlannedNodeDto
import com.kq.acdos.data.remote.VehicleStatusDto
import com.kq.acdos.data.remote.VehicleStatusUpdateDto
import com.kq.acdos.data.strandedPickups
import com.kq.acdos.data.unplannedPickups
import java.time.Instant
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test
import retrofit2.Response

/** The dispatcher's main path against fake APIs: plan, disrupt, re-plan. */
class DispatcherViewModelTest {
    private val day = LocalDate.parse("2026-11-03")
    private val t0 = Instant.parse("2026-11-03T05:30:00Z")

    private fun pickup(id: String, status: PickupRequestStatusDto) =
        DispatcherPickupDto(id, "Crew $id", "Kilimani, Nairobi", t0, status)

    private fun van(id: String, status: VehicleStatusDto, onTheRoad: Boolean = false) =
        DispatcherVehicleDto(id, "KDA $id", 4, status, onTheRoad)

    private fun route(vehicleId: String, vararg pickupIds: String) = DispatcherRouteDto(
        routeId = "route-$vehicleId",
        vehicleId = vehicleId,
        vehiclePlate = "KDA $vehicleId",
        totalDistanceKm = 30.0,
        plannedDeparture = t0.minusSeconds(5400),
        plannedArrival = t0.minusSeconds(1800),
        nodes = pickupIds.mapIndexed { i, id -> PlannedNodeDto(id, i + 1, t0.minusSeconds(4800)) }
    )

    /** One day held in memory. pickups() answers in pages of two, to exercise paging. */
    private class FakeDispatcherApi(
        var pickups: List<DispatcherPickupDto>,
        var vans: List<DispatcherVehicleDto>,
        var routes: List<DispatcherRouteDto>
    ) : DispatcherApi {
        val reportTimes = mutableListOf<Pair<String, Instant>>()
        val statuses = mutableListOf<Pair<String, VehicleStatusDto>>()

        override suspend fun pickups(
            date: LocalDate?,
            cursor: String?,
            limit: Int?
        ): Response<DispatcherPickupPageDto> {
            val from = cursor?.toInt() ?: 0
            val next = if (from + 2 < pickups.size) "${from + 2}" else null
            return Response.success(DispatcherPickupPageDto(pickups.drop(from).take(2), next))
        }

        override suspend fun vehicles(cursor: String?, limit: Int?) =
            Response.success(DispatcherVehiclePageDto(vans, null))

        override suspend fun routes(date: LocalDate?, cursor: String?, limit: Int?) =
            Response.success(DispatcherRoutePageDto(routes, null))

        override suspend fun setReportTime(
            pickupId: String,
            update: PickupReportTimeUpdateDto
        ): Response<DispatcherPickupDto> {
            reportTimes += pickupId to update.reportTime
            return Response.success(pickups.first { it.id == pickupId })
        }

        override suspend fun setVehicleStatus(
            vehicleId: String,
            update: VehicleStatusUpdateDto
        ): Response<DispatcherVehicleDto> {
            statuses += vehicleId to update.status
            vans = vans.map { if (it.id == vehicleId) it.copy(status = update.status) else it }
            return Response.success(vans.first { it.id == vehicleId })
        }
    }

    /** Every job completes on its first poll with one route. */
    private class FakeJobsApi : OptimisationJobsApi {
        val created = mutableListOf<OptimisationJobCreateDto>()

        override suspend fun createJob(idempotencyKey: String, body: OptimisationJobCreateDto) =
            Response.success(OptimisationJobAcceptedDto("job-${created.size}")).also {
                created += body
            }

        override suspend fun getJob(jobId: String): Response<OptimisationJobResultDto> =
            Response.success(
                OptimisationJobResultDto(jobId, OptimizationJobStatusDto.COMPLETED)
            )
    }

    private val api = FakeDispatcherApi(
        pickups = listOf(
            pickup("p1", PickupRequestStatusDto.ASSIGNED),
            pickup("p2", PickupRequestStatusDto.PICKED_UP),
            pickup("p3", PickupRequestStatusDto.ASSIGNED),
            pickup("p4", PickupRequestStatusDto.PENDING),
            pickup("p5", PickupRequestStatusDto.ASSIGNED)
        ),
        vans = listOf(
            van("v1", VehicleStatusDto.IN_SERVICE),
            van("v2", VehicleStatusDto.AVAILABLE),
            van("v3", VehicleStatusDto.AVAILABLE, onTheRoad = true),
            van("v4", VehicleStatusDto.BROKEN_DOWN)
        ),
        routes = listOf(route("v1", "p1", "p2", "p3"), route("v3", "p5"))
    )
    private val jobs = FakeJobsApi()

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun board() = DayBoard(api.pickups, api.vans, api.routes)

    @Test
    fun plannableVans_leaveOutBrokenDownAndOnTheRoad() {
        assertEquals(listOf("v1", "v2"), plannableVans(board()))
    }

    @Test
    fun aFirstPlan_takesOnlyPendingPickups() {
        assertEquals(listOf("p4"), unplannedPickups(board()))
    }

    @Test
    fun aBreakdown_strandsTheVansUncollectedPickups() {
        assertEquals(listOf("p1", "p3"), strandedPickups(board(), "v1"))
    }

    @Test
    fun breakdownThenReplan_sendsTheStrandedPickupsAndTheFreeVans() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()
        // Five pickups over three pages.
        assertEquals(5, viewModel.state.value.board?.pickups?.size)

        viewModel.markBrokenDown(api.vans.first { it.id == "v1" })
        advanceUntilIdle()

        assertEquals(listOf("v1" to VehicleStatusDto.BROKEN_DOWN), api.statuses)
        val replan = viewModel.state.value.replan!!
        assertEquals(R.string.dispatch_replan_breakdown, replan.label)
        assertEquals("KDA v1", replan.subject)

        viewModel.replan()
        advanceUntilIdle()

        assertEquals(
            OptimisationJobCreateDto(
                OptimizationTriggerTypeDto.VEHICLE_BREAKDOWN,
                listOf("p1", "p3"),
                listOf("v2")
            ),
            jobs.created.single()
        )
        assertEquals(null, viewModel.state.value.replan)
        assertEquals(JobUi.Done(0, 0, 0), viewModel.state.value.job)
    }

    @Test
    fun flightDelayThenReplan_sendsThatPickupWithAFlightDelayTrigger() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()
        val later = t0.plusSeconds(7200)

        viewModel.delayFlight(api.pickups.first { it.id == "p3" }, later)
        advanceUntilIdle()
        viewModel.replan()
        advanceUntilIdle()

        assertEquals(listOf("p3" to later), api.reportTimes)
        assertEquals(
            OptimisationJobCreateDto(
                OptimizationTriggerTypeDto.FLIGHT_DELAY,
                listOf("p3"),
                listOf("v1", "v2")
            ),
            jobs.created.single()
        )
    }

    @Test
    fun runOptimisation_plansThePendingPickups() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.runOptimisation()
        advanceUntilIdle()

        assertEquals(OptimizationTriggerTypeDto.SCHEDULED, jobs.created.single().triggerType)
        assertEquals(listOf("p4"), jobs.created.single().pickupRequestIds)
    }
}
