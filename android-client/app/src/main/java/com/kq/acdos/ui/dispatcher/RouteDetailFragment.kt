package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.os.bundleOf
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.Chip
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.RouteStop
import com.kq.acdos.data.latePickups
import com.kq.acdos.data.orderedRoutes
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.routeStops
import com.kq.acdos.data.slackMinutes
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.driver.shortZone
import kotlin.math.abs
import kotlinx.coroutines.launch

/**
 * One route's stops, with each crew member's report time next to the pickup
 * so the slack is visible (Figma 2:132). The API has no coordinates or driver
 * for a route, so there is no map or driver chip, and no way to message a
 * driver: all messages go through the dispatcher's crew inbox.
 */
class RouteDetailFragment : Fragment(R.layout.fragment_route_detail) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val routeId = requireArguments().getString(ARG_ROUTE)

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val board = state.board
                    val routes = board?.let(::orderedRoutes).orEmpty()
                    val index = routes.indexOfFirst { it.routeId == routeId }
                    // Gone after a re-plan replaced it, or the day changed.
                    if (board != null && index >= 0) {
                        val route = routes[index]
                        home.showTitle(routeName(index + 1, route.vehiclePlate))
                        showChips(view, board, route)
                        showStops(view, board, route)
                    } else if (board != null) {
                        home.close()
                    }
                }
            }
        }
    }

    private fun showChips(view: View, board: DayBoard, route: DispatcherRouteDto) {
        val capacity = board.vehicles.firstOrNull { it.id == route.vehicleId }?.capacity
        view.findViewById<Chip>(R.id.seats_chip).apply {
            isVisible = capacity != null
            text = capacity?.let {
                getString(R.string.dispatch_seats_used, route.nodes.size, it)
            }
        }
        val onRoute = route.nodes.map { it.pickupRequestId }
        val late = latePickups(board).count { it in onRoute }
        view.findViewById<Chip>(R.id.on_time_chip).isVisible = late == 0
        view.findViewById<Chip>(R.id.late_chip).apply {
            isVisible = late > 0
            text = resources.getQuantityString(R.plurals.dispatch_crew_late, late, late)
        }
    }

    private fun showStops(view: View, board: DayBoard, route: DispatcherRouteDto) {
        val rows = view.findViewById<LinearLayout>(R.id.stops)
        rows.removeAllViews()
        for (stop in routeStops(board, route)) {
            rows.addRow(
                title = stop.zoneLabel?.let {
                    getString(R.string.dispatch_stop_title, stop.seqOrder, shortZone(it))
                } ?: stop.seqOrder.toString(),
                subtitle = stopSubtitle(stop),
                value = Times.shortClock(stop.pickupAt),
                lead = stop.seqOrder.toString()
            )
        }
        rows.addRow(
            title = getString(R.string.dispatch_jkia),
            subtitle = slackText(slackMinutes(board, route)),
            value = Times.shortClock(route.plannedArrival)
        )
    }

    private fun stopSubtitle(stop: RouteStop): String {
        val crew = stop.crewName ?: getString(R.string.dispatch_unknown_crew)
        val report = stop.reportTime ?: return crew
        return getString(R.string.dispatch_stop_subtitle, crew, Times.shortClock(report))
    }

    private fun slackText(slack: Long?): String = when {
        slack == null -> getString(R.string.dispatch_arrive)
        slack >= 0 -> getString(R.string.dispatch_slack, slack)
        else -> getString(R.string.dispatch_slack_late, abs(slack))
    }

    companion object {
        private const val ARG_ROUTE = "route"

        fun of(routeId: String) =
            RouteDetailFragment().apply { arguments = bundleOf(ARG_ROUTE to routeId) }
    }
}
