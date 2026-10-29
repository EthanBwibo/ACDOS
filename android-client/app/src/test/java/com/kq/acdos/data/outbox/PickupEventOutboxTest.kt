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
    /** Answers by route node id; records what was sent, with the driver it was sent as. */
    private class FakeUploader(private val answers: Map<String, UploadResult>) :
        PickupEventUploader {
        val uploaded = mutableListOf<String>()
        val sentAs = mutableListOf<String>()

        override suspend fun upload(event: PendingPickupEventEntity): UploadResult {
            uploaded += event.routeNodeId
            sentAs += event.driverId
            return answers.getValue(event.routeNodeId)
        }
    }

    private lateinit var db: AcdosDatabase
    private val now = Instant.parse("2026-11-01T03:42:00Z")
    private val clock = Clock.fixed(now, ZoneOffset.UTC)
    private var keys = 0
    private var signedIn: String? = DRIVER_A

    @Before
    fun setUp() {
        db = inMemoryDatabase()
    }

    @After
    fun tearDown() = db.close()

    private fun outbox(uploader: PickupEventUploader) = PickupEventOutbox(
        db.pendingPickupEventDao(),
        uploader,
        currentUserId = { signedIn },
        clock = clock
    ) { "key-${++keys}" }

    private suspend fun pending(driver: String = DRIVER_A) =
        db.pendingPickupEventDao().pending(driver)

    @Test
    fun record_generatesKeyTimeAndDriverOnTheDevice() = runTest {
        val key = outbox { UploadResult.Retry }.recordException("n1", PickupExceptionType.NO_SHOW)

        val stored = pending().single()
        assertEquals(key, stored.idempotencyKey)
        assertEquals(now, stored.confirmedAt)
        assertEquals(DRIVER_A, stored.driverId)
        assertEquals(PickupEventType.EXCEPTION, stored.eventType)
    }

    @Test
    fun accepted_isMarkedSynced() = runTest {
        val outbox = outbox(FakeUploader(mapOf("n1" to UploadResult.Accepted)))
        outbox.recordConfirmation("n1")

        assertEquals(0, outbox.uploadPending())
        assertTrue(pending().isEmpty())
    }

    @Test
    fun duplicateKey_countsAsSuccess() = runTest {
        // An earlier upload reached the server but its response was lost.
        val outbox = outbox(FakeUploader(mapOf("n1" to UploadResult.DuplicateKey)))
        outbox.recordConfirmation("n1")

        assertEquals(0, outbox.uploadPending())
        assertTrue(pending().isEmpty())
        assertTrue(db.pendingPickupEventDao().observeConflicts(DRIVER_A).first().isEmpty())
    }

    @Test
    fun alreadyConfirmed_isATerminalConflictAndNeverRetried() = runTest {
        val uploader = FakeUploader(mapOf("n1" to UploadResult.AlreadyConfirmed))
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")

        assertEquals(0, outbox.uploadPending())
        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf("n1"), uploader.uploaded)
        val conflict = db.pendingPickupEventDao().observeConflicts(DRIVER_A).first().single()
        assertEquals(PickupEventOutbox.CONFLICT_ALREADY_CONFIRMED, conflict.conflict)
    }

    @Test
    fun rejected_storesTheReasonAndDoesNotBlockLaterEvents() = runTest {
        val answers = mapOf(
            "n1" to UploadResult.Rejected("route_node_not_found"),
            "n2" to UploadResult.Accepted
        )
        val uploader = FakeUploader(answers)
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")
        outbox.recordConfirmation("n2")

        assertEquals(0, outbox.uploadPending())
        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf("n1", "n2"), uploader.uploaded)
        assertTrue(pending().isEmpty())
        val conflict = db.pendingPickupEventDao().observeConflicts(DRIVER_A).first().single()
        assertEquals("route_node_not_found", conflict.conflict)
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
        assertEquals(2, pending().size)
    }

    @Test
    fun anotherUsersEvents_waitUntilTheySignInAgain() = runTest {
        val answers = mapOf("a-stop" to UploadResult.Accepted, "b-stop" to UploadResult.Accepted)
        val uploader = FakeUploader(answers)
        val outbox = outbox(uploader)
        outbox.recordConfirmation("a-stop")

        signedIn = DRIVER_B
        outbox.recordConfirmation("b-stop")
        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf("b-stop"), uploader.uploaded)
        assertEquals(1, pending(DRIVER_A).size)

        signedIn = DRIVER_A
        outbox.uploadPending()

        assertEquals(listOf("b-stop", "a-stop"), uploader.uploaded)
        assertEquals(listOf(DRIVER_B, DRIVER_A), uploader.sentAs)
    }

    @Test
    fun nobodySignedIn_uploadsNothing() = runTest {
        val uploader = FakeUploader(mapOf("n1" to UploadResult.Accepted))
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")

        signedIn = null

        assertEquals(0, outbox.uploadPending())
        assertTrue(uploader.uploaded.isEmpty())
        assertEquals(1, pending().size)
    }

    private companion object {
        const val DRIVER_A = "00000000-0000-0000-0000-00000000000a"
        const val DRIVER_B = "00000000-0000-0000-0000-00000000000b"
    }
}
