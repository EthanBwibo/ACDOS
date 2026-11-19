package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.children
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.PlanWave
import com.kq.acdos.data.planWaves
import com.kq.acdos.data.plannableVans
import com.kq.acdos.ui.Times
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.launch

/** A step of the job dims until it is reached. */
private const val STEP_AHEAD_ALPHA = 0.4f

/**
 * The Plan tab (#230): what a first plan will cover, and the job while it runs
 * (Figma 2:87). A first plan covers one wave of the day's unplanned pickups,
 * picked from the chips or with Next wave; none is picked at first. A waiting re-plan (a flight delay or a breakdown) shows on top
 * and opens Re-plan inside this tab. The server saves the routes itself when
 * the job finishes, so there is nothing to publish, and it has no call to
 * cancel a job.
 */
class OptimisationRunFragment : Fragment(R.layout.fragment_optimisation_run) {
    private val viewModel: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    private val dayFormat = DateTimeFormatter.ofPattern("EEE d MMM", Locale.UK)

    // In onStart, not onViewCreated: a screen names itself again when its tab comes back.
    override fun onStart() {
        super.onStart()
        home.showTitle(getString(R.string.dispatch_optimisation_title))
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        view.findViewById<Button>(R.id.start).setOnClickListener {
            pickVans(viewModel, viewModel::runOptimisation)
        }
        view.findViewById<Button>(R.id.next_wave).setOnClickListener { viewModel.nextWave() }
        view.findViewById<ChipGroup>(R.id.waves).setOnCheckedStateChangeListener { group, ids ->
            // Only the dispatcher's taps: showWaves checks chips to match the state already.
            if (!showingWaves) {
                val first = ids.firstOrNull()?.let { group.findViewById<View>(it).tag as Instant }
                viewModel.selectWave(first)
            }
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    state.board?.let { showSetup(view, state, it) }
                    showJob(view, state.job)
                    showReplan(view, state.replan)
                    view.findViewById<Button>(R.id.start).isEnabled =
                        selectedWave(state) != null && !state.job.isActive
                }
            }
        }
    }

    private fun showSetup(view: View, state: DispatcherUiState, board: DayBoard) {
        val day = dayFormat.format(state.date)
        val wave = selectedWave(state)
        view.findViewById<TextView>(R.id.report_window).text = wave?.let {
            getString(
                R.string.dispatch_report_window,
                day,
                Times.shortClock(it.first),
                Times.shortClock(it.last)
            )
        } ?: day
        showWaves(view, planWaves(board), wave)
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

    /** One chip per wave; only [selected] is checked, and none is by default. */
    private fun showWaves(view: View, waves: List<PlanWave>, selected: PlanWave?) {
        view.findViewById<View>(R.id.no_waves).isVisible = waves.isEmpty()
        view.findViewById<View>(R.id.next_wave).isEnabled = waves.isNotEmpty()
        val group = view.findViewById<ChipGroup>(R.id.waves)
        showingWaves = true
        if (waves != shownWaves) {
            shownWaves = waves
            group.removeAllViews()
            for (wave in waves) {
                val chip = layoutInflater.inflate(R.layout.item_wave_chip, group, false) as Chip
                chip.id = View.generateViewId()
                chip.tag = wave.first
                chip.text = resources.getQuantityString(
                    R.plurals.dispatch_wave_chip,
                    wave.pickupIds.size,
                    Times.shortClock(wave.first),
                    Times.shortClock(wave.last),
                    wave.pickupIds.size
                )
                group.addView(chip)
            }
        }
        val checked = group.children.firstOrNull { it.tag == selected?.first }
        if (checked == null) group.clearCheck() else group.check(checked.id)
        showingWaves = false
    }

    /** True while showWaves rebuilds or checks chips, so the listener ignores it. */
    private var showingWaves = false

    /** The waves the chips show, so a reload with the same waves doesn't rebuild them. */
    private var shownWaves: List<PlanWave>? = null

    override fun onDestroyView() {
        super.onDestroyView()
        shownWaves = null
    }

    private fun showReplan(view: View, replan: PendingReplan?) {
        view.findViewById<View>(R.id.replan_card).isVisible = replan != null
        val rows = view.findViewById<LinearLayout>(R.id.replan_rows)
        rows.removeAllViews()
        replan ?: return
        rows.addRow(
            title = getString(replan.label, replan.subject),
            subtitle = resources.getQuantityString(
                R.plurals.dispatch_to_replan,
                replan.pickupIds.size,
                replan.pickupIds.size
            ),
            value = getString(R.string.dispatch_replan_link)
        ) { home.open(ReplanFragment()) }
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
