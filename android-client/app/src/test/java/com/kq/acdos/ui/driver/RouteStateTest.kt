package com.kq.acdos.ui.driver

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.DriverRouteDao
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.local.inMemoryDatabase
import java.time.Instant
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** What the Route tab shows for what is in Room. */
@RunWith(RobolectricTestRunner::class)
class RouteStateTest {
    private lateinit var db: AcdosDatabase
    private lateinit var dao: DriverRouteDao
    private val t0 = Instant.parse("2026-10-30T03:30:00Z")

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        dao = db.driverRouteDao()
    }

    @After
    fun tearDown() = db.close()

    private fun route(id: String, plate: String) = RouteEntity(id, plate, t0)

    private fun stop(node: String, route: String, seq: Int, eta: Instant? = null) =
        RouteStopEntity(
            routeNodeId = node,
            routeId = route,
            seqOrder = seq,
            crewName = "Crew $node",
            zoneLabel = if (seq == 1) "Westlands, Nairobi" else null,
            scheduledPickup = t0.plusSeconds(600L * seq),
            eta = eta,
            pickupLat = -1.2675,
            pickupLon = 36.81202
        )

    @Test
    fun noCachedRoute_isNoRoute() = runTest {
        assertEquals(RouteUiState.NoRoute, routeState(dao).first())
    }

    @Test
    fun stops_comeInRouteOrderWithPlateAndUpdateTime() = runTest {
        dao.saveActiveRoute(
            route("r1", "KDA 123A"),
            listOf(stop("n3", "r1", 3), stop("n1", "r1", 1), stop("n2", "r1", 2))
        )

        val state = routeState(dao).first() as RouteUiState.Route

        assertEquals("KDA 123A", state.plate)
        assertEquals(t0, state.updatedAt)
        assertEquals(listOf(1, 2, 3), state.stops.map { it.number })
        assertEquals(listOf("n1", "n2", "n3"), state.stops.map { it.routeNodeId })
        assertEquals("Westlands, Nairobi", state.stops[0].zoneLabel)
        assertEquals(null, state.stops[1].zoneLabel)
    }

    @Test
    fun pickupTime_isTheEtaWhenThereIsOneElseTheScheduledTime() = runTest {
        val eta = t0.plusSeconds(900)
        dao.saveActiveRoute(
            route("r1", "KDA 123A"),
            listOf(stop("n1", "r1", 1, eta = eta), stop("n2", "r1", 2))
        )

        val stops = (routeState(dao).first() as RouteUiState.Route).stops

        assertEquals(eta, stops[0].pickupTime)
        assertEquals(t0.plusSeconds(1200), stops[1].pickupTime)
    }

    @Test
    fun routeReplacedWhileOpen_switchesToTheNewRoutesStops() = runTest {
        dao.saveActiveRoute(route("r1", "KDA 111A"), listOf(stop("old", "r1", 1)))
        val firstShown = CompletableDeferred<Unit>()

        val shown = async {
            routeState(dao)
                .filterIsInstance<RouteUiState.Route>()
                .onEach { firstShown.complete(Unit) }
                .map { it.plate to it.stops.map(StopRow::routeNodeId) }
                .take(2)
                .toList()
        }
        firstShown.await()
        dao.saveActiveRoute(route("r2", "KDA 222B"), listOf(stop("new", "r2", 1)))

        assertEquals(
            listOf("KDA 111A" to listOf("old"), "KDA 222B" to listOf("new")),
            shown.await()
        )
    }

    @Test
    fun routePurged_isNoRouteAgain() = runTest {
        dao.saveActiveRoute(route("r1", "KDA 123A"), listOf(stop("n1", "r1", 1)))
        dao.purgeRoute("r1")

        assertEquals(RouteUiState.NoRoute, routeState(dao).first())
    }
}
