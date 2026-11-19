package com.kq.acdos.ui.dispatcher

import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.planSummary
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
import com.kq.acdos.data.remote.RosterImportResultDto
import com.kq.acdos.data.remote.VehicleStatusDto
import com.kq.acdos.data.remote.VehicleStatusUpdateDto
import com.kq.acdos.data.strandedPickups
import com.kq.acdos.data.unplannedPickups
import com.kq.acdos.data.vanChoices
import java.io.IOException
import java.time.Instant
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.Response

/** The dispatcher's main path against fake APIs: plan, disrupt, re-plan. */
class DispatcherViewModelTest {
    private val day = LocalDate.parse("2026-11-03")
    private val t0 = Instant.parse("2026-11-03T05:30:00Z")

    private fun pickup(id: String, status: PickupRequestStatusDto) = DispatcherPickupDto(
        id,
        "Crew $id",
        "Kilimani, Nairobi",
        -1.3,
        36.8,
        t0,
        status,
        needsAck = false,
        acknowledgedAt = null
    )

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
        var failLoads = false

        override suspend fun pickups(
            date: LocalDate?,
            cursor: String?,
            limit: Int?
        ): Response<DispatcherPickupPageDto> {
            if (failLoads) throw IOException("no signal")
            val from = cursor?.toInt() ?: 0
            val next = if (from + 2 < pickups.size) "${from + 2}" else null
            return Response.success(DispatcherPickupPageDto(pickups.drop(from).take(2), next))
        }

        override suspend fun vehicles(cursor: String?, limit: Int?) =
            Response.success(DispatcherVehiclePageDto(vans, null))

        override suspend fun crew(query: String?, cursor: String?, limit: Int?) =
            error("not used here")

        override suspend fun nearestZone(lat: Double, lon: Double) = error("not used here")

        override suspend fun addPickup(
            idempotencyKey: String,
            body: com.kq.acdos.data.remote.PickupRequestCreateDto
        ) = error("not used here")

        override suspend fun setHome(
            crewMemberId: String,
            body: com.kq.acdos.data.remote.LatLonDto
        ) = error("not used here")

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

        override suspend fun importRoster(
            file: MultipartBody.Part,
            dryRun: Boolean,
            idempotencyKey: String?
        ): Response<RosterImportResultDto> = error("not used here")
    }

    /** Every job completes on its first poll with one route, unless [refusal] is set. */
    private class FakeJobsApi : OptimisationJobsApi {
        val created = mutableListOf<OptimisationJobCreateDto>()
        var status = OptimizationJobStatusDto.COMPLETED

        /** A 422 body to answer createJob with instead of accepting the job. */
        var refusal: String? = null

        override suspend fun createJob(
            idempotencyKey: String,
            body: OptimisationJobCreateDto
        ): Response<OptimisationJobAcceptedDto> {
            refusal?.let {
                return Response.error(422, it.toResponseBody("application/json".toMediaType()))
            }
            created += body
            return Response.success(OptimisationJobAcceptedDto("job-${created.size - 1}"))
        }

        override suspend fun getJob(jobId: String): Response<OptimisationJobResultDto> =
            Response.success(OptimisationJobResultDto(jobId, status))
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
    fun plannableVans_leaveOutUnavailableVans() {
        // The demo's test vans (#198): the backend refuses them, so the picker never offers them.
        val withTestVan = DayBoard(
            api.pickups,
            api.vans + van("v5", VehicleStatusDto.UNAVAILABLE),
            api.routes
        )

        assertEquals(listOf("v1", "v2"), plannableVans(withTestVan))
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
    fun aFailedLoad_saysWhy_keepsTheBoard_andClearsOnceALoadWorks() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()
        val board = viewModel.state.value.board

        api.failLoads = true
        viewModel.load()
        advanceUntilIdle()

        assertEquals(R.string.dispatch_load_offline, viewModel.state.value.loadFailure?.text)
        assertEquals(board, viewModel.state.value.board)

        api.failLoads = false
        viewModel.load()
        advanceUntilIdle()

        assertNull(viewModel.state.value.loadFailure)
    }

    @Test
    fun aFailedReplanJob_bringsTheAlertBack() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        jobs.status = OptimizationJobStatusDto.FAILED
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.markBrokenDown(api.vans.first { it.id == "v1" })
        advanceUntilIdle()
        val alert = viewModel.state.value.replan
        viewModel.replan()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.job is JobUi.Failed)
        assertEquals(alert, viewModel.state.value.replan)
    }

    @Test
    fun discardingAReplan_dropsTheAlertAndStartsNoJob() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.markBrokenDown(api.vans.first { it.id == "v1" })
        advanceUntilIdle()
        viewModel.discardReplan()
        advanceUntilIdle()

        assertNull(viewModel.state.value.replan)
        assertTrue(jobs.created.isEmpty())
    }

    @Test
    fun aJob_remembersThePlanItStartedFrom() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()
        val before = planSummary(viewModel.state.value.board!!)

        viewModel.nextWave()
        viewModel.runOptimisation()
        advanceUntilIdle()

        assertEquals(before, viewModel.state.value.before)
    }

    @Test
    fun runOptimisation_plansThePendingPickups() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.nextWave()
        viewModel.runOptimisation()
        advanceUntilIdle()

        assertEquals(OptimizationTriggerTypeDto.SCHEDULED, jobs.created.single().triggerType)
        assertEquals(listOf("p4"), jobs.created.single().pickupRequestIds)
    }

    /** p4 at 05:30 is pending; p6 and p7 are a later wave, more than an hour after it. */
    private fun twoWaves() {
        api.pickups = api.pickups + listOf(
            pickup(
                "p6",
                PickupRequestStatusDto.PENDING
            ).copy(reportTime = t0.plusSeconds(3 * 3600)),
            pickup("p7", PickupRequestStatusDto.PENDING).copy(reportTime = t0.plusSeconds(4 * 3600))
        )
    }

    @Test
    fun noWave_isSelectedByDefault_andStartPlansNothing() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        twoWaves()
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        assertNull(selectedWave(viewModel.state.value))
        viewModel.runOptimisation()
        advanceUntilIdle()

        assertTrue(jobs.created.isEmpty())
        assertEquals(DispatcherMessage(R.string.dispatch_pick_a_wave), viewModel.messages.first())
    }

    @Test
    fun nextWave_selectsTheEarliest_andStartPlansOnlyThatWave() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        twoWaves()
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.nextWave()
        assertEquals(listOf("p4"), selectedWave(viewModel.state.value)?.pickupIds)
        viewModel.runOptimisation()
        advanceUntilIdle()

        assertEquals(listOf("p4"), jobs.created.single().pickupRequestIds)
    }

    @Test
    fun aPickedWave_isPlanned() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        twoWaves()
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.selectWave(t0.plusSeconds(3 * 3600))
        viewModel.runOptimisation()
        advanceUntilIdle()

        assertEquals(listOf("p6", "p7"), jobs.created.single().pickupRequestIds)
    }

    @Test
    fun planningWindowTooWide_showsTheServersMessage() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val detail = "these pickups' report times span 18 h 35 min, more than the 4 h " +
            "one plan may cover: plan each wave separately"
        jobs.refusal = """{"code": "planning_window_too_wide", "detail": "$detail"}"""
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        viewModel.nextWave()
        viewModel.runOptimisation()
        advanceUntilIdle()

        assertEquals(
            DispatcherMessage(R.string.dispatch_failed, detail),
            viewModel.messages.first()
        )
    }

    @Test
    fun aVanAlreadyOnAWave_tickedDeliberately_goesIntoTheJob() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()
        // v1 already has a route today, so the picker starts it unticked (#272).
        val v1 = vanChoices(viewModel.state.value.board!!).first { it.vehicle.id == "v1" }
        assertEquals(false, v1.tickedByDefault)

        viewModel.nextWave()
        viewModel.runOptimisation(listOf("v1"))
        advanceUntilIdle()

        assertEquals(listOf("v1"), jobs.created.single().vehicleIds)
    }

    @Test
    fun ackLabel_followsTheNotice() {
        val none = pickup("p1", PickupRequestStatusDto.ASSIGNED)
        val pending = none.copy(needsAck = true)
        val done = none.copy(acknowledgedAt = t0)

        assertEquals(null, ackLabel(none))
        assertEquals(R.string.dispatch_awaiting_ack, ackLabel(pending))
        assertEquals(R.string.dispatch_acknowledged, ackLabel(done))
    }

    @Test
    fun aVanUntickedInThePicker_isLeftOutOfTheJob() = runTest {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val viewModel = DispatcherViewModel(DispatchRepository(api, jobs), day)
        advanceUntilIdle()

        // v2 unticked; v4 is broken down, so it never goes in even if asked for.
        viewModel.nextWave()
        viewModel.runOptimisation(listOf("v1", "v4"))
        advanceUntilIdle()

        assertEquals(listOf("v1"), jobs.created.single().vehicleIds)
    }
}
