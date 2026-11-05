package com.kq.acdos.ui.driver

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.outbox.BatchResult
import com.kq.acdos.data.outbox.PickupEventOutbox
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
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
import org.robolectric.annotation.Config

private const val DRIVER = "driver-1"
private const val NODE = "node-1"

/** Against a real Room database, because what matters here is what ends up in the outbox. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ConfirmPickupViewModelTest {
    private lateinit var database: AcdosDatabase
    private val dispatcher = StandardTestDispatcher()
    private var uploads = 0

    private val stop = RouteStopEntity(
        routeNodeId = NODE,
        routeId = "route-1",
        seqOrder = 1,
        crewName = "A. Sample",
        zoneLabel = "Karen, Nairobi",
        scheduledPickup = Instant.EPOCH,
        eta = null,
        pickupLat = -1.3,
        pickupLon = 36.7
    )

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        database = inMemoryDatabase()
        runBlocking {
            database.driverRouteDao().saveActiveRoute(
                RouteEntity("route-1", "KDH 101A", Instant.EPOCH),
                listOf(stop)
            )
        }
    }

    @After
    fun tearDown() {
        database.close()
        Dispatchers.resetMain()
    }

    private fun viewModel() = ConfirmPickupViewModel(
        database.driverRouteDao(),
        NODE,
        PickupEventOutbox(
            database.pendingPickupEventDao(),
            uploader = { BatchResult.Retry },
            currentUserId = { DRIVER }
        ),
        upload = { uploads++ }
    )

    private fun waitUntilFinished(viewModel: ConfirmPickupViewModel) = runBlocking {
        repeat(200) {
            dispatcher.scheduler.advanceUntilIdle()
            if (viewModel.finished.value) return@runBlocking
            delay(5)
        }
    }

    private fun outbox(): List<PendingPickupEventEntity> = runBlocking {
        database.pendingPickupEventDao().observeAll(DRIVER).first()
    }

    @Test
    fun `crew on board is saved, then uploaded, then the screen closes`() {
        val viewModel = viewModel()

        viewModel.crewOnBoard()
        waitUntilFinished(viewModel)

        val event = outbox().single()
        assertEquals(PickupEventType.PICKUP_CONFIRMED, event.eventType)
        assertEquals(NODE, event.routeNodeId)
        assertNull(event.syncedAt)
        assertEquals(1, uploads)
        assertTrue(viewModel.finished.value)
    }

    @Test
    fun `a double tap records one event`() {
        val viewModel = viewModel()

        viewModel.crewOnBoard()
        viewModel.crewOnBoard()
        waitUntilFinished(viewModel)

        assertEquals(1, outbox().size)
    }

    @Test
    fun `not at the pickup point records a no-show`() {
        val viewModel = viewModel()

        viewModel.report(PickupExceptionType.NO_SHOW)
        waitUntilFinished(viewModel)

        assertEquals(PickupExceptionType.NO_SHOW, outbox().single().exceptionType)
    }

    @Test
    fun `nothing is recorded until the driver decides`() {
        val viewModel = viewModel()

        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(outbox().isEmpty())
        assertFalse(viewModel.finished.value)
    }

    @Test
    fun `the stop comes from the cached route`() = runBlocking {
        assertEquals("A. Sample", viewModel().stop.first()?.crewName)
    }

    @Test
    fun `a stop that has left the route reads as gone`() = runBlocking {
        database.driverRouteDao().deleteAllRoutes()

        assertNull(viewModel().stop.first())
    }
}
