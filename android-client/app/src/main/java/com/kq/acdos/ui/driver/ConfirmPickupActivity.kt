package com.kq.acdos.ui.driver

import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.local.DriverRouteDao
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.RouteStopEntity
import com.kq.acdos.data.outbox.PickupEventOutbox
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.applySystemBarPadding
import java.time.Instant
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/** Up to two letters for the avatar: "A. Sample" gives "AS". */
fun initials(name: String): String = name.split(' ').filter { it.isNotBlank() }
    .let { words -> listOfNotNull(words.firstOrNull(), words.drop(1).lastOrNull()) }
    .joinToString("") { it.take(1).uppercase() }

/** Saves to the outbox first, so all of this works with no signal. */
class ConfirmPickupViewModel(
    dao: DriverRouteDao,
    events: Flow<List<PendingPickupEventEntity>>,
    private val routeNodeId: String,
    private val outbox: PickupEventOutbox,
    private val upload: () -> Unit,
    private val refreshRoute: suspend () -> Unit
) : ViewModel() {
    /** Null once a re-plan has taken this stop off the driver's route. */
    val stop: Flow<RouteStopEntity?> = dao.observeRouteWithStops().map { cached ->
        cached?.stops?.find { it.routeNodeId == routeNodeId }
    }

    /**
     * A no-show is already recorded here, by this phone or on the server (#196), so all that's
     * left is a late arrival.
     */
    val alreadyNoShow: Flow<Boolean> = combine(stop, events) { cached, recorded ->
        withServerStatus(stopProgress(recorded)[routeNodeId], cached?.serverStatus)?.noShow == true
    }

    private val finishedState = MutableStateFlow(false)

    /** True once the event is saved, and the screen should close. */
    val finished: StateFlow<Boolean> = finishedState.asStateFlow()

    private var recording = false

    /**
     * Only the driver home refreshes the route, and it is stopped while this screen is open, so
     * without this a re-plan would never reach [stop]. Throttled like the home's own refresh.
     */
    fun checkStillOnRoute() {
        viewModelScope.launch { refreshRoute() }
    }

    /** A new event: a no-show before it stays in the log, and the server applies both in order. */
    fun crewOnBoard() = record { outbox.recordConfirmation(routeNodeId) }

    fun report(type: PickupExceptionType) = record { outbox.recordException(routeNodeId, type) }

    /** One event per visit: every call would otherwise create a new event with a new key. */
    private fun record(event: suspend () -> Unit) {
        if (recording) return
        recording = true
        viewModelScope.launch {
            event()
            upload()
            finishedState.value = true
        }
    }
}

/**
 * One stop, one decision. Crew on board, or not at the pickup point. Saved on the phone
 * first, so the driver is never held up by the network. The dispatcher sees the result
 * through the server; the app never contacts crew directly from here.
 */
class ConfirmPickupActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }

    private val viewModel: ConfirmPickupViewModel by viewModels {
        viewModelFactory {
            initializer {
                val routeNodeId = checkNotNull(intent.getStringExtra(EXTRA_ROUTE_NODE_ID))
                ConfirmPickupViewModel(
                    container.database.driverRouteDao(),
                    container.database.pendingPickupEventDao().observeForStop(routeNodeId),
                    routeNodeId,
                    container.pickupEventOutbox,
                    container::uploadPickupEvents,
                    refreshRoute = { container.driverRouteRepository?.refresh(force = false) }
                )
            }
        }
    }

    /** For the dialogs' titles. */
    private var crewNameText = ""

    private var openDialog: Dialog? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_confirm_pickup)
        applySystemBarPadding(findViewById(R.id.main))

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.setNavigationOnClickListener { finish() }
        toolbar.setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.action_report_problem) askWhatWentWrong()
            item.itemId == R.id.action_report_problem
        }

        val scheduled = detailRow(R.id.scheduled, R.string.confirm_scheduled)
        val now = detailRow(R.id.now, R.string.confirm_now)
        val avatar = findViewById<TextView>(R.id.avatar)
        val crewName = findViewById<TextView>(R.id.crew_name)
        val zone = findViewById<TextView>(R.id.zone)

        findViewById<Button>(R.id.on_board).setOnClickListener { viewModel.crewOnBoard() }
        findViewById<Button>(R.id.not_at_point).setOnClickListener { confirmNoShow() }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.stop.collect { stop ->
                    if (stop == null) {
                        leaveBecauseStopIsGone()
                    } else {
                        crewNameText = stop.crewName
                        crewName.text = stop.crewName
                        avatar.text = initials(stop.crewName)
                        zone.text = stop.zoneLabel?.let(::shortZone)
                            ?: getString(R.string.route_zone_unknown)
                        scheduled.text = Times.clock(stop.scheduledPickup)
                    }
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.alreadyNoShow.collect { noShow ->
                    findViewById<View>(R.id.no_show_chip).isVisible = noShow
                    findViewById<View>(R.id.not_at_point).isVisible = !noShow
                    toolbar.menu.findItem(R.id.action_report_problem).isVisible = !noShow
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.finished.collect { if (it) finish() }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    now.text = Times.clock(Instant.now())
                    delay(CLOCK_TICK_MS)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        viewModel.checkStillOnRoute()
    }

    private fun detailRow(id: Int, label: Int): TextView {
        val row = findViewById<View>(id)
        row.findViewById<TextView>(R.id.detail_label).setText(label)
        return row.findViewById(R.id.detail_value)
    }

    private fun leaveBecauseStopIsGone() {
        if (viewModel.finished.value || isFinishing) return
        openDialog?.dismiss()
        Toast.makeText(this, R.string.confirm_stop_gone, Toast.LENGTH_LONG).show()
        finish()
    }

    /** A no-show moves the pickup to missed at once, so it is checked first. */
    private fun confirmNoShow() {
        openDialog = MaterialAlertDialogBuilder(this)
            .setTitle(getString(R.string.confirm_no_show_title, crewNameText))
            .setMessage(R.string.confirm_no_show_message)
            .setPositiveButton(R.string.confirm_no_show_action) { _, _ ->
                viewModel.report(PickupExceptionType.NO_SHOW)
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    /** The server's other two exception types. Neither ends the stop. */
    private fun askWhatWentWrong() {
        val problems = listOf(
            PickupExceptionType.VEHICLE_ISSUE to R.string.route_problem_vehicle_issue,
            PickupExceptionType.TRAFFIC_DELAY to R.string.route_problem_traffic_delay
        )
        openDialog = MaterialAlertDialogBuilder(this)
            .setTitle(getString(R.string.route_problem_title, crewNameText))
            .setItems(problems.map { getString(it.second) }.toTypedArray()) { _, which ->
                viewModel.report(problems[which].first)
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    companion object {
        private const val EXTRA_ROUTE_NODE_ID = "route_node_id"
        private const val CLOCK_TICK_MS = 10_000L

        fun intent(context: Context, routeNodeId: String): Intent =
            Intent(context, ConfirmPickupActivity::class.java)
                .putExtra(EXTRA_ROUTE_NODE_ID, routeNodeId)
    }
}
