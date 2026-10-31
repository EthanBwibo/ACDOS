package com.kq.acdos.ui.driver

import android.content.ActivityNotFoundException
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
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.ui.Times
import java.util.Locale
import kotlinx.coroutines.launch

/** The driver's stops in order, from the Room cache, so it works with no signal. */
class RouteFragment : Fragment(R.layout.fragment_route) {
    private val viewModel: RouteViewModel by viewModels {
        viewModelFactory {
            initializer {
                val container = (requireActivity().application as AcdosApplication).container
                RouteViewModel(container.database.driverRouteDao())
            }
        }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val header = view.findViewById<View>(R.id.route_header)
        val plate = view.findViewById<TextView>(R.id.plate)
        val updated = view.findViewById<TextView>(R.id.updated)
        val empty = view.findViewById<TextView>(R.id.empty)
        val adapter = StopAdapter(::navigateTo)
        view.findViewById<RecyclerView>(R.id.stops).also {
            it.layoutManager = LinearLayoutManager(requireContext())
            it.adapter = adapter
        }

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

private class StopAdapter(private val onNavigate: (StopRow) -> Unit) :
    ListAdapter<StopRow, StopAdapter.Holder>(Diff) {

    class Holder(view: View) : RecyclerView.ViewHolder(view) {
        val number: TextView = view.findViewById(R.id.number)
        val crewName: TextView = view.findViewById(R.id.crew_name)
        val zone: TextView = view.findViewById(R.id.zone)
        val pickupTime: TextView = view.findViewById(R.id.pickup_time)
        val navigate: Button = view.findViewById(R.id.navigate)
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
    }

    private object Diff : DiffUtil.ItemCallback<StopRow>() {
        override fun areItemsTheSame(oldItem: StopRow, newItem: StopRow) =
            oldItem.routeNodeId == newItem.routeNodeId

        override fun areContentsTheSame(oldItem: StopRow, newItem: StopRow) = oldItem == newItem
    }
}
