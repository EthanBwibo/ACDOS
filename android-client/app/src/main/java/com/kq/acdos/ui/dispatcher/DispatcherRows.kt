package com.kq.acdos.ui.dispatcher

import android.content.Context
import android.util.TypedValue
import android.view.LayoutInflater
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.content.res.AppCompatResources
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.kq.acdos.R
import com.kq.acdos.data.RouteNeedingVan
import com.kq.acdos.data.VanChoice
import com.kq.acdos.data.VanStatus
import com.kq.acdos.data.remote.LeftOutVehicleDto
import com.kq.acdos.data.vanChoices
import com.kq.acdos.ui.Times

/** A Figma ListRow: every list on the dispatcher's screens uses this one row. */
internal fun LinearLayout.addRow(
    title: String,
    subtitle: String? = null,
    value: String? = null,
    lead: String? = null,
    onTap: (() -> Unit)? = null
): View {
    val row = LayoutInflater.from(context).inflate(R.layout.item_list_row, this, false)
    row.findViewById<TextView>(R.id.row_title).text = title
    row.findViewById<TextView>(R.id.row_subtitle).apply {
        text = subtitle
        isVisible = subtitle != null
    }
    row.findViewById<TextView>(R.id.row_value).apply {
        text = value
        isVisible = value != null
    }
    row.findViewById<TextView>(R.id.row_lead).text = lead
    if (onTap != null) {
        val ripple = TypedValue()
        context.theme.resolveAttribute(android.R.attr.selectableItemBackground, ripple, true)
        row.foreground = AppCompatResources.getDrawable(context, ripple.resourceId)
        row.setOnClickListener { onTap() }
    }
    addView(row)
    return row
}

internal val Fragment.home get() = requireActivity() as DispatcherHomeActivity

/** "R2 · KDA 456B" */
internal fun Fragment.routeName(number: Int, plate: String) =
    getString(R.string.dispatch_route_name, number, plate)

/** "KDX 004 left out: has the 08:00–10:00 route", one line per van; null with none. */
internal fun Context.leftOutText(leftOut: List<LeftOutVehicleDto>): String? =
    leftOut.takeIf { it.isNotEmpty() }?.joinToString("\n") {
        getString(
            R.string.dispatch_left_out,
            it.plateNumber,
            Times.shortClock(it.routeDeparture),
            Times.shortClock(it.routeArrival)
        )
    }

/** Shows [leftOut] in [view], or hides it with none. */
internal fun Fragment.showLeftOut(view: TextView, leftOut: List<LeftOutVehicleDto>) {
    val text = requireContext().leftOutText(leftOut)
    view.isVisible = text != null
    view.text = text
}

/** "KDX 004 · Free from 07:15", or the plate alone for a van with no route that counts. */
internal fun Context.vanLabel(van: VanChoice): String {
    val plate = van.vehicle.plateNumber
    return when (val status = van.status) {
        VanStatus.Free -> plate

        is VanStatus.FreeFrom ->
            getString(R.string.dispatch_van_free_from, plate, Times.shortClock(status.at))

        is VanStatus.OnWave -> getString(
            R.string.dispatch_van_on_wave,
            plate,
            getString(
                R.string.dispatch_time_range,
                Times.shortClock(status.first),
                Times.shortClock(status.last)
            )
        )

        is VanStatus.LaterRoute ->
            getString(R.string.dispatch_van_later_route, plate, Times.shortClock(status.departure))
    }
}

/** "KDX 004's 08:00–10:00 route needs a van" */
internal fun Context.needsVanText(route: RouteNeedingVan): String = getString(
    R.string.dispatch_route_needs_van,
    route.plate,
    Times.shortClock(route.departure),
    Times.shortClock(route.arrival)
)

internal fun Fragment.jobText(job: JobUi): String = when (job) {
    JobUi.None -> ""

    JobUi.Queued -> getString(R.string.dispatch_job_queued)

    JobUi.Running -> getString(R.string.dispatch_job_running)

    is JobUi.Done -> getString(R.string.dispatch_job_done, job.routes, job.late, job.unassigned)

    is JobUi.Failed -> job.error?.let { getString(R.string.dispatch_job_failed, it) }
        ?: getString(R.string.dispatch_job_failed_unknown)
}

/**
 * The vans a job for [pickupIds] may use, with each one's status for their
 * wave (#274): "Free from 07:15" (its earlier route is due in, plus the
 * turnaround) starts ticked, like a van with no route; "On wave 04:00–06:30"
 * and "Later route 08:15" start unticked, and the dispatcher can still tick
 * them. Broken-down and unavailable vans are not offered.
 */
internal fun Fragment.pickVans(
    viewModel: DispatcherViewModel,
    pickupIds: List<String>,
    start: (List<String>) -> Unit
) {
    val board = viewModel.state.value.board ?: return
    val vans = vanChoices(board, pickupIds)
    // None to offer: let the ViewModel say so.
    if (vans.isEmpty()) return start(emptyList())
    val labels = vans.map { requireContext().vanLabel(it) }
    val ticked = BooleanArray(vans.size) { vans[it].tickedByDefault }
    MaterialAlertDialogBuilder(requireContext())
        .setTitle(R.string.dispatch_pick_vans)
        .setMultiChoiceItems(labels.toTypedArray(), ticked) { _, i, on ->
            ticked[i] = on
        }
        .setPositiveButton(R.string.dispatch_start_job) { _, _ ->
            start(vans.filterIndexed { i, _ -> ticked[i] }.map { it.vehicle.id })
        }
        .setNegativeButton(R.string.action_cancel, null)
        .show()
}
