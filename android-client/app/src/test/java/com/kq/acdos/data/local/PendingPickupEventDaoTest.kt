package com.kq.acdos.data.local

import android.database.sqlite.SQLiteConstraintException
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** The outbox SQL: what counts as pending, and the two ways an event leaves it. */
@RunWith(RobolectricTestRunner::class)
class PendingPickupEventDaoTest {
    private lateinit var db: AcdosDatabase
    private lateinit var dao: PendingPickupEventDao

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        dao = db.pendingPickupEventDao()
    }

    @After
    fun tearDown() = db.close()

    private val t0 = Instant.parse("2026-11-01T03:40:00Z")

    private fun event(key: String, minutes: Long, driver: String = DRIVER_A) =
        PendingPickupEventEntity(
            idempotencyKey = key,
            driverId = driver,
            routeNodeId = "n-$key",
            eventType = PickupEventType.PICKUP_CONFIRMED,
            exceptionType = null,
            confirmedAt = t0.plusSeconds(60 * minutes)
        )

    @Test
    fun pending_isOldestFirst() = runTest {
        dao.insert(event("late", 5))
        dao.insert(event("early", 1))

        assertEquals(listOf("early", "late"), dao.pending(DRIVER_A).map { it.idempotencyKey })
    }

    @Test
    fun pending_isOnlyThatDriversEvents() = runTest {
        dao.insert(event("a1", 1, DRIVER_A))
        dao.insert(event("b1", 2, DRIVER_B))

        assertEquals(listOf("a1"), dao.pending(DRIVER_A).map { it.idempotencyKey })
        assertEquals(listOf("b1"), dao.pending(DRIVER_B).map { it.idempotencyKey })
    }

    @Test
    fun countPending_isThatDriversEventsStillToUpload() = runTest {
        dao.insert(event("a-pending", 1, DRIVER_A))
        dao.insert(event("a-synced", 2, DRIVER_A))
        dao.insert(event("a-conflict", 3, DRIVER_A))
        dao.insert(event("b-pending", 4, DRIVER_B))
        dao.markSynced("a-synced", t0)
        dao.markConflict("a-conflict", "stop_already_confirmed")

        assertEquals(1, dao.countPending(DRIVER_A))
        assertEquals(1, dao.countPending(DRIVER_B))
        assertEquals(0, dao.countPending("someone-else"))
    }

    @Test
    fun markSynced_removesFromPending() = runTest {
        dao.insert(event("k1", 1))
        dao.insert(event("k2", 2))

        dao.markSynced("k1", t0.plusSeconds(3600))

        assertEquals(listOf("k2"), dao.pending(DRIVER_A).map { it.idempotencyKey })
    }

    @Test
    fun markConflict_removesFromPendingAndSurfacesIt() = runTest {
        dao.insert(event("k1", 1))

        dao.markConflict("k1", "stop_already_confirmed")

        assertEquals(emptyList<PendingPickupEventEntity>(), dao.pending(DRIVER_A))
        val conflict = dao.observeConflicts(DRIVER_A).first().single()
        assertEquals("stop_already_confirmed", conflict.conflict)
        assertNull(conflict.syncedAt)
    }

    @Test
    fun conflicts_areOnlyThatDriversConflicts() = runTest {
        dao.insert(event("a1", 1, DRIVER_A))
        dao.insert(event("b1", 2, DRIVER_B))
        dao.markConflict("a1", "stop_already_confirmed")
        dao.markConflict("b1", "route_node_not_found")

        val seenByB = dao.observeConflicts(DRIVER_B).first().map { it.idempotencyKey }

        assertEquals(listOf("b1"), seenByB)
        assertEquals(listOf("a1"), dao.observeConflicts(DRIVER_A).first().map { it.idempotencyKey })
    }

    @Test
    fun exception_roundTripsItsTypeAndDriver() = runTest {
        dao.insert(
            event("k1", 1).copy(
                eventType = PickupEventType.EXCEPTION,
                exceptionType = PickupExceptionType.NO_SHOW
            )
        )

        val stored = dao.pending(DRIVER_A).single()

        assertEquals(PickupEventType.EXCEPTION, stored.eventType)
        assertEquals(PickupExceptionType.NO_SHOW, stored.exceptionType)
        assertEquals(t0.plusSeconds(60), stored.confirmedAt)
        assertEquals(DRIVER_A, stored.driverId)
    }

    @Test
    fun sameIdempotencyKey_cannotBeStoredTwice() = runTest {
        dao.insert(event("k1", 1))
        try {
            dao.insert(event("k1", 2))
            fail("a second event with the same idempotency key was stored")
        } catch (expected: SQLiteConstraintException) {
            // the key is the primary key
        }
    }

    private companion object {
        const val DRIVER_A = "00000000-0000-0000-0000-00000000000a"
        const val DRIVER_B = "00000000-0000-0000-0000-00000000000b"
    }
}
