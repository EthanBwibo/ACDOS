package com.kq.acdos.ui.driver

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.useThemeColors
import java.util.Locale
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * One job at a time: the next pickup and its big action, from the Room cache, so it works
 * with no signal. Pull to refresh asks the server; the screen updates when Room does.
 */
class RouteFragment : Fragment(R.layout.fragment_route) {
    private val viewModel: RouteViewModel by viewModels {
        viewModelFactory {
            initializer {
                RouteViewModel(
                    container.database.driverRouteDao(),
                    container.database.pendingPickupEventDao(),
                    driverId = { container.authRepository.storedSessionUserId() }
                )
            }
        }
    }

    private val refresh: RouteRefreshViewModel by activityViewModels {
        RouteRefreshViewModel.Factory
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val content = view.findViewById<View>(R.id.route)
        val empty = view.findViewById<TextView>(R.id.empty)
        val syncChip = view.findViewById<TextView>(R.id.sync_chip)
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.useThemeColors()
        swipe.setOnRefreshListener {
            container.uploadPickupEvents()
            if (!refresh.refreshByPull()) swipe.isRefreshing = false
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val route = state as? RouteUiState.Route
                    content.isVisible = route != null
                    empty.isVisible = state == RouteUiState.NoRoute
                    if (route == null) {
                        driverHome.showHeader(null, null)
                    } else {
                        showRoute(view, route)
                    }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(container.connectivity.network, viewModel.state) { network, state ->
                    val queued = (state as? RouteUiState.Route)?.queued ?: 0
                    getString(syncChipText(network.isOnline, queued), queued)
                }.collect { syncChip.text = it }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(
                    refresh.refreshing,
                    refresh.firstLoadPending,
                    viewModel.state,
                    ::routeSpinner
                ).collect { swipe.isRefreshing = it }
            }
        }
        // Only seen when nothing is cached: with a route on screen, a failed
        // refresh stays quiet and the "Updated" time shows its age.
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(refresh.firstLoadPending, refresh.lastFailure, ::emptyRouteMessage)
                    .collect { empty.setText(it) }
            }
        }
    }

    private val container get() = (requireActivity().application as AcdosApplication).container

    private val driverHome get() = requireActivity() as DriverHomeActivity

    private fun showRoute(view: View, route: RouteUiState.Route) {
        val progress = routeProgress(route.stops)
        val updated = getString(R.string.route_updated, Times.clock(route.updatedAt))
        driverHome.showHeader(route.plate, updated)
        view.findViewById<TextView>(R.id.progress_chip).text =
            getString(R.string.route_progress, progress.pickedUp, route.stops.size)

        val map = view.findViewById<RouteMapView>(R.id.map)
        map.contentDescription = getString(R.string.route_map_description, route.stops.size)
        val nextIndex = route.stops.indexOf(progress.next)
        map.show(route.stops.map { MapPoint(it.lat, it.lon) }, nextIndex)

        view.findViewById<View>(R.id.next_card).isVisible = progress.next != null
        view.findViewById<View>(R.id.all_done).isVisible = progress.next == null
        progress.next?.let { showNext(view, it) }

        view.findViewById<View>(R.id.then_label).isVisible = progress.then.isNotEmpty()
        view.findViewById<View>(R.id.then_card).isVisible = progress.then.isNotEmpty()
        val rows = view.findViewById<LinearLayout>(R.id.then_rows)
        rows.removeAllViews()
        for (stop in progress.then) {
            val row = LayoutInflater.from(rows.context).inflate(R.layout.item_list_row, rows, false)
            row.findViewById<TextView>(R.id.row_lead).text = stop.number.toString()
            row.findViewById<TextView>(R.id.row_title).text = zoneName(stop)
            row.findViewById<TextView>(R.id.row_subtitle).text = stop.crewName
            row.findViewById<TextView>(R.id.row_value).text = Times.clock(stop.pickupTime)
            rows.addView(row)
        }
    }

    private fun showNext(view: View, stop: StopRow) {
        view.findViewById<TextView>(R.id.next_title).text =
            getString(R.string.route_next_title, zoneName(stop), stop.crewName)
        val time = view.findViewById<View>(R.id.next_time)
        time.findViewById<TextView>(R.id.detail_label).setText(R.string.route_pickup_by)
        time.findViewById<TextView>(R.id.detail_value).text = Times.clock(stop.pickupTime)

        val warning = view.findViewById<TextView>(R.id.status_warning)
        warning.isVisible = stop.progress != null
        warning.text = stop.progress?.let(::statusText)

        view.findViewById<Button>(R.id.navigate).setOnClickListener { navigateTo(stop) }
        view.findViewById<Button>(R.id.confirm).setOnClickListener {
            startActivity(ConfirmPickupActivity.intent(requireContext(), stop.routeNodeId))
        }
    }

    private fun zoneName(stop: StopRow) =
        stop.zoneLabel?.let(::shortZone) ?: getString(R.string.route_zone_unknown)

    private fun statusText(progress: StopProgress): String {
        progress.conflict?.let { return getString(R.string.route_status_rejected, it) }
        val label = getString(progressLabel(progress))
        if (progress.sent) return label
        return getString(R.string.route_status_not_sent, label)
    }

    /** Opens the stop in the phone's maps app, with a pin labelled by the crew name. */
    private fun navigateTo(stop: StopRow) {
        // Locale.ROOT: a decimal point whatever the phone's language.
        val point = String.format(Locale.ROOT, "%.5f,%.5f", stop.lat, stop.lon)
        val uri = Uri.parse("geo:0,0?q=$point(${Uri.encode(stop.crewName)})")
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(requireContext(), R.string.route_no_maps_app, Toast.LENGTH_LONG).show()
        }
    }
}
