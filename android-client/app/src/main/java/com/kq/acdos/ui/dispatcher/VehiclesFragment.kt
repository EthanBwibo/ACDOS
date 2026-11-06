package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import androidx.annotation.StringRes
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.kq.acdos.R
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.VehicleStatusDto
import kotlinx.coroutines.launch

/**
 * The vans, from the hub's tile, and where a breakdown is recorded. No
 * wireframe of its own, so it uses the same rows as the others.
 */
class VehiclesFragment : Fragment(R.layout.fragment_dispatch_list) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_vehicles))
        val rows = view.findViewById<LinearLayout>(R.id.rows)

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    rows.removeAllViews()
                    val vehicles = state.board?.vehicles ?: return@collect
                    vehicles.forEach { addVehicle(rows, it) }
                    if (vehicles.isEmpty()) rows.addRow(getString(R.string.dispatch_no_vehicles))
                }
            }
        }
    }

    private fun addVehicle(rows: LinearLayout, vehicle: DispatcherVehicleDto) {
        val status = getString(vehicleStatusLabel(vehicle.status))
        rows.addRow(
            title = getString(
                R.string.dispatch_vehicle_title,
                vehicle.plateNumber,
                vehicle.capacity
            ),
            subtitle = if (vehicle.onTheRoad) {
                getString(R.string.dispatch_on_the_road, status)
            } else {
                status
            }
        ) { askAboutVehicle(vehicle) }
    }

    private fun askAboutVehicle(vehicle: DispatcherVehicleDto) {
        val brokenDown = vehicle.status == VehicleStatusDto.BROKEN_DOWN
        val action =
            if (brokenDown) R.string.dispatch_mark_available else R.string.dispatch_mark_broken_down
        MaterialAlertDialogBuilder(requireContext())
            .setTitle(vehicle.plateNumber)
            .setItems(arrayOf(getString(action))) { _, _ ->
                if (brokenDown) {
                    viewModel.markAvailable(vehicle)
                } else {
                    viewModel.markBrokenDown(vehicle)
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }
}

@StringRes
private fun vehicleStatusLabel(status: VehicleStatusDto): Int = when (status) {
    VehicleStatusDto.AVAILABLE -> R.string.vehicle_status_available
    VehicleStatusDto.IN_SERVICE -> R.string.vehicle_status_in_service
    VehicleStatusDto.BROKEN_DOWN -> R.string.vehicle_status_broken_down
}
