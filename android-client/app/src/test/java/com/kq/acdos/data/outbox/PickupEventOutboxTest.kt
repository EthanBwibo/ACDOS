package com.kq.acdos.data.outbox

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.inMemoryDatabase
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** How server answers move an event out of the outbox, with a fake uploader. */
@RunWith(RobolectricTestRunner::class)
class PickupEventOutboxTest {
    private class FakeUploader(private val answers: Map<String, UploadResult>) :
        PickupEventUploader {
        val uploaded = mutableListOf<String>()

        override suspend fun upload(event: PendingPickupEventEntity): UploadResult {
            uploaded += event.routeNodeId
            return answers.getValue(event.routeNodeId)
        }
    }

    private lateinit var db: AcdosDatabase
    private val now = Instant.parse("2026-11-01T03:42:00Z")
    private val clock = Clock.fixed(now, ZoneOffset.UTC)
    private var keys = 0

    @Before
    fun setUp() {
        db = inMemoryDatabase()
    }

    @After
    fun tearDown() = db.close()

    private fun outbox(uploader: PickupEventUploader) =
        PickupEventOutbox(db.pendingPickupEventDao(), uploader, clock) { "key-${++keys}" }

    @Test
    fun record_generatesKeyAndTimeOnTheDevice() = runTest {
        val key = outbox { UploadResult.Retry }.recordException("n1", PickupExceptionType.NO_SHOW)

        val stored = db.pendingPickupEventDao().pending().single()
        assertEquals(key, stored.idempotencyKey)
        assertEquals(now, stored.confirmedAt)
        assertEquals(PickupEventType.EXCEPTION, stored.eventType)
    }

    @Test
    fun accepted_isMarkedSynced() = runTest {
        val outbox = outbox(FakeUploader(mapOf("n1" to UploadResult.Accepted)))
        outbox.recordConfirmation("n1")

        assertEquals(0, outbox.uploadPending())
        assertTrue(db.pendingPickupEventDao().pending().isEmpty())
    }

    @Test
    fun duplicateKey_countsAsSuccess() = runTest {
        // An earlier upload reached the server but its response was lost.
        val outbox = outbox(FakeUploader(mapOf("n1" to UploadResult.DuplicateKey)))
        outbox.recordConfirmation("n1")

        assertEquals(0, outbox.uploadPending())
        assertTrue(db.pendingPickupEventDao().pending().isEmpty())
        assertTrue(db.pendingPickupEventDao().observeConflicts().first().isEmpty())
    }

    @Test
    fun alreadyConfirmed_isATerminalConflictAndNeverRetried() = runTest {
        val uploader = FakeUploader(mapOf("n1" to UploadResult.AlreadyConfirmed))
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")

        assertEquals(0, outbox.uploadPending())
        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf("n1"), uploader.uploaded)
        val conflict = db.pendingPickupEventDao().observeConflicts().first().single()
        assertEquals(PickupEventOutbox.CONFLICT_ALREADY_CONFIRMED, conflict.conflict)
    }

    @Test
    fun retry_keepsTheEventAndStopsTheRun() = runTest {
        val answers = mapOf("n1" to UploadResult.Retry, "n2" to UploadResult.Accepted)
        val uploader = FakeUploader(answers)
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")
        outbox.recordConfirmation("n2")

        assertEquals(2, outbox.uploadPending())

        assertEquals(listOf("n1"), uploader.uploaded)
        assertEquals(2, db.pendingPickupEventDao().pending().size)
    }
}
