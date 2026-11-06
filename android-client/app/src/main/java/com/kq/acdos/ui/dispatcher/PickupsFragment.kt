package com.kq.acdos.ui.dispatcher

import android.app.TimePickerDialog
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
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.ui.Times
import java.time.LocalTime
import kotlinx.coroutines.launch

/**
 * The day's pickups, from the hub's tile: who reports when, whether they've
 * acknowledged a change, and where a flight delay is recorded. No wireframe of
 * its own, so it uses the same rows as the others.
 */
class PickupsFragment : Fragment(R.layout.fragment_dispatch_list) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_pickups))
        val rows = view.findViewById<LinearLayout>(R.id.rows)

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    rows.removeAllViews()
                    val pickups = state.board?.pickups ?: return@collect
                    pickups.forEach { addPickup(rows, it) }
                    if (pickups.isEmpty()) rows.addRow(getString(R.string.dispatch_no_pickups))
                }
            }
        }
    }

    private fun addPickup(rows: LinearLayout, pickup: DispatcherPickupDto) {
        val status = getString(pickupStatusLabel(pickup.status))
        val subtitle = getString(
            R.string.dispatch_pickup_subtitle,
            Times.clock(pickup.reportTime),
            status
        )
        val ack = ackLabel(pickup)?.let { " · " + getString(it) }.orEmpty()
        rows.addRow(
            title = getString(
                R.string.dispatch_pickup_title,
                pickup.crewName,
                pickup.zoneLabel ?: getString(R.string.dispatch_no_value)
            ),
            subtitle = subtitle + ack
        ) { askAboutPickup(pickup) }
    }

    /** A flight delay: pick the new report time, same day. */
    private fun askAboutPickup(pickup: DispatcherPickupDto) {
        val plannable = pickup.status == PickupRequestStatusDto.PENDING ||
            pickup.status == PickupRequestStatusDto.ASSIGNED
        if (!plannable) return
        MaterialAlertDialogBuilder(requireContext())
            .setTitle(pickup.crewName)
            .setItems(arrayOf(getString(R.string.dispatch_flight_delay))) { _, _ ->
                val current = pickup.reportTime.atZone(Times.ZONE)
                TimePickerDialog(requireContext(), { _, hour, minute ->
                    val newTime = current.with(LocalTime.of(hour, minute)).toInstant()
                    viewModel.delayFlight(pickup, newTime)
                }, current.hour, current.minute, true).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }
}

@StringRes
private fun pickupStatusLabel(status: PickupRequestStatusDto): Int = when (status) {
    PickupRequestStatusDto.PENDING -> R.string.pickup_status_pending
    PickupRequestStatusDto.ASSIGNED -> R.string.pickup_status_assigned
    PickupRequestStatusDto.PICKED_UP -> R.string.pickup_status_picked_up
    PickupRequestStatusDto.MISSED -> R.string.pickup_status_missed
    PickupRequestStatusDto.CANCELLED -> R.string.pickup_status_cancelled
}

/**
 * Where the crew member is with the latest schedule-change notice (#53, #56):
 * acknowledged, still to acknowledge, or no line when there is no notice.
 */
@StringRes
internal fun ackLabel(pickup: DispatcherPickupDto): Int? = when {
    pickup.acknowledgedAt != null -> R.string.dispatch_acknowledged
    pickup.needsAck -> R.string.dispatch_awaiting_ack
    else -> null
}
