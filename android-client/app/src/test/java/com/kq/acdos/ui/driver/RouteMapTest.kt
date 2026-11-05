package com.kq.acdos.ui.driver

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RouteMapTest {
    private val delta = 0.01f

    @Test
    fun `north is up and east is right`() {
        val south = MapPoint(lat = -1.4, lon = 36.7)
        val north = MapPoint(lat = -1.2, lon = 36.9)

        val (first, second) = projectRoute(listOf(south, north), 300f, 300f, 20f)

        assertTrue(second.x > first.x)
        assertTrue(second.y < first.y)
    }

    @Test
    fun `every point stays inside the margin`() {
        val points = listOf(
            MapPoint(-1.25, 36.70),
            MapPoint(-1.31, 36.82),
            MapPoint(-1.27, 36.88),
            JKIA_POINT
        )

        for (point in projectRoute(points, 340f, 190f, 28f)) {
            assertTrue(point.x in 28f..312f)
            assertTrue(point.y in 28f..162f)
        }
    }

    @Test
    fun `one scale for both axes keeps the route's shape`() {
        val points = listOf(MapPoint(0.0, 0.0), MapPoint(1.0, 1.0))

        val (first, second) = projectRoute(points, 400f, 200f, 0f)

        assertEquals(second.x - first.x, first.y - second.y, delta)
    }

    @Test
    fun `a single point sits in the middle`() {
        val only = projectRoute(listOf(JKIA_POINT), 300f, 200f, 20f).single()

        assertEquals(150f, only.x, delta)
        assertEquals(100f, only.y, delta)
    }

    @Test
    fun `points in a straight line don't divide by zero`() {
        val across = projectRoute(listOf(MapPoint(0.0, 0.0), MapPoint(0.0, 1.0)), 300f, 200f, 20f)
        val upDown = projectRoute(listOf(MapPoint(0.0, 0.0), MapPoint(1.0, 0.0)), 300f, 200f, 20f)

        assertEquals(20f, across[0].x, delta)
        assertEquals(280f, across[1].x, delta)
        assertEquals(180f, upDown[0].y, delta)
        assertEquals(20f, upDown[1].y, delta)
    }

    @Test
    fun `no points draw nothing`() {
        assertTrue(projectRoute(emptyList(), 300f, 200f, 20f).isEmpty())
    }
}
