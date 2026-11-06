package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.planWindow
import com.kq.acdos.data.plannableVans
import com.kq.acdos.ui.Times
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.launch

/** A step of the job dims until it is reached. */
private const val STEP_AHEAD_ALPHA = 0.4f

/**
 * What a first plan will cover, and the job while it runs (Figma 2:87). The
 * server saves the routes itself when the job finishes, so there is nothing
 * to publish, and it has no call to cancel a job.
 */
class OptimisationRunFragment : Fragment(R.layout.fragment_optimisation_run) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    private val dayFormat = DateTimeFormatter.ofPattern("EEE d MMM", Locale.UK)

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_optimisation_title))
        view.findViewById<Button>(R.id.start).setOnClickListener {
            pickVans(viewModel, viewModel::runOptimisation)
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    state.board?.let { showSetup(view, state, it) }
                    showJob(view, state.job)
                    view.findViewById<Button>(R.id.start).isEnabled =
                        state.board != null && !state.job.isActive
                }
            }
        }
    }

    private fun showSetup(view: View, state: DispatcherUiState, board: DayBoard) {
        val day = dayFormat.format(state.date)
        view.findViewById<TextView>(R.id.report_window).text = planWindow(board)?.let {
            getString(
                R.string.dispatch_report_window,
                day,
                Times.shortClock(it.first),
                Times.shortClock(it.second)
            )
        } ?: day
        val vans = plannableVans(board)
        view.findViewById<TextView>(R.id.vans_available).text =
            getString(R.string.dispatch_vans_available, vans.size)
        val seats = board.vehicles.filter { it.id in vans }.map { it.capacity }
        view.findViewById<TextView>(R.id.seats).text = when {
            seats.isEmpty() -> getString(R.string.dispatch_no_value)
            seats.min() == seats.max() -> seats.first().toString()
            else -> getString(R.string.dispatch_seat_range, seats.min(), seats.max())
        }
    }

    private fun showJob(view: View, job: JobUi) {
        view.findViewById<View>(R.id.job_queued).step(job != JobUi.None)
        view.findViewById<View>(R.id.job_running)
            .step(job != JobUi.None && job != JobUi.Queued)
        view.findViewById<View>(R.id.job_done).step(job is JobUi.Done)
        view.findViewById<View>(R.id.job_failed).apply {
            isVisible = job is JobUi.Failed
        }
        view.findViewById<View>(R.id.job_progress).isVisible = job.isActive
        view.findViewById<TextView>(R.id.job_text).apply {
            text = if (job == JobUi.None) getString(R.string.dispatch_job_idle) else jobText(job)
        }
    }

    private fun View.step(reached: Boolean) {
        alpha = if (reached) 1f else STEP_AHEAD_ALPHA
    }
}
