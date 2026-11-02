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

/** How server answers move events out of the outbox, with a fake uploader. */
@RunWith(RobolectricTestRunner::class)
class PickupEventOutboxTest {
    /**
     * Answers each event by its route node id; a node not in [answers] gets no
     * result. [retry] answers the whole batch with Retry instead. Records each
     * batch sent, as (node, driver) pairs.
     */
    private class FakeUploader(
        private val answers: Map<String, UploadResult> = emptyMap(),
        private val retry: Boolean = false
    ) : PickupEventUploader {
        val batches = mutableListOf<List<Pair<String, String>>>()

        val uploaded get() = batches.flatten().map { it.first }

        override suspend fun upload(events: List<PendingPickupEventEntity>): BatchResult {
            batches += events.map { it.routeNodeId to it.driverId }
            if (retry) return BatchResult.Retry
            val answered = events.filter { it.routeNodeId in answers }
            return BatchResult.Answered(
                answered.associate { it.idempotencyKey to answers.getValue(it.routeNodeId) }
            )
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

    private suspend fun conflicts() = db.pendingPickupEventDao().observeConflicts(DRIVER_A).first()

    @Test
    fun record_generatesKeyTimeAndDriverOnTheDevice() = runTest {
        val key = outbox(FakeUploader()).recordException("n1", PickupExceptionType.NO_SHOW)

        val stored = pending().single()
        assertEquals(key, stored.idempotencyKey)
        assertEquals(now, stored.confirmedAt)
        assertEquals(DRIVER_A, stored.driverId)
        assertEquals(PickupEventType.EXCEPTION, stored.eventType)
    }

    @Test
    fun synced_isMarkedSyncedInOneBatch() = runTest {
        val uploader = FakeUploader(mapOf("n1" to UploadResult.Synced, "n2" to UploadResult.Synced))
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")
        outbox.recordConfirmation("n2")

        assertEquals(0, outbox.uploadPending())

        assertEquals(1, uploader.batches.size)
        assertTrue(pending().isEmpty())
        assertTrue(conflicts().isEmpty())
    }

    @Test
    fun rejected_isAFinalConflictWithItsCodeAndTheRestStillSync() = runTest {
        val answers = mapOf(
            "n1" to UploadResult.Rejected("already_confirmed"),
            "n2" to UploadResult.Synced
        )
        val uploader = FakeUploader(answers)
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")
        outbox.recordConfirmation("n2")

        assertEquals(0, outbox.uploadPending())
        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf("n1", "n2"), uploader.uploaded)
        assertTrue(pending().isEmpty())
        assertEquals("already_confirmed", conflicts().single().conflict)
    }

    @Test
    fun retry_keepsTheWholeBatchPending() = runTest {
        val outbox = outbox(FakeUploader(retry = true))
        outbox.recordConfirmation("n1")
        outbox.recordConfirmation("n2")

        assertEquals(2, outbox.uploadPending())

        assertEquals(2, pending().size)
        assertTrue(conflicts().isEmpty())
    }

    @Test
    fun anEventTheServerDidNotAnswer_staysPending() = runTest {
        val outbox = outbox(FakeUploader(mapOf("n1" to UploadResult.Synced)))
        outbox.recordConfirmation("n1")
        outbox.recordConfirmation("n2")

        assertEquals(1, outbox.uploadPending())

        assertEquals(listOf("n2"), pending().map { it.routeNodeId })
    }

    @Test
    fun moreThan50Events_goInBatchesOf50() = runTest {
        val nodes = (1..51).map { "n$it" }
        val uploader = FakeUploader(nodes.associateWith { UploadResult.Synced })
        val outbox = outbox(uploader)
        for (node in nodes) outbox.recordConfirmation(node)

        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf(50, 1), uploader.batches.map { it.size })
    }

    @Test
    fun anotherUsersEvents_waitUntilTheySignInAgain() = runTest {
        val uploader = FakeUploader(
            mapOf("a-stop" to UploadResult.Synced, "b-stop" to UploadResult.Synced)
        )
        val outbox = outbox(uploader)
        outbox.recordConfirmation("a-stop")

        signedIn = DRIVER_B
        outbox.recordConfirmation("b-stop")
        assertEquals(0, outbox.uploadPending())

        assertEquals(listOf("b-stop"), uploader.uploaded)
        assertEquals(1, pending(DRIVER_A).size)

        signedIn = DRIVER_A
        outbox.uploadPending()

        assertEquals(
            listOf(listOf("b-stop" to DRIVER_B), listOf("a-stop" to DRIVER_A)),
            uploader.batches
        )
    }

    @Test
    fun nobodySignedIn_uploadsNothing() = runTest {
        val uploader = FakeUploader(mapOf("n1" to UploadResult.Synced))
        val outbox = outbox(uploader)
        outbox.recordConfirmation("n1")

        signedIn = null

        assertEquals(0, outbox.uploadPending())
        assertTrue(uploader.batches.isEmpty())
        assertEquals(1, pending().size)
    }

    private companion object {
        const val DRIVER_A = "00000000-0000-0000-0000-00000000000a"
        const val DRIVER_B = "00000000-0000-0000-0000-00000000000b"
    }
}
