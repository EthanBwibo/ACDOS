package com.kq.acdos.data.local

import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** The route_stop purge rules: crew locations leave the phone with their route. */
@RunWith(RobolectricTestRunner::class)
class DriverRouteDaoTest {
    private lateinit var db: AcdosDatabase
    private lateinit var dao: DriverRouteDao

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        dao = db.driverRouteDao()
    }

    @After
    fun tearDown() = db.close()

    private val t0 = Instant.parse("2026-11-01T03:00:00Z")

    private fun route(id: String) = RouteEntity(id, "KDA 001A", t0)

    private fun stop(node: String, route: String, seq: Int) = RouteStopEntity(
        routeNodeId = node,
        routeId = route,
        seqOrder = seq,
        crewName = "Crew $node",
        zoneLabel = "Westlands, Nairobi",
        scheduledPickup = t0.plusSeconds(600L * seq),
        eta = null,
        pickupLat = -1.2675,
        pickupLon = 36.81202
    )

    @Test
    fun stops_comeBackInRouteOrder() = runTest {
        dao.saveActiveRoute(route("r1"), listOf(stop("n3", "r1", 3), stop("n1", "r1", 1)))

        val order = dao.observeStops("r1").first().map { it.routeNodeId }

        assertEquals(listOf("n1", "n3"), order)
    }

    @Test
    fun replacedRoute_takesItsStopsWithIt() = runTest {
        dao.saveActiveRoute(route("old"), listOf(stop("a", "old", 1), stop("b", "old", 2)))

        dao.saveActiveRoute(route("new"), listOf(stop("c", "new", 1)))

        assertEquals("new", dao.observeRoute().first()?.id)
        assertTrue(dao.observeStops("old").first().isEmpty())
        assertEquals(listOf("c"), dao.observeStops("new").first().map { it.routeNodeId })
    }

    @Test
    fun completedRoute_purgesRouteAndStops() = runTest {
        dao.saveActiveRoute(route("r1"), listOf(stop("a", "r1", 1), stop("b", "r1", 2)))

        dao.purgeRoute("r1")

        assertNull(dao.observeRoute().first())
        assertTrue(dao.observeStops("r1").first().isEmpty())
    }

    @Test
    fun purgingAnotherRoute_leavesTheActiveOne() = runTest {
        dao.saveActiveRoute(route("r1"), listOf(stop("a", "r1", 1)))

        dao.purgeRoute("some-other-route")

        assertEquals(1, dao.observeStops("r1").first().size)
    }
}
