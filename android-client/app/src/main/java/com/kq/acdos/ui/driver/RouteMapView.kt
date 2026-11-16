package com.kq.acdos.ui.driver

import android.content.Context
import android.content.res.Configuration.UI_MODE_NIGHT_MASK
import android.content.res.Configuration.UI_MODE_NIGHT_YES
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.BitmapDrawable
import android.util.AttributeSet
import android.util.TypedValue
import android.view.MotionEvent
import android.view.ViewOutlineProvider
import com.google.android.material.color.MaterialColors
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.CustomZoomButtonsController
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.CopyrightOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline

/** A place on the route, in degrees. */
data class MapPoint(val lat: Double, val lon: Double)

/** Where the route ends. The same point as JKIA in the backend's solver. */
val JKIA_POINT = MapPoint(lat = -1.3192, lon = 36.9278)

/** How a stop is drawn: picked up is grey, the next pickup is KQ red, the rest are plain. */
enum class StopMark { PICKED_UP, NEXT, AHEAD }

/** A numbered pickup on the map. */
data class MapStop(val point: MapPoint, val number: Int, val mark: StopMark)

/**
 * The line the map draws: the stops in visiting order, then JKIA. It joins the
 * stops straight and is not road geometry; road routing would need a routing
 * service, which is out of scope. The times on screen come from the Random Forest.
 */
fun routeLine(stops: List<MapStop>): List<MapPoint> = stops.map { it.point } + JKIA_POINT

/**
 * Dark mode for the light OSM tiles: light becomes dark but each colour keeps
 * its hue, so parks stay green and main roads stay orange. Each row is minus a
 * 180 degree hue rotation (its weights add up to 1), plus 255: the hue turns
 * back round while the lightness flips. Scaled by 0.8 so the tiles stay dim.
 */
private val DARK_TILES = ColorMatrixColorFilter(
    ColorMatrix(
        floatArrayOf(
            0.574f, -1.430f, -0.144f, 0f, 255f,
            -0.426f, -0.430f, -0.144f, 0f, 255f,
            -0.426f, -1.430f, 0.856f, 0f, 255f,
            0f, 0f, 0f, 1f, 0f
        )
    ).apply { postConcat(ColorMatrix().apply { setScale(0.8f, 0.8f, 0.8f, 1f) }) }
)

/**
 * The route on OpenStreetMap tiles (#227): numbered stops, a JKIA marker and the
 * line between them, framed to fit. No key and no billing. Tiles are cached on the
 * phone, so ones already seen show again with a weak signal or none.
 */
class RouteMapView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) :
    MapView(context, attrs) {

    /** The dispatcher's copy only shows the route: no panning or zooming. */
    var readOnly = false
        set(value) {
            field = value
            setMultiTouchControls(!value)
        }

    private val density = resources.displayMetrics.density

    /** The line last framed, so a driver's own zoom survives updates to the same route. */
    private var framed: List<MapPoint>? = null
    private var pendingFrame: BoundingBox? = null

    init {
        setTileSource(TileSourceFactory.MAPNIK)
        isTilesScaledToDpi = true
        setMultiTouchControls(true)
        zoomController.setVisibility(CustomZoomButtonsController.Visibility.NEVER)
        minZoomLevel = MIN_ZOOM
        maxZoomLevel = MAX_ZOOM
        // Round corners from the bg_map background.
        outlineProvider = ViewOutlineProvider.BACKGROUND
        clipToOutline = true
        overlayManager.tilesOverlay.apply {
            loadingBackgroundColor = color(com.google.android.material.R.attr.colorSurfaceContainer)
            loadingLineColor = color(com.google.android.material.R.attr.colorOutlineVariant)
            val night = resources.configuration.uiMode and UI_MODE_NIGHT_MASK == UI_MODE_NIGHT_YES
            if (night) setColorFilter(DARK_TILES)
        }
        addOnFirstLayoutListener { _, _, _, _, _ ->
            pendingFrame?.let { zoomToBoundingBox(it, false, framePadding()) }
            pendingFrame = null
        }
    }

    private fun color(attr: Int) = MaterialColors.getColor(this, attr)

    fun show(stops: List<MapStop>) {
        val line = routeLine(stops)
        overlays.clear()
        overlays += Polyline(this).apply {
            setPoints(line.map { GeoPoint(it.lat, it.lon) })
            infoWindow = null
            outlinePaint.apply {
                color = color(com.google.android.material.R.attr.colorOnSurfaceVariant)
                strokeWidth = 3 * density
                strokeCap = Paint.Cap.ROUND
                // Dashed, so it doesn't read as the road the van takes.
                pathEffect = DashPathEffect(floatArrayOf(8 * density, 6 * density), 0f)
            }
        }
        stops.forEach { overlays += marker(it.point, stopIcon(it), "${it.number}") }
        overlays += marker(JKIA_POINT, jkiaIcon(), JKIA)
        overlays += CopyrightOverlay(context).apply {
            setTextColor(color(com.google.android.material.R.attr.colorOnSurface))
        }
        if (line != framed) frame(line)
        invalidate()
    }

    /** Frames the whole route again, after the driver has panned or zoomed away. */
    fun recentre() {
        framed?.let(::frame)
    }

    private fun frame(line: List<MapPoint>) {
        framed = line
        val box = BoundingBox.fromGeoPointsSafe(line.map { GeoPoint(it.lat, it.lon) })
        if (isLayoutOccurred) zoomToBoundingBox(box, false, framePadding()) else pendingFrame = box
    }

    private fun framePadding() = (FRAME_PADDING_DP * density).toInt()

    private fun marker(at: MapPoint, icon: Bitmap, label: String) = Marker(this).apply {
        position = GeoPoint(at.lat, at.lon)
        this.icon = BitmapDrawable(resources, icon)
        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
        title = label
        infoWindow = null
        // Tapping a marker would otherwise pan the map to it.
        setOnMarkerClickListener { _, _ -> true }
    }

    private fun stopIcon(stop: MapStop): Bitmap {
        val onSurface = color(com.google.android.material.R.attr.colorOnSurface)
        val surface = color(com.google.android.material.R.attr.colorSurface)
        val (fill, ink) = when (stop.mark) {
            StopMark.NEXT -> color(androidx.appcompat.R.attr.colorPrimary) to
                color(com.google.android.material.R.attr.colorOnPrimary)

            StopMark.PICKED_UP -> color(com.google.android.material.R.attr.colorOutline) to surface

            StopMark.AHEAD -> surface to onSurface
        }
        val size = ((if (stop.mark == StopMark.NEXT) 30 else 24) * density).toInt()
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val half = size / 2f
        val ring = 2 * density
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.color = if (stop.mark == StopMark.PICKED_UP) surface else onSurface
        canvas.drawCircle(half, half, half, paint)
        paint.color = fill
        canvas.drawCircle(half, half, half - ring, paint)
        drawLabel(canvas, "${stop.number}", half, half, ink, 12)
        return bitmap
    }

    private fun jkiaIcon(): Bitmap {
        val width = (40 * density).toInt()
        val height = (22 * density).toInt()
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        paint.color = color(com.google.android.material.R.attr.colorOnSurface)
        val corner = 4 * density
        canvas.drawRoundRect(
            RectF(0f, 0f, width.toFloat(), height.toFloat()),
            corner,
            corner,
            paint
        )
        val surface = color(com.google.android.material.R.attr.colorSurface)
        drawLabel(canvas, JKIA, width / 2f, height / 2f, surface, 10)
        return bitmap
    }

    private fun drawLabel(canvas: Canvas, text: String, x: Float, y: Float, ink: Int, sp: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = ink
            textAlign = Paint.Align.CENTER
            typeface = Typeface.DEFAULT_BOLD
            textSize = TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_SP,
                sp.toFloat(),
                resources.displayMetrics
            )
        }
        canvas.drawText(text, x, y - (paint.ascent() + paint.descent()) / 2, paint)
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        // Read-only: let the screen scroll past it.
        if (readOnly) return false
        // Panning the map shouldn't scroll the screen or start a pull to refresh.
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            parent?.requestDisallowInterceptTouchEvent(true)
        }
        return super.dispatchTouchEvent(event)
    }

    private companion object {
        const val JKIA = "JKIA"
        const val MIN_ZOOM = 9.0
        const val MAX_ZOOM = 18.0
        const val FRAME_PADDING_DP = 36
    }
}
