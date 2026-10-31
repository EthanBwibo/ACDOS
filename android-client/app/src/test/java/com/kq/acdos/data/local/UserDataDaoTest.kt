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

/** Sign-out clears the user's data but keeps events that still have to be uploaded. */
@RunWith(RobolectricTestRunner::class)
class UserDataDaoTest {
    private lateinit var db: AcdosDatabase

    @Before
    fun setUp() {
        db = inMemoryDatabase()
    }

    @After
    fun tearDown() = db.close()

    private val t0 = Instant.parse("2026-11-01T03:00:00Z")

    private fun event(key: String) = PendingPickupEventEntity(
        idempotencyKey = key,
        driverId = DRIVER,
        routeNodeId = "n-$key",
        eventType = PickupEventType.PICKUP_CONFIRMED,
        exceptionType = null,
        confirmedAt = t0
    )

    @Test
    fun clearUserData_removesCachedDataAndKeepsUnsyncedEvents() = runTest {
        db.driverRouteDao().saveActiveRoute(
            RouteEntity("r1", "KDA 001A", t0),
            listOf(RouteStopEntity("n1", "r1", 1, "Crew C", null, t0, null, -1.2675, 36.81202))
        )
        val crew = db.crewDao()
        crew.savePickup(CrewPickupEntity("p1", t0, t0, "KDA 001A", t0))
        crew.upsertNotices(
            listOf(ScheduleChangeNoticeEntity("x1", "p1", "flight_delay", t0, t0, t0, null))
        )
        crew.replacePresets(listOf(PresetMessageEntity("m1", "running_late", "Running late")))
        val outbox = db.pendingPickupEventDao()
        outbox.insert(event("pending"))
        outbox.insert(event("conflicted"))
        outbox.insert(event("synced"))
        outbox.markConflict("conflicted", "stop_already_confirmed")
        outbox.markSynced("synced", t0)

        db.userDataDao().clearUserData()

        assertNull(db.driverRouteDao().observeRoute().first())
        assertTrue(db.driverRouteDao().observeStops("r1").first().isEmpty())
        assertNull(crew.observePickup().first())
        assertTrue(crew.observeNotices().first().isEmpty())
        assertTrue(crew.observePresets().first().isEmpty())
        assertEquals(listOf("pending"), outbox.pending(DRIVER).map { it.idempotencyKey })
        assertEquals(
            listOf("conflicted"),
            outbox.observeConflicts(DRIVER).first().map { it.idempotencyKey }
        )
    }

    private companion object {
        const val DRIVER = "00000000-0000-0000-0000-00000000000a"
    }
}
