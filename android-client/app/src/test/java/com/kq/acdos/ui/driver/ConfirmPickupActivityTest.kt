package com.kq.acdos.ui.driver

import android.os.Looper
import android.view.View
import androidx.test.core.app.ApplicationProvider
import com.google.android.material.button.MaterialButton
import com.kq.acdos.AcdosApplication
import com.kq.acdos.AppContainer
import com.kq.acdos.R
import com.kq.acdos.data.DriverRouteRepository
import com.kq.acdos.data.FakeMeApi
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.RouteEntity
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.outbox.BatchResult
import com.kq.acdos.data.outbox.PickupEventOutbox
import com.kq.acdos.data.remote.DriverRouteDto
import com.kq.acdos.data.remote.DriverRouteResponseDto
import com.kq.acdos.data.remote.DriverStopDto
import com.kq.acdos.data.remote.RouteStatusDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ActivityController
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowDialog
import org.robolectric.shadows.ShadowToast
import retrofit2.Response

private const val NODE = "node-1"

/** The real container with the network swapped out, so no build config can reach Supabase. */
class FakeApiApplication : AcdosApplication() {
    val api = FakeMeApi()
    var now: Instant = Instant.EPOCH

    override val container: AppContainer by lazy {
        object : AppContainer(this) {
            override val driverRouteRepository by lazy {
                DriverRouteRepository(api, database.driverRouteDao(), clock = { now })
            }

            override val pickupEventOutbox by lazy {
                PickupEventOutbox(
                    database.pendingPickupEventDao(),
                    uploader = { BatchResult.Retry },
                    currentUserId = { "driver-1" }
                )
            }
        }
    }
}

/** The real screen on the real theme, reading the app's own Room database. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = FakeApiApplication::class)
class ConfirmPickupActivityTest {
    private val app get() = ApplicationProvider.getApplicationContext<FakeApiApplication>()

    private val container get() = app.container

    private val routes get() = container.database.driverRouteDao()

    private val stopDto = DriverStopDto(
        routeNodeId = NODE,
        seqOrder = 1,
        crewName = "A. Sample",
        zoneLabel = "Karen, Nairobi",
        scheduledPickup = Instant.EPOCH,
        lat = -1.3,
        lon = 36.7
    )

    /** What the server says the route is now. */
    private fun serverHas(stops: List<DriverStopDto>) {
        val route = DriverRouteDto("route-1", RouteStatusDto.ACTIVE, "KDH 101A", stops)
        app.api.next = { Response.success(DriverRouteResponseDto(route)) }
    }

    private fun waitOutThrottle() {
        app.now = app.now.plusSeconds(DriverRouteRepository.THROTTLE.seconds + 1)
    }

    private var controller: ActivityController<ConfirmPickupActivity>? = null

    @Before
    fun setUp() = runBlocking {
        serverHas(listOf(stopDto))
        routes.saveActiveRoute(
            RouteEntity("route-1", "KDH 101A", Instant.EPOCH),
            listOf(
                RouteStopEntity(
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
            )
        )
    }

    @After
    fun tearDown() {
        container.database.close()
    }

    private fun open(): ConfirmPickupActivity {
        val intent = ConfirmPickupActivity.intent(ApplicationProvider.getApplicationContext(), NODE)
        val opened = Robolectric.buildActivity(ConfirmPickupActivity::class.java, intent).setup()
        controller = opened
        settle()
        return opened.get()
    }

    /** Room answers on its own thread, so the main looper needs a moment to hear it. */
    private fun settle(until: () -> Boolean = { false }) {
        repeat(40) {
            shadowOf(Looper.getMainLooper()).idle()
            if (until()) return
            Thread.sleep(25)
        }
    }

    private fun recordNoShow() = runBlocking {
        container.database.pendingPickupEventDao().insert(
            PendingPickupEventEntity(
                idempotencyKey = "key-1",
                driverId = "driver-1",
                routeNodeId = NODE,
                eventType = PickupEventType.EXCEPTION,
                exceptionType = PickupExceptionType.NO_SHOW,
                confirmedAt = Instant.EPOCH
            )
        )
    }

    private fun recorded() = runBlocking {
        container.database.pendingPickupEventDao().observeForStop(NODE).first()
    }

    @Test
    fun `a stop re-planned away while the screen is hidden closes it on resume`() {
        val activity = open()
        assertFalse(activity.isFinishing)
        controller!!.pause().stop()

        runBlocking { routes.deleteAllRoutes() }
        settle()
        assertFalse("waits for the driver to come back", activity.isFinishing)

        controller!!.restart().resume()
        settle(until = { activity.isFinishing })

        assertTrue(activity.isFinishing)
        assertEquals(
            activity.getString(R.string.confirm_stop_gone),
            ShadowToast.getTextOfLatestToast()
        )
    }

    @Test
    fun `coming back asks the server, and a re-plan there closes the screen`() {
        val activity = open()
        val asked = app.api.calls
        controller!!.pause().stop()

        serverHas(emptyList())
        waitOutThrottle()
        controller!!.restart().resume()
        settle(until = { activity.isFinishing })

        assertEquals(asked + 1, app.api.calls)
        assertTrue(activity.isFinishing)
        assertEquals(
            activity.getString(R.string.confirm_stop_gone),
            ShadowToast.getTextOfLatestToast()
        )
    }

    @Test
    fun `no signal keeps the screen open, because the event can still be saved`() {
        val activity = open()
        controller!!.pause().stop()

        app.api.next = { throw IOException("no signal") }
        waitOutThrottle()
        controller!!.restart().resume()
        settle()

        assertFalse(activity.isFinishing)
    }

    @Test
    fun `a stop still on the route leaves the screen open on resume`() {
        val activity = open()
        controller!!.pause().stop()

        controller!!.restart().resume()
        settle()

        assertFalse(activity.isFinishing)
    }

    @Test
    fun `the re-plan's dialog goes with the screen`() {
        val activity = open()
        activity.findViewById<MaterialButton>(R.id.not_at_point).performClick()
        settle()
        val dialog = ShadowDialog.getLatestDialog()
        assertTrue(dialog.isShowing)

        runBlocking { routes.deleteAllRoutes() }
        settle(until = { activity.isFinishing })

        assertTrue(activity.isFinishing)
        assertFalse(dialog.isShowing)
    }

    @Test
    fun `not at the pickup point asks first and records nothing until confirmed`() {
        val activity = open()

        activity.findViewById<MaterialButton>(R.id.not_at_point).performClick()
        settle()

        assertTrue(ShadowDialog.getLatestDialog().isShowing)
        assertTrue(recorded().isEmpty())
        assertFalse(activity.isFinishing)
    }

    @Test
    fun `after a no-show only crew on board is offered`() {
        recordNoShow()

        val activity = open()
        val chip = activity.findViewById<View>(R.id.no_show_chip)
        settle(until = { chip.visibility == View.VISIBLE })

        assertEquals(View.VISIBLE, chip.visibility)
        assertEquals(View.GONE, activity.findViewById<View>(R.id.not_at_point).visibility)
        assertEquals(View.VISIBLE, activity.findViewById<View>(R.id.on_board).visibility)
    }
}
