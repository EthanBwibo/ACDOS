package com.kq.acdos.ui.driver

import android.view.ContextThemeWrapper
import android.view.MotionEvent
import android.view.View
import androidx.test.core.app.ApplicationProvider
import com.kq.acdos.R
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.osmdroid.config.Configuration
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.overlay.CopyrightOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

private val DONE = StopProgress(
    type = PickupEventType.PICKUP_CONFIRMED,
    exception = null,
    sent = true,
    conflict = null,
    done = true
)

/** The route map (#227): what it draws, in what order, and how it's set up. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class RouteMapTest {
    private fun stop(number: Int, lat: Double, progress: StopProgress? = null) = StopRow(
        routeNodeId = "node-$number",
        number = number,
        crewName = "Crew $number",
        zoneLabel = "Karen, Nairobi",
        pickupTime = Instant.EPOCH,
        lat = lat,
        lon = 36.8,
        progress = progress
    )

    private val noShow = DONE.copy(
        type = PickupEventType.EXCEPTION,
        exception = PickupExceptionType.NO_SHOW,
        noShow = true
    )

    @Test
    fun `the line joins the stops in visiting order and ends at JKIA`() {
        val stops = listOf(
            MapStop(MapPoint(-1.30, 36.70), 1, StopMark.PICKED_UP),
            MapStop(MapPoint(-1.25, 36.80), 2, StopMark.NEXT)
        )

        assertEquals(
            listOf(MapPoint(-1.30, 36.70), MapPoint(-1.25, 36.80), JKIA_POINT),
            routeLine(stops)
        )
    }

    @Test
    fun `picked up stops are grey, the next is red, the rest are plain`() {
        val stops = listOf(
            stop(1, -1.30, DONE),
            stop(2, -1.29, noShow),
            stop(3, -1.28),
            stop(4, -1.27)
        )

        val marks = driverMapStops(stops, next = stops[2])

        assertEquals(
            listOf(StopMark.PICKED_UP, StopMark.AHEAD, StopMark.NEXT, StopMark.AHEAD),
            marks.map { it.mark }
        )
        assertEquals(listOf(1, 2, 3, 4), marks.map { it.number })
        assertEquals(MapPoint(-1.28, 36.8), marks[2].point)
    }

    @Test
    fun `with every stop picked up, none is next`() {
        val stops = listOf(stop(1, -1.30, DONE), stop(2, -1.29, DONE))

        val marks = driverMapStops(stops, next = null).map { it.mark }

        assertEquals(listOf(StopMark.PICKED_UP, StopMark.PICKED_UP), marks)
    }

    private fun mapView(): RouteMapView {
        val context = ContextThemeWrapper(
            ApplicationProvider.getApplicationContext(),
            R.style.Theme_ACDOS
        )
        return RouteMapView(context)
    }

    @Test
    fun `the map draws the line, a marker per stop, JKIA and the OSM credit`() {
        val map = mapView()

        map.show(
            listOf(
                MapStop(MapPoint(-1.30, 36.70), 1, StopMark.PICKED_UP),
                MapStop(MapPoint(-1.25, 36.80), 2, StopMark.NEXT)
            )
        )

        val overlays = map.overlays
        assertEquals(1, overlays.filterIsInstance<Polyline>().size)
        assertEquals(
            listOf("1", "2", "JKIA"),
            overlays.filterIsInstance<Marker>().map { it.title }
        )
        assertEquals(1, overlays.filterIsInstance<CopyrightOverlay>().size)
        assertEquals(3, overlays.filterIsInstance<Polyline>().single().actualPoints.size)
    }

    @Test
    fun `recentre frames the whole route again after the driver zooms in`() {
        val map = mapView()
        map.measure(
            View.MeasureSpec.makeMeasureSpec(400, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(300, View.MeasureSpec.EXACTLY)
        )
        map.layout(0, 0, 400, 300)
        map.show(listOf(MapStop(MapPoint(-1.26, 36.80), 1, StopMark.NEXT)))
        val framed = map.zoomLevelDouble
        map.controller.setZoom(18.0)
        map.controller.setCenter(GeoPoint(-1.10, 36.60))

        map.recentre()

        assertEquals(framed, map.zoomLevelDouble, 0.01)
        assertTrue(map.boundingBox.contains(GeoPoint(JKIA_POINT.lat, JKIA_POINT.lon)))
        assertTrue(map.boundingBox.contains(GeoPoint(-1.26, 36.80)))
    }

    @Test
    fun `the read-only map takes no touches, so the screen scrolls past it`() {
        val map = mapView()
        map.readOnly = true
        val down = MotionEvent.obtain(0, 0, MotionEvent.ACTION_DOWN, 10f, 10f, 0)

        assertFalse(map.dispatchTouchEvent(down))
    }

    @Test
    fun `tile requests carry the app id, as OSM's tile policy asks`() {
        assertEquals("com.kq.acdos", Configuration.getInstance().userAgentValue)
    }
}
