package com.kq.acdos.ui.crew

import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.annotation.StringRes
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.button.MaterialButton
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.ScheduleChangeNoticeEntity
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.showLoading
import com.kq.acdos.ui.useThemeColors
import kotlinx.coroutines.launch

/**
 * The crew member's next pickup (Figma 3:333): time, JKIA report time and
 * vehicle, from the Room cache so it shows with no signal. When a re-plan
 * changed it (#53), a card on top says what changed until it is acknowledged.
 */
class CrewPickupFragment : Fragment(R.layout.fragment_crew_pickup) {
    private val viewModel: CrewPickupViewModel by viewModels { CrewPickupViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (requireActivity() as CrewHomeActivity).showTitle(R.string.crew_pickup_title)
        val details = view.findViewById<View>(R.id.details)
        val empty = view.findViewById<TextView>(R.id.empty)
        val acknowledge = view.findViewById<MaterialButton>(R.id.acknowledge)
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.useThemeColors()
        swipe.setOnRefreshListener {
            if (!viewModel.refresh(manual = true)) swipe.isRefreshing = false
        }
        view.findViewById<View>(R.id.report_row).label(R.string.crew_report_time)
        view.findViewById<View>(R.id.vehicle_row).label(R.string.crew_vehicle)

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val shown = state as? CrewPickupState.Pickup
                    details.isVisible = shown != null
                    empty.isVisible = state == CrewPickupState.NoPickup
                    if (shown != null) {
                        showPickup(view, shown.pickup)
                        showNotice(view, shown.notice, acknowledge)
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
                viewModel.acknowledging.collect {
                    acknowledge.showLoading(it, R.string.crew_notice_acknowledge)
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    Snackbar.make(view, message, Snackbar.LENGTH_LONG)
                        .setAnchorView(requireActivity().findViewById(R.id.bottom_nav))
                        .show()
                }
            }
        }
    }

    private fun View.label(@StringRes text: Int) {
        findViewById<TextView>(R.id.detail_label).setText(text)
    }

    private fun View.value(text: String) {
        findViewById<TextView>(R.id.detail_value).text = text
    }

    private fun showPickup(view: View, pickup: CrewPickupEntity) {
        view.findViewById<TextView>(R.id.pickup_time).text =
            pickup.estimatedPickup?.let(Times::clock)
                ?: getString(R.string.crew_pickup_time_unknown)
        view.findViewById<View>(R.id.report_row).value(Times.clock(pickup.reportTime))
        view.findViewById<View>(R.id.vehicle_row)
            .value(pickup.plateNumber ?: getString(R.string.crew_no_vehicle))
        view.findViewById<TextView>(R.id.updated).text =
            getString(R.string.route_updated, Times.clock(pickup.fetchedAt))
    }

    private fun showNotice(
        view: View,
        change: ScheduleChangeNoticeEntity?,
        acknowledge: MaterialButton
    ) {
        view.findViewById<View>(R.id.notice).isVisible = change != null
        if (change == null) return
        view.findViewById<TextView>(R.id.notice_change).text = noticeText(change)
        acknowledge.setOnClickListener { viewModel.acknowledge(change.id) }
    }

    private fun noticeText(change: ScheduleChangeNoticeEntity): String {
        val reason = getString(noticeReason(change.reason))
        val was = change.previousPickupTime
        val now = change.newPickupTime
        return when {
            now == null -> getString(
                R.string.crew_notice_unassigned,
                was?.let(Times::clock).orEmpty(),
                reason
            )

            was == null -> getString(R.string.crew_notice_new_time, Times.clock(now), reason)

            else -> getString(
                R.string.crew_notice_change,
                Times.shortClock(was),
                Times.clock(now),
                reason
            )
        }
    }

    /** Each time the tab comes to the front, e.g. when the crew member opens the app. */
    override fun onStart() {
        super.onStart()
        viewModel.refresh(manual = false)
    }
}
