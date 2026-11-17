package com.kq.acdos.ui.dispatcher

import android.content.ContentResolver
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.StringRes
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.R
import com.kq.acdos.data.remote.RejectReasonDto
import com.kq.acdos.data.remote.RosterImportResultDto
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** What the system file picker may offer: CSV under the names apps give it. */
internal val ROSTER_TYPES = arrayOf("text/csv", "text/comma-separated-values")

/**
 * Opens the system file picker (SAF) for a roster CSV and hands what's chosen to [roster].
 * Made as a property, so it is registered before the fragment is created, as the Activity
 * Result API requires.
 */
internal fun Fragment.rosterPicker(
    roster: () -> RosterImportViewModel,
    chosen: () -> Unit
): ActivityResultLauncher<Array<String>> =
    registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@registerForActivityResult
        val resolver = requireContext().contentResolver
        viewLifecycleOwner.lifecycleScope.launch {
            val file = withContext(Dispatchers.IO) { readRoster(resolver, uri) }
            if (file == null) {
                Toast.makeText(requireContext(), R.string.roster_unreadable, Toast.LENGTH_LONG)
                    .show()
            } else {
                roster().choose(file.first, file.second)
                chosen()
            }
        }
    }

/**
 * The file's name and bytes: at most one byte over the limit, which is enough for the
 * ViewModel to refuse it. Null if it can't be read.
 */
private fun readRoster(resolver: ContentResolver, uri: Uri): Pair<String, ByteArray>? = try {
    val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
        ?.use { if (it.moveToFirst()) it.getString(0) else null }
        ?: "roster.csv"
    val bytes = resolver.openInputStream(uri)?.use { it.readAtMost(ROSTER_MAX_BYTES + 1) }
    bytes?.let { name to it }
} catch (e: IOException) {
    null
} catch (e: SecurityException) {
    null
}

/** Up to [limit] bytes: a huge file is never read whole into memory. */
private fun InputStream.readAtMost(limit: Int): ByteArray {
    val out = ByteArrayOutputStream()
    val buffer = ByteArray(8 * 1024)
    while (out.size() < limit) {
        val read = read(buffer, 0, minOf(buffer.size, limit - out.size()))
        if (read < 0) break
        out.write(buffer, 0, read)
    }
    return out.toByteArray()
}

/**
 * Import roster (#229): the dry run's counts, each given pickup point's nearest zone and
 * distance (#245), and the rows it would skip, then "Import N pickups". Nothing is written until that tap. The import starts no re-plan; the dispatcher
 * runs optimisation as usual.
 */
class RosterImportFragment : Fragment(R.layout.fragment_roster_import) {
    private val roster: RosterImportViewModel by activityViewModels {
        RosterImportViewModel.Factory
    }
    private val dispatcher: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    private val picker = rosterPicker({ roster }) {}

    // In onStart, not onViewCreated: a screen names itself again when its tab comes back.
    override fun onStart() {
        super.onStart()
        home.showTitle(getString(R.string.roster_import))
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        view.findViewById<Button>(R.id.import_now).setOnClickListener { roster.importNow() }
        view.findViewById<Button>(R.id.retry).setOnClickListener { roster.retry() }
        val other = view.findViewById<Button>(R.id.other_file)
        other.setOnClickListener {
            if (roster.state.value.imported != null) {
                home.close()
            } else {
                picker.launch(ROSTER_TYPES)
            }
        }

        var reloaded = false
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                roster.state.collect { state ->
                    show(view, state)
                    // The new pickups belong on the day's board straight away.
                    if (state.imported != null && !reloaded) {
                        reloaded = true
                        dispatcher.load()
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        // Leaving after an import: the next visit starts from a new file.
        if (!requireActivity().isChangingConfigurations && roster.state.value.imported != null) {
            roster.clear()
        }
        super.onDestroy()
    }

    private fun show(view: View, state: RosterImportState) {
        view.findViewById<TextView>(R.id.file_name).text = state.fileName
        view.findViewById<View>(R.id.busy).isVisible = state.busy
        val result = state.imported ?: state.check
        view.findViewById<TextView>(R.id.status).text = when {
            state.failure != null -> getString(state.failure.text, state.failure.detail)
            state.busy && state.check == null -> getString(R.string.roster_checking)
            state.busy -> getString(R.string.roster_importing)
            state.imported != null -> getString(R.string.roster_imported)
            state.check?.pickupsCreated == 0 -> getString(R.string.roster_nothing_to_import)
            state.check != null -> getString(R.string.roster_checked)
            else -> ""
        }

        view.findViewById<View>(R.id.summary_card).isVisible = result != null
        result?.let { showSummary(view, it) }
        showLocations(view, result)
        showRejected(view, result)

        view.findViewById<Button>(R.id.import_now).apply {
            isVisible = state.check != null && state.imported == null
            isEnabled = state.canImport
            text = resources.getQuantityString(
                R.plurals.roster_import_pickups,
                state.check?.pickupsCreated ?: 0,
                state.check?.pickupsCreated ?: 0
            )
        }
        view.findViewById<View>(R.id.retry).isVisible = state.failure != null && !state.busy
        view.findViewById<Button>(R.id.other_file).apply {
            setText(
                if (state.imported !=
                    null
                ) {
                    R.string.roster_done
                } else {
                    R.string.roster_choose_other
                }
            )
            isEnabled = !state.busy
        }
    }

    private fun showSummary(view: View, result: RosterImportResultDto) {
        detail(view, R.id.rows_in_file, R.string.roster_rows_in_file, result.rows)
        detail(view, R.id.crew_created, R.string.roster_crew_created, result.crewCreated)
        detail(view, R.id.crew_updated, R.string.roster_crew_updated, result.crewUpdated)
        val pickups = if (result.dryRun) {
            R.string.roster_pickups_to_import
        } else {
            R.string.roster_pickups_imported
        }
        detail(view, R.id.pickups, pickups, result.pickupsCreated)
        detail(view, R.id.rows_rejected, R.string.roster_rows_rejected, result.rowsRejected)
    }

    private fun detail(view: View, id: Int, @StringRes label: Int, value: Int) {
        val row = view.findViewById<View>(id)
        row.findViewById<TextView>(R.id.detail_label).setText(label)
        row.findViewById<TextView>(R.id.detail_value).text = value.toString()
    }

    private fun showLocations(view: View, result: RosterImportResultDto?) {
        val shown = result?.let { locationRows(it, ::getString) }.orEmpty()
        for (id in listOf(R.id.locations_label, R.id.locations_card, R.id.locations_hint)) {
            view.findViewById<View>(id).isVisible = shown.isNotEmpty()
        }
        val rows = view.findViewById<LinearLayout>(R.id.location_rows)
        rows.removeAllViews()
        for (row in shown) rows.addRow(title = row.zone, subtitle = row.detail, lead = row.line)
    }

    private fun showRejected(view: View, result: RosterImportResultDto?) {
        val rejected = result?.rejected.orEmpty()
        view.findViewById<View>(R.id.rejected_label).isVisible = rejected.isNotEmpty()
        view.findViewById<View>(R.id.rejected_card).isVisible = rejected.isNotEmpty()
        val rows = view.findViewById<LinearLayout>(R.id.rejected_rows)
        rows.removeAllViews()
        for (row in rejected) {
            rows.addRow(
                title = getString(rejectReasonLabel(row.reason)),
                subtitle = getString(
                    R.string.roster_rejected_subtitle,
                    row.staffNo ?: getString(R.string.roster_no_staff_no),
                    row.detail
                ),
                lead = row.line.toString()
            )
        }
    }
}

/** One pickup point in the preview (#245): its line, nearest zone, and who and how far. */
internal data class LocationRow(val line: String, val zone: String, val detail: String)

/**
 * The given pickup points, in line order. Whether one is outside comes from the rows the
 * server rejected, not from the rounded distance: 10.04 km shows as 10.0 but is outside.
 */
internal fun locationRows(result: RosterImportResultDto, text: (Int) -> String): List<LocationRow> {
    val outside = result.rejected
        .filter { it.reason == RejectReasonDto.OUTSIDE_PICKUP_ZONES }
        .map { it.line }
        .toSet()
    return result.locations.map { location ->
        val format = if (location.line in outside) {
            R.string.roster_location_outside
        } else {
            R.string.roster_location_near
        }
        LocationRow(
            line = location.line.toString(),
            zone = location.zoneLabel,
            detail = String.format(
                Locale.getDefault(),
                text(format),
                location.staffNo,
                location.distanceKm
            )
        )
    }
}

@StringRes
internal fun rejectReasonLabel(reason: RejectReasonDto): Int = when (reason) {
    RejectReasonDto.INVALID_ROW -> R.string.roster_reason_invalid_row
    RejectReasonDto.OUTSIDE_PICKUP_ZONES -> R.string.roster_reason_outside_zones
    RejectReasonDto.REPORT_TIME_PAST -> R.string.roster_reason_report_time_past
    RejectReasonDto.DUPLICATE_PICKUP -> R.string.roster_reason_duplicate
    RejectReasonDto.NO_PICKUP_LOCATION -> R.string.roster_reason_no_location
    RejectReasonDto.SET_HOME_NEEDS_LOCATION -> R.string.roster_reason_set_home_no_location
}
