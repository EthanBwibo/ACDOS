package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.PlanSummary
import com.kq.acdos.data.orderedRoutes
import com.kq.acdos.data.planSummary
import com.kq.acdos.data.remote.PickupRequestStatusDto
import kotlinx.coroutines.launch

/**
 * What a re-plan keeps and what it changes (Figma 2:188). Vans already out are
 * locked; only unstarted routes go back to the solver. The server saves the
 * new routes when the job finishes, so "Before" and "After" compare the board
 * either side of it, and the only choice first is Discard or Re-plan.
 */
class ReplanFragment : Fragment(R.layout.fragment_replan) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_replan))
        view.findViewById<Button>(R.id.discard).setOnClickListener {
            viewModel.discardReplan()
            home.close()
        }
        view.findViewById<Button>(R.id.replan).setOnClickListener {
            pickVans(viewModel, viewModel::replan)
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state -> show(view, state) }
            }
        }
    }

    private fun show(view: View, state: DispatcherUiState) {
        val replan = state.replan
        view.findViewById<TextView>(R.id.replan_title).text = when {
            replan != null -> getString(replan.label, replan.subject)
            else -> jobText(state.job)
        }
        view.findViewById<TextView>(R.id.replan_subtitle).apply {
            isVisible = replan != null
            text = replan?.let {
                resources.getQuantityString(
                    R.plurals.dispatch_to_replan,
                    it.pickupIds.size,
                    it.pickupIds.size
                )
            }
        }
        view.findViewById<View>(R.id.replan_actions).isVisible = replan != null
        view.findViewById<View>(R.id.replan_progress).isVisible = state.job.isActive
        view.findViewById<Button>(R.id.replan).isEnabled =
            state.board != null && !state.job.isActive

        val board = state.board
        if (board != null && replan != null) {
            showRoutes(view, board, replan.pickupIds.toSet())
        }
        view.findViewById<View>(R.id.fixed_group).isVisible = replan != null
        view.findViewById<View>(R.id.resolved_group).isVisible = replan != null
        showComparison(view, state)
    }

    private fun showRoutes(view: View, board: DayBoard, affected: Set<String>) {
        val fixed = view.findViewById<LinearLayout>(R.id.fixed)
        val resolved = view.findViewById<LinearLayout>(R.id.resolved)
        fixed.removeAllViews()
        resolved.removeAllViews()
        val outNow = board.vehicles.filter { it.onTheRoad }.map { it.id }.toSet()
        val pickedUp = board.pickups
            .filter { it.status == PickupRequestStatusDto.PICKED_UP }
            .map { it.id }
            .toSet()
        orderedRoutes(board).forEachIndexed { index, route ->
            val pickups = route.nodes.map { it.pickupRequestId }
            val name = routeName(index + 1, route.vehiclePlate)
            if (route.vehicleId in outNow) {
                fixed.addRow(
                    title = name,
                    subtitle = getString(
                        R.string.dispatch_picked_up_of,
                        pickups.count { it in pickedUp },
                        pickups.size
                    ),
                    value = getString(R.string.dispatch_locked)
                )
            } else if (pickups.any { it in affected }) {
                val moving = pickups.count { it in affected }
                resolved.addRow(
                    title = name,
                    subtitle = resources.getQuantityString(
                        R.plurals.dispatch_to_replan,
                        moving,
                        moving
                    )
                )
            }
        }
        if (fixed.childCount == 0) fixed.addRow(getString(R.string.dispatch_none))
        if (resolved.childCount == 0) resolved.addRow(getString(R.string.dispatch_none))
    }

    private fun showComparison(view: View, state: DispatcherUiState) {
        val now = state.board?.let(::planSummary)
        val before = state.before ?: now
        val finished = state.before != null && state.job is JobUi.Done
        val beforeRow = view.findViewById<View>(R.id.before_row)
        val afterRow = view.findViewById<View>(R.id.after_row)
        beforeRow.findViewById<TextView>(R.id.detail_label).setText(R.string.dispatch_before)
        beforeRow.findViewById<TextView>(R.id.detail_value).text = before?.let(::summary)
        afterRow.isVisible = finished
        afterRow.findViewById<TextView>(R.id.detail_label).setText(R.string.dispatch_after)
        afterRow.findViewById<TextView>(R.id.detail_value).text = now?.let(::summary)
    }

    private fun summary(plan: PlanSummary) = getString(
        R.string.dispatch_compare,
        plan.vehicleMinutes,
        plan.vansUsed,
        plan.late
    )
}
