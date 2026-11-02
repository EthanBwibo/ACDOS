package com.kq.acdos.ui.crew

import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.ui.Times
import kotlinx.coroutines.launch

/**
 * The crew member's next pickup: time, JKIA report time and vehicle, from
 * the Room cache so it shows with no signal. Read-only until #53 adds
 * acknowledging changes.
 */
class CrewPickupFragment : Fragment(R.layout.fragment_crew_pickup) {
    private val viewModel: CrewPickupViewModel by viewModels { CrewPickupViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val details = view.findViewById<View>(R.id.details)
        val empty = view.findViewById<TextView>(R.id.empty)
        val pickupTime = view.findViewById<TextView>(R.id.pickup_time)
        val reportTime = view.findViewById<TextView>(R.id.report_time)
        val vehicle = view.findViewById<TextView>(R.id.vehicle)
        val updated = view.findViewById<TextView>(R.id.updated)
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.setOnRefreshListener {
            if (!viewModel.refresh(manual = true)) swipe.isRefreshing = false
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val pickup = (state as? CrewPickupState.Pickup)?.pickup
                    details.isVisible = pickup != null
                    empty.isVisible = state == CrewPickupState.NoPickup
                    if (pickup != null) {
                        pickupTime.text = pickup.estimatedPickup?.let(Times::clock)
                            ?: getString(R.string.crew_pickup_time_unknown)
                        reportTime.text =
                            getString(R.string.crew_report_time, Times.clock(pickup.reportTime))
                        vehicle.text = pickup.plateNumber
                            ?.let { getString(R.string.crew_vehicle, it) }
                            ?: getString(R.string.crew_no_vehicle)
                        updated.text =
                            getString(R.string.route_updated, Times.clock(pickup.fetchedAt))
                    }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.refreshing.collect { swipe.isRefreshing = it }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    Snackbar.make(view, message, Snackbar.LENGTH_LONG).show()
                }
            }
        }
    }

    /** Each time the tab comes to the front, e.g. when the crew member opens the app. */
    override fun onStart() {
        super.onStart()
        viewModel.refresh(manual = false)
    }
}
