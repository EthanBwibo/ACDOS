package com.kq.acdos.auth

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.local.ScheduleChangeNoticeEntity
import com.kq.acdos.data.local.inMemoryDatabase
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

/**
 * Sign-out and a server-ended session, with the real Room database: the user's
 * data is gone and pickup events not yet uploaded are still there.
 */
@RunWith(RobolectricTestRunner::class)
class SessionEndClearsUserDataTest {
    private lateinit var db: AcdosDatabase
    private lateinit var router: SessionRouter
    private val t0 = Instant.parse("2026-11-01T03:00:00Z")

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        router = SessionRouter(FakeAuth(), FakeCache(), db.userDataDao())
    }

    @After
    fun tearDown() = db.close()

    private fun event(key: String) = PendingPickupEventEntity(
        idempotencyKey = key,
        driverId = USER,
        routeNodeId = "n-$key",
        eventType = PickupEventType.PICKUP_CONFIRMED,
        exceptionType = null,
        confirmedAt = t0
    )

    /** A driver's route and outbox, and a crew member's pickup, notices and presets. */
    private suspend fun seed() {
        db.driverRouteDao().saveActiveRoute(
            RouteEntity("r1", "KDA 001A", t0),
            listOf(RouteStopEntity("n1", "r1", 1, "Crew C", -1.2675, 36.812022, t0, t0))
        )
        val crew = db.crewDao()
        crew.savePickup(CrewPickupEntity("p1", t0, t0, "KDA 001A", t0))
        crew.upsertNotices(
            listOf(ScheduleChangeNoticeEntity("x1", "p1", "flight_delay", t0, t0, t0, null))
        )
        crew.replacePresets(listOf(PresetMessageEntity("m1", "running_late", "Running late")))
        val outbox = db.pendingPickupEventDao()
        outbox.insert(event("unsynced"))
        outbox.insert(event("uploaded"))
        outbox.markSynced("uploaded", t0)
    }

    private suspend fun assertOnlyUnsyncedEventsLeft() {
        assertNull(db.driverRouteDao().observeRoute().first())
        assertTrue(db.driverRouteDao().observeStops("r1").first().isEmpty())
        val crew = db.crewDao()
        assertNull(crew.observePickup().first())
        assertTrue(crew.observeNotices().first().isEmpty())
        assertTrue(crew.observePresets().first().isEmpty())
        val left = db.query("SELECT idempotency_key FROM pickup_event_outbox", null).use {
            buildList { while (it.moveToNext()) add(it.getString(0)) }
        }
        assertEquals(listOf("unsynced"), left)
    }

    @Test
    fun signOut_clearsUserDataAndKeepsUnsyncedEvents() = runTest {
        seed()

        router.signOut()

        assertOnlyUnsyncedEventsLeft()
    }

    @Test
    fun sessionEndedByServer_clearsUserDataAndKeepsUnsyncedEvents() = runTest {
        seed()

        router.onSessionEnded()

        assertOnlyUnsyncedEventsLeft()
    }
}
