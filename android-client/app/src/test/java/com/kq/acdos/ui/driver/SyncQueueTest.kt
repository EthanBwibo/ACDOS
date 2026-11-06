package com.kq.acdos.ui.driver

import com.kq.acdos.R
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.outbox.BatchResult
import com.kq.acdos.data.outbox.PickupEventOutbox
import com.kq.acdos.data.outbox.UploadResult
import java.time.Instant
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** The Sync tab, read from the real outbox in an in-memory Room database. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
class SyncQueueTest {
    private val t0 = Instant.parse("2026-11-05T02:00:00Z")
    private val driver = "driver-1"

    private lateinit var database: AcdosDatabase

    private fun stop(node: String) = RouteStopEntity(
        routeNodeId = node,
        routeId = "route-1",
        seqOrder = 1,
        crewName = "Crew $node",
        zoneLabel = "Karen, Nairobi",
        scheduledPickup = t0,
        eta = null,
        pickupLat = -1.3,
        pickupLon = 36.7
    )

    private fun event(
        key: String,
        minute: Long,
        syncedAt: Instant? = null,
        conflict: String? = null,
        node: String = "node-$key",
        driverId: String = driver,
        exception: PickupExceptionType? = null
    ) = PendingPickupEventEntity(
        idempotencyKey = key,
        driverId = driverId,
        routeNodeId = node,
        eventType = if (exception == null) {
            PickupEventType.PICKUP_CONFIRMED
        } else {
            PickupEventType.EXCEPTION
        },
        exceptionType = exception,
        confirmedAt = t0.plusSeconds(60 * minute),
        syncedAt = syncedAt,
        conflict = conflict
    )

    private suspend fun insert(vararg events: PendingPickupEventEntity) =
        events.forEach { database.pendingPickupEventDao().insert(it) }

    private suspend fun readQueue(stops: List<RouteStopEntity> = emptyList()) =
        syncQueue(database.pendingPickupEventDao().observeAll(driver).first(), stops)

    private fun outbox(answer: suspend (List<PendingPickupEventEntity>) -> BatchResult) =
        PickupEventOutbox(
            database.pendingPickupEventDao(),
            uploader = { answer(it) },
            currentUserId = { driver }
        )

    private fun viewModel(send: suspend () -> Int) = SyncViewModel(
        database.pendingPickupEventDao().observeAll(driver),
        database.driverRouteDao().observeRouteWithStops().map { it?.stops.orEmpty() },
        send
    )

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        database = inMemoryDatabase()
    }

    @After
    fun tearDown() {
        database.close()
        Dispatchers.resetMain()
    }

    @Test
    fun `waiting events come first, in the order they will be sent`() = runTest {
        insert(event("second", 2), event("first", 1), event("sent", 0, syncedAt = t0))

        val queue = readQueue()

        assertEquals(listOf("first", "second", "sent"), queue.rows.map { it.key })
        assertEquals(2, queue.waiting)
    }

    @Test
    fun `past events are newest first`() = runTest {
        insert(
            event("old", 1, syncedAt = t0),
            event("refused", 2, conflict = "not_your_stop"),
            event("new", 3, syncedAt = t0)
        )

        assertEquals(listOf("new", "refused", "old"), readQueue().rows.map { it.key })
    }

    @Test
    fun `each event has the status Room holds for it`() = runTest {
        insert(
            event("waiting", 3),
            event("sent", 2, syncedAt = t0),
            event("refused", 1, conflict = "already_confirmed")
        )

        val byKey = readQueue().rows.associateBy { it.key }

        assertEquals(QueueStatus.WAITING, byKey.getValue("waiting").status)
        assertEquals(QueueStatus.SENT, byKey.getValue("sent").status)
        assertEquals(QueueStatus.REFUSED, byKey.getValue("refused").status)
        assertEquals("already_confirmed", byKey.getValue("refused").conflict)
    }

    @Test
    fun `the server's codes become reasons, and an unknown code still gets one`() {
        assertEquals(
            R.string.sync_refused_already_confirmed,
            refusalReason("already_confirmed")
        )
        assertEquals(R.string.sync_refused_not_your_stop, refusalReason("not_your_stop"))
        assertEquals(R.string.sync_refused_other, refusalReason("something_new"))
    }

    @Test
    fun `a refused event is not counted as waiting`() = runTest {
        insert(event("refused", 1, conflict = "already_confirmed"))

        assertEquals(0, readQueue().waiting)
    }

    @Test
    fun `last synced is the latest upload, and null before any`() = runTest {
        assertNull(readQueue().lastSynced)

        val later = t0.plusSeconds(600)
        insert(event("a", 1, syncedAt = later), event("b", 2, syncedAt = t0), event("c", 3))

        assertEquals(later, readQueue().lastSynced)
    }

    @Test
    fun `another driver's events on the same phone are not shown`() = runTest {
        insert(event("mine", 1), event("theirs", 2, driverId = "driver-2"))

        assertEquals(listOf("mine"), readQueue().rows.map { it.key })
    }

    @Test
    fun `events are named from the cached stop`() = runTest {
        insert(event("a", 1, node = "node-a"))

        val row = readQueue(listOf(stop("node-a"))).rows.single()

        assertEquals("Crew node-a", row.crewName)
        assertEquals("Karen, Nairobi", row.zoneLabel)
        assertTrue(row.onBoard)
        assertEquals(R.string.sync_action_pickup, row.action)
    }

    @Test
    fun `an event stays listed after a re-plan takes its stop away`() = runTest {
        insert(event("a", 1, node = "gone"))

        val row = readQueue(stops = emptyList()).rows.single()

        assertEquals("a", row.key)
        assertNull(row.crewName)
        assertNull(row.zoneLabel)
    }

    @Test
    fun `a no-show is not shown as on board`() = runTest {
        insert(event("a", 1, exception = PickupExceptionType.NO_SHOW))

        val row = readQueue().rows.single()

        assertFalse(row.onBoard)
        assertEquals(R.string.route_status_no_show, row.action)
    }

    @Test
    fun `history stops at the cap and says how many are left off, but waiting never does`() =
        runTest {
            val extra = 3
            for (i in 0 until QUEUE_HISTORY_ROWS + extra) {
                insert(event("sent-$i", i.toLong(), syncedAt = t0))
            }
            for (i in 0 until 30) {
                insert(event("wait-$i", 100L + i))
            }

            val queue = readQueue()

            assertEquals(30 + QUEUE_HISTORY_ROWS, queue.rows.size)
            assertEquals(extra, queue.hidden)
            assertEquals(30, queue.rows.count { it.status == QueueStatus.WAITING })
        }

    @Test
    fun `Sync now uploads for real and the screen follows Room`() = runTest {
        val recorder = outbox { batch ->
            BatchResult.Answered(batch.associate { it.idempotencyKey to UploadResult.Synced })
        }
        database.driverRouteDao().saveActiveRoute(
            RouteEntity("route-1", "KDH 101A", t0),
            listOf(stop("node-a"))
        )
        recorder.recordConfirmation("node-a")
        val viewModel = viewModel(send = recorder::uploadPending)
        assertEquals(1, readQueue().waiting)

        viewModel.syncNow()

        assertEquals(0, viewModel.results.first())
        assertEquals(QueueStatus.SENT, readQueue().rows.single().status)
    }

    @Test
    fun `Sync now reports what is still waiting when the upload fails`() = runTest {
        val recorder = outbox { BatchResult.Retry }
        recorder.recordConfirmation("node-a")
        val viewModel = viewModel(send = recorder::uploadPending)

        viewModel.syncNow()

        assertEquals(1, viewModel.results.first())
        assertEquals(QueueStatus.WAITING, readQueue().rows.single().status)
    }

    @Test
    fun `a second tap while sending does nothing`() {
        var sends = 0
        val gate = CompletableDeferred<Int>()
        val viewModel = SyncViewModel(flowOf(emptyList()), flowOf(emptyList())) {
            sends++
            gate.await()
        }

        viewModel.syncNow()
        viewModel.syncNow()

        assertTrue(viewModel.sending.value)
        gate.complete(0)
        runBlocking { viewModel.results.first() }
        assertEquals(1, sends)
        assertFalse(viewModel.sending.value)
    }
}
