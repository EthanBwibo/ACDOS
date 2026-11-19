package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.data.remote.LatLonDto
import com.kq.acdos.ui.driver.RouteMapView
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker

/**
 * A pin on the osmdroid map (#253), for Add pickup's Different location or for a
 * crew member's Set home. Tapping the map drops the pin, and each drop asks the
 * server once for the nearest pickup zone and distance (the import's PostGIS
 * check): never while moving, to keep it to one request on 2G. A point beyond
 * 10 km of every zone can't be used.
 */
class PinPickerFragment : Fragment(R.layout.fragment_pin_picker) {
    private val entry: PickupEntryViewModel by activityViewModels { PickupEntryViewModel.Factory }
    private val dispatcher: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    private val forHome get() = requireArguments().getBoolean(ARG_SET_HOME)

    private lateinit var map: RouteMapView
    private val marker by lazy { Marker(map).apply { setAnchor(0.5f, 1f) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The pin lives in the ViewModel, so it survives a rotation; a new screen starts empty.
        if (savedInstanceState == null) entry.startPin()
    }

    override fun onStart() {
        super.onStart()
        home.showTitle(
            if (forHome) {
                getString(R.string.pin_set_home, entry.crewDetail.value?.name.orEmpty())
            } else {
                getString(R.string.pin_pickup_point)
            }
        )
        map.onResume()
    }

    override fun onStop() {
        map.onPause()
        super.onStop()
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        map = view.findViewById(R.id.map)
        val start = entry.pin.value.point ?: NAIROBI
        map.controller.setZoom(START_ZOOM)
        map.controller.setCenter(GeoPoint(start.lat, start.lon))
        map.overlays += MapEventsOverlay(object : MapEventsReceiver {
            override fun singleTapConfirmedHelper(point: GeoPoint): Boolean {
                entry.placePin(LatLonDto(point.latitude, point.longitude))
                return true
            }

            override fun longPressHelper(point: GeoPoint) = false
        })
        view.findViewById<Button>(R.id.use_point).apply {
            setText(if (forHome) R.string.pin_save_home else R.string.pin_use_point)
            setOnClickListener { use() }
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(entry.pin, entry.setHome, ::Pair).collect { (pin, setHome) ->
                    show(view, pin, setHome)
                }
            }
        }
    }

    private fun show(view: View, pin: PinState, setHome: SetHomeState) {
        pin.point?.let { point ->
            marker.position = GeoPoint(point.lat, point.lon)
            if (marker !in map.overlays) map.overlays += marker
            map.invalidate()
        }
        val nearest = pin.nearest
        view.findViewById<TextView>(R.id.preview).text = when {
            pin.point == null -> getString(R.string.pin_tap_hint)

            pin.checking -> getString(R.string.pin_checking)

            nearest != null -> getString(
                pinPreviewText(nearest),
                nearest.zoneLabel,
                kmText(nearest)
            )

            else -> ""
        }
        val failure = if (forHome) setHome.failure ?: pin.failure else pin.failure
        view.findViewById<TextView>(R.id.failure).apply {
            text = failure?.let { getString(it.text, it.detail) }
            isVisible = failure != null
        }
        view.findViewById<Button>(R.id.use_point).isEnabled = pin.usable && !setHome.busy

        val saved = setHome.saved
        if (forHome && saved != null) {
            // The board's pickup zones come from homes, so it reloads.
            dispatcher.load()
            val root = requireActivity().findViewById<View>(R.id.main)
            val name = entry.crewDetail.value?.name.orEmpty()
            Snackbar.make(
                root,
                getString(R.string.pin_home_saved, name, saved.zoneLabel),
                Snackbar.LENGTH_LONG
            ).setAnchorView(R.id.bottom_nav).show()
            entry.openCrew(entry.crewDetail.value ?: return)
            home.close()
        }
    }

    private fun use() {
        if (forHome) {
            entry.saveHome()
        } else {
            entry.usePin()
            home.close()
        }
    }

    companion object {
        private const val ARG_SET_HOME = "set_home"
        private const val START_ZOOM = 12.0

        /** The CBD: the map opens on it, with the zones around. */
        private val NAIROBI = LatLonDto(lat = -1.2864, lon = 36.8172)

        fun forAddPickup() = PinPickerFragment().apply {
            arguments = Bundle().apply { putBoolean(ARG_SET_HOME, false) }
        }

        /** For the crew member on the Crew detail screen. */
        fun forSetHome() = PinPickerFragment().apply {
            arguments = Bundle().apply { putBoolean(ARG_SET_HOME, true) }
        }
    }
}
