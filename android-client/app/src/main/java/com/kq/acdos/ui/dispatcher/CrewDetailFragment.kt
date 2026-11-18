package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.R
import com.kq.acdos.data.remote.CrewListItemDto
import com.kq.acdos.ui.humanise
import kotlinx.coroutines.launch

/**
 * One crew member (#253), opened from the Crew list: staff number, role and home
 * zone, and Set home, which opens the map pin picker. A new home counts from now
 * on; pickups already stored keep their points.
 */
class CrewDetailFragment : Fragment(R.layout.fragment_crew_detail) {
    private val entry: PickupEntryViewModel by activityViewModels { PickupEntryViewModel.Factory }

    override fun onStart() {
        super.onStart()
        home.showTitle(entry.crewDetail.value?.name.orEmpty())
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        view.findViewById<View>(R.id.set_home).setOnClickListener {
            home.open(PinPickerFragment.forSetHome())
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                entry.crewDetail.collect { crew ->
                    // Gone after the process was killed: back to the list.
                    if (crew == null) home.close() else show(view, crew)
                }
            }
        }
    }

    private fun show(view: View, crew: CrewListItemDto) {
        val rows = view.findViewById<LinearLayout>(R.id.rows)
        rows.removeAllViews()
        val none = getString(R.string.dispatch_no_value)
        val details = listOf(
            R.string.crew_staff_no to (crew.staffNo ?: none),
            R.string.profile_crew_role to humanise(crew.crewRole),
            R.string.profile_home_zone to (crew.homeZoneLabel ?: none)
        )
        val gap = (8 * resources.displayMetrics.density).toInt()
        for ((label, value) in details) {
            val row = LayoutInflater.from(view.context)
                .inflate(R.layout.view_detail_row, rows, false)
            row.findViewById<TextView>(R.id.detail_label).setText(label)
            row.findViewById<TextView>(R.id.detail_value).text = value
            if (rows.childCount > 0) (row.layoutParams as LinearLayout.LayoutParams).topMargin = gap
            rows.addView(row)
        }
    }
}
