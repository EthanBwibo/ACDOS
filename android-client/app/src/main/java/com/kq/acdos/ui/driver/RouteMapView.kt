package com.kq.acdos.ui.driver

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.View
import com.google.android.material.color.MaterialColors
import kotlin.math.min

/** A place on the route, in degrees. */
data class MapPoint(val lat: Double, val lon: Double)

/** A position inside the view, in pixels. */
data class MapXy(val x: Float, val y: Float)

/** Where the route ends. The same point as JKIA in the backend's solver. */
val JKIA_POINT = MapPoint(lat = -1.3192, lon = 36.9278)

/**
 * Fits [points] into a [width] by [height] box with [margin] around it. One scale for both
 * axes, so the route keeps its shape. Treating degrees as flat is fine at Nairobi's scale,
 * right on the equator. North is up, and y grows downwards on screen.
 */
fun projectRoute(points: List<MapPoint>, width: Float, height: Float, margin: Float): List<MapXy> {
    if (points.isEmpty()) return emptyList()
    val minLat = points.minOf { it.lat }
    val maxLat = points.maxOf { it.lat }
    val minLon = points.minOf { it.lon }
    val maxLon = points.maxOf { it.lon }
    val spanLon = maxLon - minLon
    val spanLat = maxLat - minLat
    val usableWidth = width - 2 * margin
    val usableHeight = height - 2 * margin
    val scale = when {
        spanLon == 0.0 && spanLat == 0.0 -> 0.0
        spanLon == 0.0 -> usableHeight / spanLat
        spanLat == 0.0 -> usableWidth / spanLon
        else -> min(usableWidth / spanLon, usableHeight / spanLat)
    }
    val left = (width - spanLon * scale) / 2
    val top = (height - spanLat * scale) / 2
    return points.map {
        MapXy(
            x = (left + (it.lon - minLon) * scale).toFloat(),
            y = (top + (maxLat - it.lat) * scale).toFloat()
        )
    }
}

/**
 * The route as a schematic: real stop positions joined in order, ending at JKIA. It has no
 * street map, so it needs no Maps key and no signal, and costs nothing on 2G. [Navigate]
 * hands over to the phone's maps app for directions.
 */
class RouteMapView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) :
    View(context, attrs) {
    private var stops: List<MapPoint> = emptyList()

    /** Position in [stops] of the next pickup, or -1. Earlier stops are drawn as done. */
    private var nextIndex = -1

    private val density = resources.displayMetrics.density
    private val grid = Paint().apply {
        color = color(com.google.android.material.R.attr.colorOutlineVariant)
        strokeWidth = density
    }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = color(com.google.android.material.R.attr.colorOnSurfaceVariant)
        style = Paint.Style.STROKE
        strokeWidth = 2 * density
        pathEffect = DashPathEffect(floatArrayOf(6 * density, 5 * density), 0f)
    }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = color(com.google.android.material.R.attr.colorOnSurface)
        style = Paint.Style.STROKE
        strokeWidth = 2 * density
    }
    private val surface = color(com.google.android.material.R.attr.colorSurface)
    private val red = color(androidx.appcompat.R.attr.colorPrimary)
    private val ink = color(com.google.android.material.R.attr.colorOnSurface)

    private fun color(attr: Int) = MaterialColors.getColor(this, attr)

    fun show(stops: List<MapPoint>, nextIndex: Int) {
        this.stops = stops
        this.nextIndex = nextIndex
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        drawGrid(canvas)
        if (stops.isEmpty()) return
        val all = projectRoute(stops + JKIA_POINT, width.toFloat(), height.toFloat(), 28 * density)
        val path = Path()
        all.forEachIndexed { i, p -> if (i == 0) path.moveTo(p.x, p.y) else path.lineTo(p.x, p.y) }
        canvas.drawPath(path, line)

        all.dropLast(1).forEachIndexed { i, p -> drawStop(canvas, p, i) }
        val jkia = all.last()
        val half = 9 * density
        fill.color = ink
        canvas.drawRoundRect(
            jkia.x - half,
            jkia.y - half,
            jkia.x + half,
            jkia.y + half,
            3 * density,
            3 * density,
            fill
        )
    }

    private fun drawGrid(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        for (i in 1..3) canvas.drawLine(w * i / 4, 0f, w * i / 4, h, grid)
        for (i in 1..2) canvas.drawLine(0f, h * i / 3, w, h * i / 3, grid)
    }

    private fun drawStop(canvas: Canvas, at: MapXy, index: Int) {
        val isNext = index == nextIndex
        val isDone = nextIndex < 0 || index < nextIndex
        val radius = (if (isNext) 9 else 6) * density
        fill.color = when {
            isNext -> red
            isDone -> ink
            else -> surface
        }
        canvas.drawCircle(at.x, at.y, radius, fill)
        canvas.drawCircle(at.x, at.y, radius, ring)
    }
}
