package com.kq.acdos.data

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.local.RouteWithStops
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.DriverRouteDto
import com.kq.acdos.data.remote.DriverRouteResponseDto
import com.kq.acdos.data.remote.DriverStopDto
import com.kq.acdos.data.remote.RouteStatusDto
import com.squareup.moshi.JsonDataException
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

/** What a refresh does to the Room cache for each answer from GET /drivers/me/route. */
@RunWith(RobolectricTestRunner::class)
class DriverRouteRepositoryTest {
    private val t0 = Instant.parse("2026-10-30T03:00:00Z")
    private var now = t0
    private val driverId = "driver-1"

    private lateinit var db: AcdosDatabase
    private val api = FakeMeApi()
    private lateinit var repository: DriverRouteRepository

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        repository = DriverRouteRepository(api, db.driverRouteDao(), clock = { now })
    }

    @After
    fun tearDown() = db.close()

    private fun stop(node: String, seq: Int, eta: Instant? = null) = DriverStopDto(
        routeNodeId = node,
        seqOrder = seq,
        crewName = "Crew $node",
        zoneLabel = if (seq == 1) "Westlands, Nairobi" else null,
        scheduledPickup = t0.plusSeconds(600L * seq),
        eta = eta,
        lat = -1.2675,
        lon = 36.81202
    )

    private fun route(id: String, status: RouteStatusDto = RouteStatusDto.ACTIVE) =
        DriverRouteDto(id, status, "KDA $id", listOf(stop("$id-n1", 1), stop("$id-n2", 2)))

    private fun answer(route: DriverRouteDto?) {
        api.next = { Response.success(DriverRouteResponseDto(route)) }
    }

    private fun answerError(status: Int, code: String) {
        val body = """{"code":"$code","detail":"x"}"""
        api.next = { Response.error(status, body.toResponseBody("application/json".toMediaType())) }
    }

    private suspend fun cached(): RouteWithStops? =
        db.driverRouteDao().observeRouteWithStops().first()

    /** A cached route as #28 left it, and one unsynced pickup event for its first stop. */
    private suspend fun cacheRouteWithPendingEvent(key: String = "key-1") {
        db.driverRouteDao().saveActiveRoute(
            RouteEntity("old", "KDA old", t0),
            listOf(
                RouteStopEntity("old-n1", "old", 1, "Crew old-n1", null, t0, null, -1.2, 36.8)
            )
        )
        db.pendingPickupEventDao().insert(
            PendingPickupEventEntity(
                idempotencyKey = key,
                driverId = driverId,
                routeNodeId = "old-n1",
                eventType = PickupEventType.PICKUP_CONFIRMED,
                exceptionType = null,
                confirmedAt = t0
            )
        )
    }

    private suspend fun pendingKeys() =
        db.pendingPickupEventDao().pending(driverId).map { it.idempotencyKey }

    @Test
    fun activeRoute_isSavedWithEveryField() = runTest {
        val eta = t0.plusSeconds(700)
        answer(
            DriverRouteDto(
                "r1",
                RouteStatusDto.ACTIVE,
                "KDA 123A",
                listOf(stop("n1", 1, eta = eta), stop("n2", 2))
            )
        )
        now = t0.plusSeconds(42)

        assertEquals(RefreshResult.UPDATED, repository.refresh(force = true))

        val saved = cached()!!
        assertEquals(RouteEntity("r1", "KDA 123A", t0.plusSeconds(42)), saved.route)
        assertEquals(
            setOf(
                RouteStopEntity(
                    "n1", "r1", 1, "Crew n1", "Westlands, Nairobi", t0.plusSeconds(600), eta,
                    -1.2675, 36.81202
                ),
                RouteStopEntity(
                    "n2", "r1", 2, "Crew n2", null, t0.plusSeconds(1200), null, -1.2675, 36.81202
                )
            ),
            saved.stops.toSet()
        )
    }

    @Test
    fun newRoute_replacesTheCachedOne() = runTest {
        cacheRouteWithPendingEvent()
        answer(route("r2"))

        assertEquals(RefreshResult.UPDATED, repository.refresh(force = true))

        val saved = cached()!!
        assertEquals("r2", saved.route.id)
        assertEquals(setOf("r2-n1", "r2-n2"), saved.stops.map { it.routeNodeId }.toSet())
        assertEquals(listOf("key-1"), pendingKeys())
    }

    @Test
    fun noRouteCompletedOrSuperseded_purgeTheCacheAndKeepPendingEvents() = runTest {
        val answers = listOf(
            null,
            route("old", RouteStatusDto.COMPLETED),
            route("old", RouteStatusDto.SUPERSEDED)
        )
        for ((i, route) in answers.withIndex()) {
            cacheRouteWithPendingEvent(key = "key-$i")
            answer(route)

            assertEquals("$route", RefreshResult.NO_ROUTE, repository.refresh(force = true))

            assertNull("$route", cached())
            assertEquals("$route", listOf("key-$i"), pendingKeys())
            // Uploaded, so the next case starts with one pending event again.
            db.pendingPickupEventDao().markSynced("key-$i", t0)
        }
    }

    @Test
    fun supersededRoute_keepsAPendingEventForOneOfItsStopsForTheUploader() = runTest {
        cacheRouteWithPendingEvent()
        answer(route("old", RouteStatusDto.SUPERSEDED))

        repository.refresh(force = true)

        // The stop is gone, the event isn't: #29's uploader reads pending().
        assertNull(cached())
        val event = db.pendingPickupEventDao().pending(driverId).single()
        assertEquals("old-n1", event.routeNodeId)
        assertNull(event.syncedAt)
        assertNull(event.conflict)
    }

    @Test
    fun failures_keepTheCacheAndSayWhy() = runTest {
        val cases = listOf<Pair<() -> Unit, RefreshResult>>(
            { api.next = { throw IOException("offline") } } to RefreshResult.OFFLINE,
            { answerError(401, "unauthorized") } to RefreshResult.SIGN_IN_AGAIN,
            { answerError(403, "forbidden") } to RefreshResult.NOT_ALLOWED,
            { answerError(503, "unavailable") } to RefreshResult.FAILED,
            { api.next = { throw JsonDataException("unreadable 200") } } to RefreshResult.FAILED
        )
        cacheRouteWithPendingEvent()
        val before = cached()

        for ((setUp, expected) in cases) {
            setUp()

            assertEquals(expected, repository.refresh(force = true))

            assertEquals("$expected", before, cached())
            assertEquals("$expected", listOf("key-1"), pendingKeys())
        }
    }

    @Test
    fun throttle_skipsAnUnforcedRefreshWithin60Seconds() = runTest {
        answer(route("r1"))
        repository.refresh(force = false)

        now = t0.plusSeconds(59)
        assertEquals(RefreshResult.THROTTLED, repository.refresh(force = false))
        assertEquals(1, api.calls)

        assertEquals(RefreshResult.UPDATED, repository.refresh(force = true))
        assertEquals(2, api.calls)

        // The forced refresh at 59 s restarted the window.
        now = t0.plusSeconds(59 + 60)
        assertEquals(RefreshResult.UPDATED, repository.refresh(force = false))
        assertEquals(3, api.calls)
    }

    @Test
    fun throttle_countsFailedAttemptsToo() = runTest {
        api.next = { throw IOException("offline") }
        assertEquals(RefreshResult.OFFLINE, repository.refresh(force = false))

        now = t0.plusSeconds(30)
        answer(route("r1"))

        assertEquals(RefreshResult.THROTTLED, repository.refresh(force = false))
        assertEquals(1, api.calls)
    }
}
