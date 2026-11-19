package com.kq.acdos.ui.dispatcher

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.core.widget.doAfterTextChanged
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.ChipGroup
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import com.kq.acdos.R
import com.kq.acdos.data.remote.PickupRequestTypeDto
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.driver.initials
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZonedDateTime
import kotlinx.coroutines.launch

/**
 * Add pickup (#253), opened from Fleet & crew → Pickups: find the crew member by
 * name or staff number, pick the Nairobi date and time, rostered or standby, and
 * pick them up from home or from a pin on the map. The server checks it the same
 * way as a roster row. Saving starts no re-plan.
 */
class AddPickupFragment : Fragment(R.layout.fragment_add_pickup) {
    private val entry: PickupEntryViewModel by activityViewModels { PickupEntryViewModel.Factory }
    private val dispatcher: DispatcherViewModel by activityViewModels {
        DispatcherViewModel.Factory
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) entry.startAddPickup()
    }

    override fun onStart() {
        super.onStart()
        home.showTitle(getString(R.string.add_pickup))
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val search = view.findViewById<TextInputEditText>(R.id.crew_search)
        search.doAfterTextChanged { text ->
            // Only typing searches: the text set for a chosen crew member doesn't.
            if (entry.addPickup.value.crew == null) entry.search(text?.toString().orEmpty())
        }
        view.findViewById<Button>(R.id.report_time).setOnClickListener { pickReportTime() }
        view.findViewById<ChipGroup>(R.id.type).setOnCheckedStateChangeListener { _, checked ->
            val standby = checked.firstOrNull() == R.id.type_standby
            val type = if (standby) PickupRequestTypeDto.STANDBY else PickupRequestTypeDto.ROSTERED
            entry.setType(type)
        }
        view.findViewById<RadioButton>(R.id.place_home).setOnClickListener { entry.useHome() }
        view.findViewById<RadioButton>(R.id.place_pin).setOnClickListener {
            home.open(PinPickerFragment.forAddPickup())
        }
        view.findViewById<Button>(R.id.save).setOnClickListener { entry.save() }

        var reloaded = false
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                entry.addPickup.collect { state ->
                    show(view, state)
                    if (state.added != null && !reloaded) {
                        reloaded = true
                        // The new pickup belongs on the day's board straight away.
                        dispatcher.load()
                        // On the activity's root: this screen closes straight away.
                        val root = requireActivity().findViewById<View>(R.id.main)
                        Snackbar.make(root, R.string.add_pickup_added, Snackbar.LENGTH_LONG)
                            .setAnchorView(R.id.bottom_nav)
                            .show()
                        home.close()
                    }
                }
            }
        }
    }

    private fun show(view: View, state: AddPickupState) {
        val crew = state.crew
        view.findViewById<TextInputLayout>(R.id.crew_search_layout).isVisible = crew == null
        val rows = view.findViewById<LinearLayout>(R.id.crew_rows)
        rows.removeAllViews()
        if (crew != null) {
            // The chosen crew member, tapped to choose someone else.
            rows.addRow(
                title = crew.name,
                subtitle = crew.staffNo,
                value = getString(R.string.add_pickup_change),
                lead = initials(crew.name)
            ) { entry.chooseCrew(null) }
        } else {
            state.results.forEach { found ->
                rows.addRow(
                    title = found.name,
                    subtitle = found.staffNo,
                    lead = initials(found.name)
                ) { entry.chooseCrew(found) }
            }
            val noMatch = state.results.isEmpty() && !state.searching &&
                state.query.trim().length >= PickupEntryViewModel.MIN_QUERY
            if (noMatch) rows.addRow(getString(R.string.add_pickup_no_match))
        }
        view.findViewById<View>(R.id.crew_card).isVisible = rows.childCount > 0

        view.findViewById<Button>(R.id.report_time).text = state.reportTime?.let {
            Times.clockWithDay(it)
        } ?: getString(R.string.add_pickup_pick_time)

        view.findViewById<RadioButton>(R.id.place_home).apply {
            text = crew?.let {
                val zone = it.homeZoneLabel ?: getString(R.string.dispatch_no_value)
                getString(R.string.add_pickup_home_zone, zone)
            } ?: getString(R.string.add_pickup_home)
            isChecked = state.place is PickupPlace.Home
        }
        view.findViewById<RadioButton>(R.id.place_pin).apply {
            val pin = state.place as? PickupPlace.Pin
            text = pin?.let {
                getString(R.string.add_pickup_pin_zone, it.nearest.zoneLabel, kmText(it.nearest))
            } ?: getString(R.string.add_pickup_different)
            isChecked = pin != null
        }

        view.findViewById<TextView>(R.id.failure).apply {
            text = state.failure?.let { getString(it.text, it.detail) }
            isVisible = state.failure != null
        }
        view.findViewById<Button>(R.id.save).isEnabled = state.canSave
    }

    /** A Nairobi date, then the time on it; the default is the day the board shows. */
    private fun pickReportTime() {
        val shown = entry.addPickup.value.reportTime?.atZone(Times.ZONE)
        val day = shown?.toLocalDate() ?: dispatcher.state.value.date
        DatePickerDialog(requireContext(), { _, year, month, dayOfMonth ->
            val date = LocalDate.of(year, month + 1, dayOfMonth)
            val time = shown?.toLocalTime() ?: LocalTime.of(DEFAULT_HOUR, 0)
            TimePickerDialog(requireContext(), { _, hour, minute ->
                val chosen = ZonedDateTime.of(date, LocalTime.of(hour, minute), Times.ZONE)
                entry.setReportTime(chosen.toInstant())
            }, time.hour, time.minute, true).show()
        }, day.year, day.monthValue - 1, day.dayOfMonth).show()
    }

    private companion object {
        /** The start of the early bank, where most pickups are. */
        const val DEFAULT_HOUR = 5
    }
}
