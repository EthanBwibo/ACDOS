package com.kq.acdos.ui.driver

import android.net.NetworkCapabilities
import com.kq.acdos.R
import com.kq.acdos.data.NetworkKind
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.networkKind
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadow.api.Shadow

private val PICKED_UP = StopProgress(
    type = PickupEventType.PICKUP_CONFIRMED,
    exception = null,
    sent = true,
    conflict = null,
    done = true
)

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RouteProgressTest {
    private fun stop(number: Int, progress: StopProgress? = null) = StopRow(
        routeNodeId = "node-$number",
        number = number,
        crewName = "Crew $number",
        zoneLabel = "Karen, Nairobi",
        pickupTime = Instant.EPOCH,
        lat = -1.3,
        lon = 36.8,
        progress = progress
    )

    private fun event(
        key: String,
        exception: PickupExceptionType? = null,
        conflict: String? = null
    ) = PendingPickupEventEntity(
        idempotencyKey = key,
        driverId = "driver-1",
        routeNodeId = "node-1",
        eventType = if (exception == null) {
            PickupEventType.PICKUP_CONFIRMED
        } else {
            PickupEventType.EXCEPTION
        },
        exceptionType = exception,
        confirmedAt = Instant.EPOCH,
        conflict = conflict
    )

    private fun progressOf(vararg events: PendingPickupEventEntity) =
        stopProgress(events.toList()).getValue("node-1")

    @Test
    fun `a no-show stays listed, and leaves the next pickup`() {
        val noShow = progressOf(event("a", PickupExceptionType.NO_SHOW))

        val progress = routeProgress(listOf(stop(1, noShow), stop(2)))

        assertEquals("node-1", progress.noShows.single().routeNodeId)
        assertEquals("node-2", progress.next?.routeNodeId)
    }

    @Test
    fun `crew on board after a no-show counts as picked up`() {
        val late = progressOf(event("a", PickupExceptionType.NO_SHOW), event("b"))

        val progress = routeProgress(listOf(stop(1, late)))

        assertTrue(progress.noShows.isEmpty())
        assertEquals(1, progress.pickedUp)
    }

    @Test
    fun `a refused late pickup leaves the no-show standing`() {
        val refused = progressOf(
            event("a", PickupExceptionType.NO_SHOW),
            event("b", conflict = "already_confirmed")
        )

        val progress = routeProgress(listOf(stop(1, refused)))

        assertEquals(1, progress.noShows.size)
        assertEquals(0, progress.pickedUp)
        assertEquals("already_confirmed", refused.conflict)
    }

    @Test
    fun `a refused no-show isn't a no-show`() {
        val refused = progressOf(
            event("a", PickupExceptionType.NO_SHOW, conflict = "not_your_stop")
        )

        assertFalse(refused.noShow)
        assertFalse(refused.done)
    }

    @Test
    fun `stop minutes round to the nearest minute`() {
        val t0 = Instant.EPOCH

        assertEquals(7, legMinutes(t0, t0.plusSeconds(7 * 60 + 29)))
        assertEquals(8, legMinutes(t0, t0.plusSeconds(7 * 60 + 30)))
    }

    @Test
    fun `stops at the same place have no minutes`() {
        val t0 = Instant.EPOCH

        assertNull(legMinutes(t0, t0))
        assertNull(legMinutes(t0, t0.plusSeconds(29)))
        assertNull(legMinutes(t0.plusSeconds(600), t0))
    }

    @Test
    fun `the next pickup is the first stop still open`() {
        val stops = listOf(stop(1, PICKED_UP), stop(2), stop(3))

        val progress = routeProgress(stops)

        assertEquals(stops[1], progress.next)
        assertEquals(listOf(stops[2]), progress.then)
        assertEquals(1, progress.pickedUp)
    }

    @Test
    fun `a no-show is finished but is not a pickup`() {
        val noShow = PICKED_UP.copy(
            type = PickupEventType.EXCEPTION,
            exception = PickupExceptionType.NO_SHOW,
            noShow = true
        )

        val progress = routeProgress(listOf(stop(1, noShow), stop(2)))

        assertEquals(2, progress.next?.number)
        assertEquals(0, progress.pickedUp)
    }

    @Test
    fun `a stop the server refused comes back as the next pickup`() {
        val refused = PICKED_UP.copy(sent = false, conflict = "already_confirmed", done = false)

        assertEquals(1, routeProgress(listOf(stop(1, refused), stop(2))).next?.number)
    }

    @Test
    fun `a traffic delay leaves the stop open`() {
        val delay = PICKED_UP.copy(
            type = PickupEventType.EXCEPTION,
            exception = PickupExceptionType.TRAFFIC_DELAY,
            done = false
        )

        assertEquals(1, routeProgress(listOf(stop(1, delay))).next?.number)
    }

    @Test
    fun `nothing is next once every stop is done`() {
        val progress = routeProgress(listOf(stop(1, PICKED_UP)))

        assertNull(progress.next)
        assertTrue(progress.then.isEmpty())
    }

    @Test
    fun `the sync chip says what the driver needs to know`() {
        assertEquals(R.string.sync_chip_offline, syncChipText(online = false, queued = 0))
        assertEquals(R.string.sync_chip_offline, syncChipText(online = false, queued = 2))
        assertEquals(R.string.sync_chip_online, syncChipText(online = true, queued = 2))
        assertEquals(R.string.sync_chip_all_sent, syncChipText(online = true, queued = 0))
    }

    @Test
    fun `zone labels are shortened to the place name`() {
        assertEquals("Karen", shortZone("Karen, Nairobi"))
        assertEquals("Karen", shortZone("Karen"))
    }

    @Test
    fun `initials come from the first and last word`() {
        assertEquals("AS", initials("A. Sample"))
        assertEquals("CO", initials("Capt. Amina B. Otieno"))
        assertEquals("T", initials("Test"))
        assertEquals("", initials(""))
    }

    @Test
    fun `the phone's network maps to what the screens show`() {
        fun caps(transport: Int?, internet: Boolean): NetworkCapabilities {
            val capabilities = Shadow.newInstanceOf(NetworkCapabilities::class.java)
            val shadow = shadowOf(capabilities)
            if (internet) shadow.addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            transport?.let(shadow::addTransportType)
            return capabilities
        }

        assertEquals(NetworkKind.NONE, networkKind(null))
        assertEquals(
            NetworkKind.NONE,
            networkKind(caps(NetworkCapabilities.TRANSPORT_WIFI, internet = false))
        )
        assertEquals(
            NetworkKind.WIFI,
            networkKind(caps(NetworkCapabilities.TRANSPORT_WIFI, internet = true))
        )
        assertEquals(
            NetworkKind.MOBILE,
            networkKind(caps(NetworkCapabilities.TRANSPORT_CELLULAR, internet = true))
        )
    }
}
