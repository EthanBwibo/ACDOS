package com.kq.acdos.ui.driver

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.kq.acdos.R
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.useThemeColors
import kotlinx.coroutines.launch

/** Read-only list of planned routes. Shift requests are out of scope (Figma 3:237). */
class ScheduleFragment : Fragment(R.layout.fragment_schedule) {
    private val viewModel: ScheduleViewModel by activityViewModels { ScheduleViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (requireActivity() as DriverHomeActivity).showHeader(getString(R.string.tab_schedule), null)
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.useThemeColors()
        swipe.setOnRefreshListener {
            viewModel.load()
            // Without an API nothing changes, so no new state would stop the spinner.
            swipe.isRefreshing = viewModel.state.value.loading
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    swipe.isRefreshing = state.loading
                    show(view, state)
                }
            }
        }
        viewModel.loadIfNeeded()
    }

    private fun show(view: View, state: ScheduleUiState) {
        val error = view.findViewById<TextView>(R.id.error)
        error.isVisible = state.error != null
        state.error?.let(error::setText)

        val sections = state.sections
        view.findViewById<View>(R.id.empty).isVisible = sections?.isEmpty == true
        showSection(
            view.findViewById(R.id.today_label),
            view.findViewById(R.id.today_card),
            view.findViewById(R.id.today_rows),
            sections?.today.orEmpty()
        )
        showSection(
            view.findViewById(R.id.upcoming_label),
            view.findViewById(R.id.upcoming_card),
            view.findViewById(R.id.upcoming_rows),
            sections?.upcoming.orEmpty()
        )
    }

    private fun showSection(
        label: View,
        card: View,
        rows: LinearLayout,
        routes: List<ScheduleRow>
    ) {
        label.isVisible = routes.isNotEmpty()
        card.isVisible = routes.isNotEmpty()
        rows.removeAllViews()
        for (route in routes) {
            val row = LayoutInflater.from(rows.context).inflate(R.layout.item_list_row, rows, false)
            row.findViewById<TextView>(R.id.row_lead).text = Times.dayOfMonth(route.firstPickup)
            row.findViewById<TextView>(R.id.row_title).text = if (route.showDay) {
                getString(R.string.schedule_day_title, Times.day(route.firstPickup), route.plate)
            } else {
                route.plate
            }
            row.findViewById<TextView>(R.id.row_subtitle).text = getString(
                R.string.schedule_row_subtitle,
                route.crewCount,
                Times.clock(route.firstPickup)
            )
            val value = row.findViewById<TextView>(R.id.row_value)
            if (route.started) {
                value.setText(R.string.schedule_in_progress)
            } else {
                value.text = Times.shortClock(route.firstPickup)
            }
            rows.addView(row)
        }
    }
}
