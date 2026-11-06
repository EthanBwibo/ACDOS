package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.Chip
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.orderedRoutes
import com.kq.acdos.data.planSummary
import com.kq.acdos.data.planWindow
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.DispatcherRouteDto
import com.kq.acdos.data.routeStops
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.driver.shortZone
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * One Nairobi day at a glance (Figma 2:26). Every card drills down: a tile to
 * its list, the plan to the job screen, an alert to the re-plan or messages,
 * a route to its detail.
 */
class DispatchHubFragment : Fragment(R.layout.fragment_dispatch_hub) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }
    private val inbox: InboxViewModel by activityViewModels { InboxViewModel.Factory }

    private val dayFormat = DateTimeFormatter.ofPattern("EEE d MMM", Locale.UK)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        view.findViewById<Button>(R.id.previous_day).setOnClickListener { viewModel.showDay(-1) }
        view.findViewById<Button>(R.id.next_day).setOnClickListener { viewModel.showDay(1) }
        view.findViewById<Button>(R.id.run_optimisation).setOnClickListener {
            home.open(OptimisationRunFragment())
        }
        val pickups = view.findViewById<View>(R.id.tile_pickups)
        val vehicles = view.findViewById<View>(R.id.tile_vehicles)
        pickups.setOnClickListener { home.open(PickupsFragment()) }
        vehicles.setOnClickListener { home.open(VehiclesFragment()) }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(viewModel.state, inbox.messages, ::Pair).collect { (state, messages) ->
                    home.showTitle(
                        getString(R.string.dispatch_title, dayFormat.format(state.date))
                    )
                    showTiles(view, state.board)
                    showPlan(view, state)
                    showAlerts(view, state, messages)
                    showRoutes(view, state.board)
                }
            }
        }
    }

    private fun showTiles(view: View, board: DayBoard?) {
        tile(view, R.id.tile_pickups, board?.pickups?.size, R.string.dispatch_tile_pickups)
        tile(view, R.id.tile_vehicles, board?.vehicles?.size, R.string.dispatch_tile_vehicles)
        tile(view, R.id.tile_late, board?.let { planSummary(it).late }, R.string.dispatch_tile_late)
    }

    private fun tile(view: View, id: Int, count: Int?, label: Int) {
        val tile = view.findViewById<View>(id)
        tile.findViewById<TextView>(R.id.stat_value).text = count?.toString().orEmpty()
        tile.findViewById<TextView>(R.id.stat_label).setText(label)
    }

    private fun showPlan(view: View, state: DispatcherUiState) {
        val board = state.board
        view.findViewById<TextView>(R.id.plan_title).text = board?.let(::planWindow)?.let {
            getString(
                R.string.dispatch_plan_window,
                Times.shortClock(it.first),
                Times.shortClock(it.second)
            )
        } ?: getString(R.string.dispatch_plan)
        view.findViewById<Chip>(R.id.plan_chip).setText(
            when {
                state.job.isActive -> R.string.dispatch_plan_running
                board?.routes.isNullOrEmpty() -> R.string.dispatch_plan_none
                else -> R.string.dispatch_plan_ready
            }
        )
        view.findViewById<TextView>(R.id.plan_summary).apply {
            text = board?.takeIf { it.routes.isNotEmpty() }?.let { summaryText(it) }
            isVisible = text.isNotEmpty()
        }
        view.findViewById<Button>(R.id.run_optimisation).isEnabled = board != null
    }

    private fun summaryText(board: DayBoard): String {
        val plan = planSummary(board)
        val late = if (plan.late == 0) {
            getString(R.string.dispatch_all_on_time)
        } else {
            resources.getQuantityString(R.plurals.dispatch_crew_late, plan.late, plan.late)
        }
        return getString(
            R.string.dispatch_plan_summary,
            plan.plannedDriveMinutes,
            plan.vansUsed,
            plan.vans,
            late
        )
    }

    private fun showAlerts(view: View, state: DispatcherUiState, messages: List<CrewMessageDto>?) {
        val rows = view.findViewById<LinearLayout>(R.id.alerts)
        rows.removeAllViews()
        state.replan?.let { replan ->
            rows.addRow(
                title = getString(replan.label, replan.subject),
                subtitle = resources.getQuantityString(
                    R.plurals.dispatch_to_replan,
                    replan.pickupIds.size,
                    replan.pickupIds.size
                ),
                value = getString(R.string.dispatch_replan_link)
            ) { home.open(ReplanFragment()) }
        }
        val unread = messages.orEmpty().count { it.readAt == null }
        rows.addRow(
            title = getString(R.string.dispatch_messages),
            subtitle = resources.getQuantityString(R.plurals.dispatch_unread, unread, unread),
            value = getString(R.string.dispatch_open_link, unread)
        ) { home.open(MessagesFragment()) }
    }

    private fun showRoutes(view: View, board: DayBoard?) {
        val rows = view.findViewById<LinearLayout>(R.id.routes)
        rows.removeAllViews()
        val routes = board?.let(::orderedRoutes).orEmpty()
        routes.forEachIndexed { index, route ->
            rows.addRow(
                title = routeName(index + 1, route.vehiclePlate),
                subtitle = routeSubtitle(board!!, route),
                value = Times.shortClock(route.plannedArrival)
            ) { home.open(RouteDetailFragment.of(route.routeId)) }
        }
        if (routes.isEmpty()) rows.addRow(getString(R.string.dispatch_none))
    }

    private fun routeSubtitle(board: DayBoard, route: DispatcherRouteDto): String {
        val stops = routeStops(board, route)
        val zones = stops.mapNotNull { it.zoneLabel }.map(::shortZone).distinct()
        return getString(R.string.dispatch_route_subtitle, stops.size, zones.joinToString(" › "))
    }
}
