package com.kq.acdos.ui.driver

import com.kq.acdos.R
import com.kq.acdos.data.DriverScheduleRepository
import com.kq.acdos.data.FakeMeApi
import com.kq.acdos.data.RefreshResult
import com.kq.acdos.data.ScheduleResult
import com.kq.acdos.data.remote.RouteStatusDto
import com.kq.acdos.data.remote.RouteSummaryDto
import com.kq.acdos.data.remote.RouteSummaryPageDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response

@OptIn(ExperimentalCoroutinesApi::class)
class ScheduleTest {
    // 10:00 in Nairobi on Thursday 5 November.
    private val now = Instant.parse("2026-11-05T07:00:00Z")
    private val api = FakeMeApi()

    private fun route(id: String, at: String) = RouteSummaryDto(
        routeId = id,
        status = RouteStatusDto.ACTIVE,
        vehiclePlate = "KDH $id",
        firstPickup = Instant.parse(at),
        stopCount = 5,
        totalDistanceKm = 40.0
    )

    private fun page(vararg items: RouteSummaryDto, next: String? = null) =
        Response.success(RouteSummaryPageDto(items.toList(), next))

    @Before
    fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun `routes split on the Nairobi date, not the UTC date`() {
        // 22:00 UTC on the 5th is already 01:00 on the 6th in Nairobi.
        val sections = scheduleSections(
            listOf(route("late", "2026-11-05T22:00:00Z"), route("early", "2026-11-05T03:00:00Z")),
            now
        )

        assertEquals(listOf("KDH early"), sections.today.map { it.plate })
        assertEquals(listOf("KDH late"), sections.upcoming.map { it.plate })
    }

    @Test
    fun `each section is in time order`() {
        val sections = scheduleSections(
            listOf(route("c", "2026-11-09T02:00:00Z"), route("b", "2026-11-07T02:00:00Z")),
            now
        )

        assertEquals(listOf("KDH b", "KDH c"), sections.upcoming.map { it.plate })
    }

    @Test
    fun `a route that has started says so and a later one today does not`() {
        val sections = scheduleSections(
            listOf(route("on", "2026-11-05T06:00:00Z"), route("off", "2026-11-05T09:00:00Z")),
            now
        )

        assertTrue(sections.today[0].started)
        assertFalse(sections.today[1].started)
    }

    @Test
    fun `a route left active from an earlier day is under Today with its date`() {
        val routes = listOf(route("old", "2026-11-03T03:00:00Z"))

        val stale = scheduleSections(routes, now).today.single()

        assertTrue(stale.showDay)
        assertTrue(stale.started)
    }

    @Test
    fun `today's rows leave the day to the section heading`() {
        val row = scheduleSections(listOf(route("a", "2026-11-05T09:00:00Z")), now).today.single()

        assertFalse(row.showDay)
    }

    @Test
    fun `the repository follows every page`() = runTest {
        val cursors = mutableListOf<String?>()
        api.nextRoutes = { cursor ->
            cursors += cursor
            if (cursor == null) {
                page(route("a", "2026-11-06T03:00:00Z"), next = "more")
            } else {
                page(route("b", "2026-11-07T03:00:00Z"))
            }
        }

        val result = DriverScheduleRepository(api).routes() as ScheduleResult.Loaded

        assertEquals(listOf(null, "more"), cursors)
        assertEquals(listOf("a", "b"), result.routes.map { it.routeId })
    }

    @Test
    fun `no connection is a failure, not an empty schedule`() = runTest {
        api.nextRoutes = { throw IOException("no signal") }

        val result = DriverScheduleRepository(api).routes()

        assertEquals(ScheduleResult.Failed(RefreshResult.OFFLINE), result)
    }

    @Test
    fun `a failed refresh keeps the list on screen and shows the error`() = runTest {
        var fail = false
        api.nextRoutes = {
            if (fail) throw IOException("no signal")
            page(route("a", "2026-11-05T09:00:00Z"))
        }
        val viewModel = ScheduleViewModel(DriverScheduleRepository(api), clock = { now })

        viewModel.load()
        fail = true
        viewModel.load()

        val state = viewModel.state.value
        assertEquals(1, state.sections?.today?.size)
        assertEquals(R.string.schedule_load_failed, state.error)
        assertFalse(state.loading)
    }

    @Test
    fun `a good refresh clears the error`() = runTest {
        var fail = true
        api.nextRoutes = {
            if (fail) throw IOException("no signal")
            page()
        }
        val viewModel = ScheduleViewModel(DriverScheduleRepository(api), clock = { now })

        viewModel.loadIfNeeded()
        assertEquals(R.string.schedule_load_failed, viewModel.state.value.error)
        fail = false
        viewModel.loadIfNeeded()

        assertNull(viewModel.state.value.error)
        assertTrue(viewModel.state.value.sections!!.isEmpty)
    }

    @Test
    fun `opening the tab again doesn't refetch a loaded schedule`() = runTest {
        var calls = 0
        api.nextRoutes = {
            calls++
            page()
        }
        val viewModel = ScheduleViewModel(DriverScheduleRepository(api), clock = { now })

        viewModel.loadIfNeeded()
        viewModel.loadIfNeeded()

        assertEquals(1, calls)
    }

    @Test
    fun `a session problem says to sign in, not to pull again`() = runTest {
        api.nextRoutes = {
            val body = """{"code": "unauthorized", "detail": "expired"}"""
            Response.error(401, body.toResponseBody("application/json".toMediaType()))
        }
        val viewModel = ScheduleViewModel(DriverScheduleRepository(api), clock = { now })

        viewModel.load()

        assertEquals(R.string.route_refresh_sign_in_again, viewModel.state.value.error)
    }

    @Test
    fun `without an API the schedule is empty rather than loading forever`() {
        val viewModel = ScheduleViewModel(repository = null, clock = { now })

        viewModel.load()

        assertTrue(viewModel.state.value.sections!!.isEmpty)
        assertFalse(viewModel.state.value.loading)
    }
}
