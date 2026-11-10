package com.kq.acdos.ui.driver

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.DriverRouteDao
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.local.ServerStopStatus
import com.kq.acdos.data.local.inMemoryDatabase
import java.time.Instant
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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

    private fun route(id: String, plate: String) = RouteEntity(id, plate, t0.plusSeconds(3_600), t0)

    private fun stop(node: String, route: String, seq: Int, eta: Instant? = null) = RouteStopEntity(
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
        assertEquals(t0.plusSeconds(3_600), state.arriveBy)
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

    private fun event(
        node: String,
        exception: PickupExceptionType? = null,
        minute: Long = 0,
        synced: Boolean = false,
        conflict: String? = null
    ) = PendingPickupEventEntity(
        idempotencyKey = "$node-$minute",
        driverId = "d1",
        routeNodeId = node,
        eventType = if (exception == null) {
            PickupEventType.PICKUP_CONFIRMED
        } else {
            PickupEventType.EXCEPTION
        },
        exceptionType = exception,
        confirmedAt = t0.plusSeconds(60 * minute),
        syncedAt = if (synced) t0 else null,
        conflict = conflict
    )

    @Test
    fun recordedEvents_showOnTheirStops() = runTest {
        dao.saveActiveRoute(
            route("r1", "KDA 123A"),
            listOf(stop("n1", "r1", 1), stop("n2", "r1", 2), stop("n3", "r1", 3))
        )
        val events = listOf(
            event("n1"),
            event("n2", PickupExceptionType.TRAFFIC_DELAY, synced = true)
        )

        val stops = (routeState(dao, flowOf(events)).first() as RouteUiState.Route).stops

        assertEquals(
            StopProgress(PickupEventType.PICKUP_CONFIRMED, null, false, null, done = true),
            stops[0].progress
        )
        assertEquals(
            StopProgress(
                PickupEventType.EXCEPTION,
                PickupExceptionType.TRAFFIC_DELAY,
                sent = true,
                conflict = null,
                done = false
            ),
            stops[1].progress
        )
        assertNull(stops[2].progress)
    }

    @Test
    fun serverStatus_reachesTheStopsWithNoEventsOnThisPhone() = runTest {
        dao.saveActiveRoute(
            route("r1", "KDA 002T"),
            listOf(
                stop("n1", "r1", 1).copy(serverStatus = ServerStopStatus.PICKED_UP),
                stop("n2", "r1", 2)
            )
        )

        val stops = (routeState(dao).first() as RouteUiState.Route).stops

        assertEquals(true, stops[0].progress?.done)
        assertNull(stops[1].progress)
    }

    @Test
    fun stopProgress_showsTheLatestEventAndEndsOnlyOnAnAcceptedPickupOrNoShow() {
        val progress = stopProgress(
            listOf(
                event("delayed-then-picked", PickupExceptionType.TRAFFIC_DELAY, minute = 1),
                event("delayed-then-picked", minute = 2),
                event("no-show", PickupExceptionType.NO_SHOW),
                event("refused", conflict = "already_confirmed")
            )
        )

        val picked = progress.getValue("delayed-then-picked")
        assertEquals(PickupEventType.PICKUP_CONFIRMED, picked.type)
        assertEquals(true, picked.done)
        assertEquals(true, progress.getValue("no-show").done)
        assertEquals("already_confirmed", progress.getValue("refused").conflict)
        assertEquals(false, progress.getValue("refused").done)
    }
}
