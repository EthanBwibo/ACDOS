package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.core.widget.doAfterTextChanged
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.textfield.TextInputEditText
import com.kq.acdos.R
import com.kq.acdos.data.remote.CrewListItemDto
import com.kq.acdos.ui.driver.initials
import kotlinx.coroutines.launch

/**
 * The Crew list under Fleet & crew (#253): everyone on the roster in name order,
 * searched by name or staff number, 20 at a time. A row opens Crew detail, where
 * the dispatcher can set the crew member's home.
 */
class CrewListFragment : Fragment(R.layout.fragment_crew_list) {
    private val entry: PickupEntryViewModel by activityViewModels { PickupEntryViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val search = view.findViewById<TextInputEditText>(R.id.crew_search)
        search.setText(entry.crewList.value.query)
        search.doAfterTextChanged { entry.searchCrewList(it?.toString().orEmpty()) }
        view.findViewById<View>(R.id.load_more).setOnClickListener { entry.loadMoreCrew() }
        entry.loadCrewList()

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                entry.crewList.collect { show(view, it) }
            }
        }
    }

    private fun show(view: View, state: CrewListState) {
        val rows = view.findViewById<LinearLayout>(R.id.rows)
        rows.removeAllViews()
        state.items.forEach { crew ->
            rows.addRow(
                title = crew.name,
                subtitle = crewSubtitle(crew),
                lead = initials(crew.name)
            ) { open(crew) }
        }
        if (state.loaded && state.items.isEmpty()) rows.addRow(getString(R.string.crew_none))
        view.findViewById<View>(R.id.load_more).apply {
            isVisible = state.nextCursor != null
            isEnabled = !state.loading
        }
        view.findViewById<TextView>(R.id.failure).apply {
            text = state.failure?.let { getString(it.text, it.detail) }
            isVisible = state.failure != null
        }
    }

    /** "KQ1001 · Westlands": staff number and home zone. */
    private fun crewSubtitle(crew: CrewListItemDto): String =
        listOfNotNull(crew.staffNo, crew.homeZoneLabel).joinToString(" · ")

    private fun open(crew: CrewListItemDto) {
        entry.openCrew(crew)
        home.open(CrewDetailFragment())
    }
}
