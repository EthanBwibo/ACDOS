package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.orderedRoutes
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.routeStops
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.driver.shortZone
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.launch

/**
 * The Routes tab (#230): the day's routes, each opening its detail and map
 * inside this tab. The list was on the hub before the tabs.
 */
class RoutesFragment : Fragment(R.layout.fragment_dispatch_list) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    private val dayFormat = DateTimeFormatter.ofPattern("EEE d MMM", Locale.UK)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val rows = view.findViewById<LinearLayout>(R.id.rows)
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    home.showTitle(
                        getString(R.string.dispatch_routes_title, dayFormat.format(state.date))
                    )
                    rows.removeAllViews()
                    // Nothing loaded isn't "no routes": the banner says the day didn't load.
                    val board = state.board ?: return@collect
                    val routes = orderedRoutes(board)
                    routes.forEachIndexed { index, route ->
                        rows.addRow(
                            title = routeName(index + 1, route.vehiclePlate),
                            subtitle = routeSubtitle(board, route),
                            value = Times.shortClock(route.plannedArrival)
                        ) { home.open(RouteDetailFragment.of(route.routeId)) }
                    }
                    if (routes.isEmpty()) rows.addRow(getString(R.string.dispatch_no_routes))
                }
            }
        }
    }

    private fun routeSubtitle(board: DayBoard, route: DispatcherRouteDto): String {
        val stops = routeStops(board, route)
        val zones = stops.mapNotNull { it.zoneLabel }.map(::shortZone).distinct()
        return getString(R.string.dispatch_route_subtitle, stops.size, zones.joinToString(" › "))
    }
}
