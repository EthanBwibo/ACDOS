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

    private fun event(key: String, minutes: Long) = PendingPickupEventEntity(
        idempotencyKey = key,
        routeNodeId = "n-$key",
        eventType = PickupEventType.PICKUP_CONFIRMED,
        exceptionType = null,
        confirmedAt = t0.plusSeconds(60 * minutes)
    )

    @Test
    fun pending_isOldestFirst() = runTest {
        dao.insert(event("late", 5))
        dao.insert(event("early", 1))

        assertEquals(listOf("early", "late"), dao.pending().map { it.idempotencyKey })
    }

    @Test
    fun markSynced_removesFromPending() = runTest {
        dao.insert(event("k1", 1))
        dao.insert(event("k2", 2))

        dao.markSynced("k1", t0.plusSeconds(3600))

        assertEquals(listOf("k2"), dao.pending().map { it.idempotencyKey })
    }

    @Test
    fun markConflict_removesFromPendingAndSurfacesIt() = runTest {
        dao.insert(event("k1", 1))

        dao.markConflict("k1", "stop_already_confirmed")

        assertEquals(emptyList<PendingPickupEventEntity>(), dao.pending())
        val conflict = dao.observeConflicts().first().single()
        assertEquals("stop_already_confirmed", conflict.conflict)
        assertNull(conflict.syncedAt)
    }

    @Test
    fun exception_roundTripsItsType() = runTest {
        dao.insert(
            event("k1", 1).copy(
                eventType = PickupEventType.EXCEPTION,
                exceptionType = PickupExceptionType.NO_SHOW
            )
        )

        val stored = dao.pending().single()

        assertEquals(PickupEventType.EXCEPTION, stored.eventType)
        assertEquals(PickupExceptionType.NO_SHOW, stored.exceptionType)
        assertEquals(t0.plusSeconds(60), stored.confirmedAt)
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
}
