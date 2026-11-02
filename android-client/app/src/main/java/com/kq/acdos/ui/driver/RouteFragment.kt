package com.kq.acdos.ui.driver

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
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
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.ui.Times
import java.util.Locale
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * The driver's stops in order, from the Room cache, so it works with no signal.
 * Pull to refresh asks the server; the list updates when Room does.
 */
class RouteFragment : Fragment(R.layout.fragment_route) {
    private val viewModel: RouteViewModel by viewModels {
        viewModelFactory {
            initializer {
                RouteViewModel(
                    container.database.driverRouteDao(),
                    container.database.pendingPickupEventDao(),
                    driverId = { container.authRepository.storedSessionUserId() },
                    outbox = container.pickupEventOutbox,
                    upload = container::uploadPickupEvents
                )
            }
        }
    }

    private val refresh: RouteRefreshViewModel by activityViewModels {
        RouteRefreshViewModel.Factory
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val header = view.findViewById<View>(R.id.route_header)
        val plate = view.findViewById<TextView>(R.id.plate)
        val updated = view.findViewById<TextView>(R.id.updated)
        val empty = view.findViewById<TextView>(R.id.empty)
        val adapter = StopAdapter(::navigateTo, viewModel::confirmPickup, ::askWhatWentWrong)
        val stops = view.findViewById<RecyclerView>(R.id.stops).also {
            it.layoutManager = LinearLayoutManager(requireContext())
            it.adapter = adapter
        }
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.setOnRefreshListener {
            container.uploadPickupEvents()
            if (!refresh.refreshByPull()) swipe.isRefreshing = false
        }
        // The swipe's child is the whole column, so ask the list: a pull only
        // refreshes when the list is already scrolled to the top.
        swipe.setOnChildScrollUpCallback { _, _ -> stops.canScrollVertically(-1) }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val route = state as? RouteUiState.Route
                    header.isVisible = route != null
                    empty.isVisible = state == RouteUiState.NoRoute
                    if (route != null) {
                        plate.text = route.plate
                        val time = Times.clock(route.updatedAt)
                        updated.text = getString(R.string.route_updated, time)
                    }
                    adapter.submitList(route?.stops.orEmpty())
                }
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

    /** The three exception types the server takes; the choice is recorded at once. */
    private fun askWhatWentWrong(stop: StopRow) {
        val problems = listOf(
            PickupExceptionType.NO_SHOW to R.string.route_problem_no_show,
            PickupExceptionType.VEHICLE_ISSUE to R.string.route_problem_vehicle_issue,
            PickupExceptionType.TRAFFIC_DELAY to R.string.route_problem_traffic_delay
        )
        MaterialAlertDialogBuilder(requireContext())
            .setTitle(getString(R.string.route_problem_title, stop.crewName))
            .setItems(problems.map { getString(it.second) }.toTypedArray()) { _, which ->
                viewModel.reportProblem(stop, problems[which].first)
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
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

private class StopAdapter(
    private val onNavigate: (StopRow) -> Unit,
    private val onPickedUp: (StopRow) -> Unit,
    private val onProblem: (StopRow) -> Unit
) : ListAdapter<StopRow, StopAdapter.Holder>(Diff) {

    class Holder(view: View) : RecyclerView.ViewHolder(view) {
        val number: TextView = view.findViewById(R.id.number)
        val crewName: TextView = view.findViewById(R.id.crew_name)
        val zone: TextView = view.findViewById(R.id.zone)
        val pickupTime: TextView = view.findViewById(R.id.pickup_time)
        val navigate: Button = view.findViewById(R.id.navigate)
        val status: TextView = view.findViewById(R.id.status)
        val actions: View = view.findViewById(R.id.actions)
        val pickedUp: Button = view.findViewById(R.id.picked_up)
        val problem: Button = view.findViewById(R.id.problem)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = Holder(
        LayoutInflater.from(parent.context).inflate(R.layout.item_route_stop, parent, false)
    )

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val stop = getItem(position)
        val context = holder.itemView.context
        holder.number.text = stop.number.toString()
        holder.crewName.text = stop.crewName
        holder.zone.text = stop.zoneLabel ?: context.getString(R.string.route_zone_unknown)
        holder.pickupTime.text =
            context.getString(R.string.route_pickup_at, Times.clock(stop.pickupTime))
        holder.navigate.setOnClickListener { onNavigate(stop) }
        holder.pickedUp.setOnClickListener { onPickedUp(stop) }
        holder.problem.setOnClickListener { onProblem(stop) }

        val progress = stop.progress
        holder.status.isVisible = progress != null
        holder.status.text = progress?.let { statusText(context, it) }
        holder.actions.isVisible = progress?.done != true
    }

    private fun statusText(context: Context, progress: StopProgress): String {
        progress.conflict?.let { return context.getString(R.string.route_status_rejected, it) }
        val label = context.getString(progressLabel(progress))
        if (progress.sent) return label
        return context.getString(R.string.route_status_not_sent, label)
    }

    private object Diff : DiffUtil.ItemCallback<StopRow>() {
        override fun areItemsTheSame(oldItem: StopRow, newItem: StopRow) =
            oldItem.routeNodeId == newItem.routeNodeId

        override fun areContentsTheSame(oldItem: StopRow, newItem: StopRow) = oldItem == newItem
    }
}
