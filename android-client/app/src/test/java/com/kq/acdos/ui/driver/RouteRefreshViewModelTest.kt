package com.kq.acdos.ui.driver

import com.kq.acdos.R
import com.kq.acdos.data.DriverRouteRepository
import com.kq.acdos.data.FakeMeApi
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.DriverRouteResponseDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

/** What the empty Route tab says after each kind of refresh. */
@RunWith(RobolectricTestRunner::class)
class RouteRefreshViewModelTest {
    private val t0 = Instant.parse("2026-10-30T03:00:00Z")
    private var now = t0

    private lateinit var db: AcdosDatabase
    private val api = FakeMeApi()
    private lateinit var viewModel: RouteRefreshViewModel

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        db = inMemoryDatabase()
        val repository = DriverRouteRepository(api, db.driverRouteDao(), clock = { now })
        viewModel = RouteRefreshViewModel(repository)
    }

    @After
    fun tearDown() {
        db.close()
        Dispatchers.resetMain()
    }

    private fun answerOffline() {
        api.next = { throw IOException("offline") }
    }

    private fun answerNoRoute() {
        api.next = { Response.success(DriverRouteResponseDto(null)) }
    }

    private fun emptyText() = emptyRouteMessage(viewModel.lastFailure.value)

    @Test
    fun startOfflineWithNothingCached_saysCouldntLoadNotNoRoute() {
        answerOffline()

        viewModel.refreshOnStart(first = true)

        assertEquals(R.string.route_load_failed, emptyText())
    }

    @Test
    fun pullFailing_saysCouldntLoadToo() {
        answerOffline()

        viewModel.refreshByPull()

        assertEquals(R.string.route_load_failed, emptyText())
    }

    @Test
    fun signInAgain_isSaidInPlaceOfNoRoute() {
        val body = """{"code":"unauthorized","detail":"x"}"""
        api.next = { Response.error(401, body.toResponseBody("application/json".toMediaType())) }

        viewModel.refreshOnStart(first = true)

        assertEquals(R.string.route_refresh_sign_in_again, emptyText())
    }

    @Test
    fun throttledStartAfterAFailure_keepsSayingCouldntLoad() {
        answerOffline()
        viewModel.refreshOnStart(first = true)

        now = t0.plusSeconds(30)
        viewModel.refreshOnStart(first = false)

        assertEquals(1, api.calls)
        assertEquals(R.string.route_load_failed, emptyText())
    }

    @Test
    fun pullAfterAFailureThatFindsNoRoute_saysNoRouteAssigned() = runTest {
        answerOffline()
        viewModel.refreshOnStart(first = true)
        answerNoRoute()

        viewModel.refreshByPull()

        // The purge runs on Room's executor, so wait for the result.
        viewModel.lastFailure.first { it == null }
        assertEquals(R.string.route_none, emptyText())
    }
}
