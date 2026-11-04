package com.kq.acdos.ui.dispatcher

import android.app.TimePickerDialog
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.card.MaterialCardView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.VehicleStatusDto
import com.kq.acdos.ui.EXTRA_FULL_NAME
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openLoginWhenSessionEnds
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.launch

/**
 * The dispatcher's hub (#27): one Nairobi day's routes, pickups and vans.
 * Run optimisation plans the day; a flight delay (tap a pickup) or a
 * breakdown (tap a van) is recorded first, then re-planned with an explicit
 * tap. Crew messages (#57) show read-only at the top, newest first. Online
 * only: nothing here is cached.
 */
class DispatcherHomeActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }
    private val viewModel: DispatcherViewModel by viewModels { DispatcherViewModel.Factory }
    private val inbox: InboxViewModel by viewModels { InboxViewModel.Factory }

    private val dayFormat = DateTimeFormatter.ofPattern("EEE d MMM", Locale.UK)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_dispatcher_home)
        val root = findViewById<View>(R.id.main)
        applySystemBarPadding(root)

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.title = intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_refresh -> {
                    viewModel.load()
                    inbox.load()
                    true
                }

                R.id.action_sign_out -> {
                    lifecycleScope.launch { container.sessionRouter.signOut() }
                    true
                }

                else -> false
            }
        }

        findViewById<Button>(R.id.previous_day).setOnClickListener { viewModel.showDay(-1) }
        findViewById<Button>(R.id.next_day).setOnClickListener { viewModel.showDay(1) }
        val run = findViewById<Button>(R.id.run_optimisation)
        run.setOnClickListener { viewModel.runOptimisation() }
        findViewById<Button>(R.id.replan).setOnClickListener { viewModel.replan() }

        val loading = findViewById<LinearProgressIndicator>(R.id.loading)
        val date = findViewById<TextView>(R.id.date)
        val jobStatus = findViewById<TextView>(R.id.job_status)
        val replanCard = findViewById<MaterialCardView>(R.id.replan_card)
        val replanText = findViewById<TextView>(R.id.replan_text)

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    loading.isVisible = state.loading
                    date.text = dayFormat.format(state.date)
                    run.isEnabled = state.board != null && state.job != JobUi.Running
                    jobStatus.isVisible = state.job != JobUi.None
                    jobStatus.text = jobText(state.job)
                    replanCard.isVisible = state.replan != null
                    state.replan?.let { replanText.text = getString(it.label, it.subject) }
                    showBoard(state.board)
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.messages.collect { showInbox(it) }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    val text = getString(message.text, message.detail)
                    Snackbar.make(root, text, Snackbar.LENGTH_LONG).show()
                }
            }
        }

        openLoginWhenSessionEnds(container)
    }

    private fun jobText(job: JobUi): String = when (job) {
        JobUi.None -> ""

        JobUi.Running -> getString(R.string.dispatch_job_running)

        is JobUi.Done -> getString(R.string.dispatch_job_done, job.routes, job.late, job.unassigned)

        is JobUi.Failed -> job.error?.let { getString(R.string.dispatch_job_failed, it) }
            ?: getString(R.string.dispatch_job_failed_unknown)
    }

    /** A day's lists are short (tens of rows), so plain rows in a scroll view do. */
    private fun showBoard(board: DayBoard?) {
        val routes = findViewById<LinearLayout>(R.id.routes)
        val pickups = findViewById<LinearLayout>(R.id.pickups)
        val vehicles = findViewById<LinearLayout>(R.id.vehicles)
        for (list in listOf(routes, pickups, vehicles)) list.removeAllViews()
        if (board == null) return

        val names = board.crewNames
        for (route in board.routes) {
            val stops = route.nodes.sortedBy { it.seqOrder }.joinToString("\n") {
                val name = names[it.pickupRequestId] ?: getString(R.string.dispatch_unknown_crew)
                val at = Times.clock(it.estimatedArrival)
                getString(R.string.dispatch_route_stop, it.seqOrder, name, at)
            }
            val times = getString(
                R.string.dispatch_route_times,
                Times.clock(route.plannedDeparture),
                Times.clock(route.plannedArrival)
            )
            addRow(
                routes,
                getString(R.string.dispatch_route_title, route.vehiclePlate, route.totalDistanceKm),
                "$times\n$stops"
            )
        }
        for (pickup in board.pickups) {
            addRow(
                pickups,
                getString(R.string.dispatch_pickup_title, pickup.crewName, pickup.zoneLabel ?: "-"),
                getString(
                    R.string.dispatch_pickup_subtitle,
                    Times.clock(pickup.reportTime),
                    getString(pickupStatusLabel(pickup.status))
                )
            ) { askAboutPickup(pickup) }
        }
        for (vehicle in board.vehicles) {
            val status = getString(vehicleStatusLabel(vehicle.status))
            addRow(
                vehicles,
                getString(R.string.dispatch_vehicle_title, vehicle.plateNumber, vehicle.capacity),
                if (vehicle.onTheRoad) getString(R.string.dispatch_on_the_road, status) else status
            ) { askAboutVehicle(vehicle) }
        }
        for (list in listOf(routes, pickups, vehicles)) {
            if (list.childCount == 0) addRow(list, getString(R.string.dispatch_none), null)
        }
    }

    /** Read-only: crew names, the preset's words and when it was sent. */
    private fun showInbox(messages: List<CrewMessageDto>?) {
        val list = findViewById<LinearLayout>(R.id.inbox)
        list.removeAllViews()
        if (messages == null) return
        for (message in messages) {
            addRow(
                list,
                getString(R.string.dispatch_message_title, message.crewName, message.label),
                Times.clock(message.sentAt)
            )
        }
        if (list.childCount == 0) addRow(list, getString(R.string.dispatch_none), null)
    }

    private fun addRow(
        list: LinearLayout,
        title: String,
        subtitle: String?,
        onTap: (() -> Unit)? = null
    ) {
        val row = LayoutInflater.from(this).inflate(R.layout.item_dispatch_row, list, false)
        row.findViewById<TextView>(R.id.title).text = title
        row.findViewById<TextView>(R.id.subtitle).apply {
            text = subtitle
            isVisible = subtitle != null
        }
        if (onTap != null) row.setOnClickListener { onTap() } else row.isClickable = false
        list.addView(row)
    }

    /** A flight delay: pick the new report time, same day. */
    private fun askAboutPickup(pickup: DispatcherPickupDto) {
        val plannable = pickup.status == PickupRequestStatusDto.PENDING ||
            pickup.status == PickupRequestStatusDto.ASSIGNED
        if (!plannable) return
        MaterialAlertDialogBuilder(this)
            .setTitle(pickup.crewName)
            .setItems(arrayOf(getString(R.string.dispatch_flight_delay))) { _, _ ->
                val current = pickup.reportTime.atZone(Times.ZONE)
                TimePickerDialog(this, { _, hour, minute ->
                    val newTime = current.with(LocalTime.of(hour, minute)).toInstant()
                    viewModel.delayFlight(pickup, newTime)
                }, current.hour, current.minute, true).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun askAboutVehicle(vehicle: DispatcherVehicleDto) {
        val brokenDown = vehicle.status == VehicleStatusDto.BROKEN_DOWN
        val action =
            if (brokenDown) R.string.dispatch_mark_available else R.string.dispatch_mark_broken_down
        MaterialAlertDialogBuilder(this)
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
private fun pickupStatusLabel(status: PickupRequestStatusDto): Int = when (status) {
    PickupRequestStatusDto.PENDING -> R.string.pickup_status_pending
    PickupRequestStatusDto.ASSIGNED -> R.string.pickup_status_assigned
    PickupRequestStatusDto.PICKED_UP -> R.string.pickup_status_picked_up
    PickupRequestStatusDto.MISSED -> R.string.pickup_status_missed
    PickupRequestStatusDto.CANCELLED -> R.string.pickup_status_cancelled
}

@StringRes
private fun vehicleStatusLabel(status: VehicleStatusDto): Int = when (status) {
    VehicleStatusDto.AVAILABLE -> R.string.vehicle_status_available
    VehicleStatusDto.IN_SERVICE -> R.string.vehicle_status_in_service
    VehicleStatusDto.BROKEN_DOWN -> R.string.vehicle_status_broken_down
}
