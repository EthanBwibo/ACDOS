package com.kq.acdos.ui.driver

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.NetworkKind
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.showLoading
import java.time.Instant
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/** The driver's local event log, so "saved on this phone" can be checked (Figma 3:284). */
class SyncFragment : Fragment(R.layout.fragment_sync) {
    private val container get() = (requireActivity().application as AcdosApplication).container

    private val viewModel: SyncViewModel by viewModels {
        viewModelFactory {
            initializer {
                SyncViewModel(
                    driverEvents(
                        container.database.pendingPickupEventDao(),
                        driverId = { container.authRepository.storedSessionUserId() }
                    ),
                    container.database.driverRouteDao().observeRouteWithStops()
                        .map { it?.stops.orEmpty() },
                    send = container::sendPickupEvents
                )
            }
        }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (requireActivity() as DriverHomeActivity).showHeader(getString(R.string.tab_sync), null)
        val button = view.findViewById<MaterialButton>(R.id.sync_now)
        button.setOnClickListener { viewModel.syncNow() }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.queue.collect { queue -> queue?.let { showQueue(view, it) } }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                container.connectivity.network.collect { showNetwork(view, it) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(viewModel.sending, viewModel.queue) { sending, queue ->
                    sending to (queue?.waiting ?: 0)
                }.collect { (sending, waiting) ->
                    button.showLoading(sending, R.string.sync_now)
                    // Off with nothing to send, but never mid-spin as the queue empties.
                    button.isEnabled = sending || waiting > 0
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.results.collect { showResult(view, it) }
            }
        }
    }

    private fun showNetwork(view: View, network: NetworkKind) {
        view.findViewById<TextView>(R.id.sync_state).setText(
            if (network.isOnline) R.string.sync_online else R.string.sync_offline
        )
        view.findViewById<Chip>(R.id.network_chip).setText(
            when (network) {
                NetworkKind.WIFI -> R.string.sync_network_wifi
                NetworkKind.MOBILE -> R.string.sync_network_mobile
                NetworkKind.NONE -> R.string.sync_network_none
            }
        )
    }

    private fun showQueue(view: View, queue: SyncQueue) {
        view.findViewById<TextView>(R.id.sync_summary).text = summary(queue)
        view.findViewById<View>(R.id.queue_empty).isVisible = queue.rows.isEmpty()
        view.findViewById<View>(R.id.queue_card).isVisible = queue.rows.isNotEmpty()
        val older = view.findViewById<TextView>(R.id.queue_older)
        older.isVisible = queue.hidden > 0
        older.text = resources.getQuantityString(R.plurals.sync_older, queue.hidden, queue.hidden)

        val rows = view.findViewById<LinearLayout>(R.id.queue_rows)
        rows.removeAllViews()
        queue.rows.forEachIndexed { index, event ->
            val row = LayoutInflater.from(rows.context).inflate(R.layout.item_list_row, rows, false)
            // The lead is the event's place in line; past events have left the line.
            row.findViewById<TextView>(R.id.row_lead).text = when (event.status) {
                QueueStatus.WAITING -> (index + 1).toString()
                QueueStatus.SENT -> getString(R.string.sync_lead_sent)
                QueueStatus.REFUSED -> getString(R.string.sync_lead_refused)
            }
            row.findViewById<TextView>(R.id.row_title).text = title(event)
            row.findViewById<TextView>(R.id.row_subtitle).text = subtitle(event)
            row.findViewById<View>(R.id.row_value).isVisible = false
            showStatusChip(row, event.status)
            rows.addView(row)
        }
    }

    private fun showStatusChip(row: View, status: QueueStatus) {
        val (id, label) = when (status) {
            QueueStatus.WAITING -> R.id.row_chip_neutral to R.string.sync_status_queued
            QueueStatus.SENT -> R.id.row_chip_success to R.string.sync_status_sent
            QueueStatus.REFUSED -> R.id.row_chip_warning to R.string.sync_status_refused
        }
        row.findViewById<Chip>(id).apply {
            isVisible = true
            setText(label)
        }
    }

    private fun title(event: QueueRow): String {
        val action = getString(event.action)
        val zone = event.zoneLabel?.let(::shortZone) ?: return action
        return getString(R.string.sync_row_title, action, zone)
    }

    private fun subtitle(event: QueueRow): String {
        event.conflict?.let { return getString(refusalReason(it)) }
        val time = Times.shortClock(event.at)
        val crew = event.crewName ?: return time
        val line = if (event.onBoard) R.string.sync_row_on_board else R.string.sync_row_crew
        return getString(line, crew, time)
    }

    private fun summary(queue: SyncQueue): String {
        val waiting = if (queue.waiting == 0) {
            getString(R.string.sync_nothing_waiting)
        } else {
            resources.getQuantityString(R.plurals.sync_waiting, queue.waiting, queue.waiting)
        }
        val synced = queue.lastSynced ?: return getString(R.string.sync_never, waiting)
        return getString(R.string.sync_last_synced, lastSyncedTime(synced), waiting)
    }

    /** With the day once it isn't today, so an old sync can't pass for a recent one. */
    private fun lastSyncedTime(at: Instant): String =
        if (Times.date(at) == Times.date(Instant.now())) {
            Times.clock(at)
        } else {
            getString(R.string.sync_day_time, Times.day(at), Times.clock(at))
        }

    private fun showResult(view: View, stillWaiting: Int) {
        val message = if (stillWaiting == 0) {
            getString(R.string.sync_all_sent)
        } else {
            resources.getQuantityString(R.plurals.sync_still_waiting, stillWaiting, stillWaiting)
        }
        Snackbar.make(view, message, Snackbar.LENGTH_LONG)
            .setAnchorView(R.id.sync_now)
            .show()
    }
}
