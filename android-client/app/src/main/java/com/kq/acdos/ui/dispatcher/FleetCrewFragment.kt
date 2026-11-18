package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import androidx.fragment.app.Fragment
import androidx.fragment.app.commit
import com.google.android.material.tabs.TabLayout
import com.kq.acdos.R

/** The two lists on Fleet & crew, in the order of their tabs. */
enum class FleetList { PICKUPS, VEHICLES }

/**
 * The Fleet & crew tab (#230): Pickups (with Import roster) and Vehicles,
 * one at a time under a pair of tabs. Import roster opens on top of this
 * screen, inside the bottom-nav tab.
 */
class FleetCrewFragment : Fragment(R.layout.fragment_fleet_crew) {
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val tabs = view.findViewById<TabLayout>(R.id.fleet_tabs)
        // The list on show survives the tab being hidden and a rotation, in the child manager.
        val showing = childFragmentManager.findFragmentById(R.id.fleet_screen)
        if (showing == null) show(PickupsFragment())
        val list = if (showing is VehiclesFragment) FleetList.VEHICLES else FleetList.PICKUPS
        tabs.getTabAt(list.ordinal)?.select()
        tabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                val list = FleetList.entries[tab.position]
                show(if (list == FleetList.VEHICLES) VehiclesFragment() else PickupsFragment())
            }

            override fun onTabUnselected(tab: TabLayout.Tab) = Unit

            override fun onTabReselected(tab: TabLayout.Tab) = Unit
        })
    }

    override fun onStart() {
        super.onStart()
        home.showTitle(getString(R.string.dispatch_fleet_title))
        // An Overview tile (#248) may have asked for one of the lists.
        home.takeFleetList()?.let(::select)
    }

    /** Shows [list], as if its tab was tapped. */
    fun select(list: FleetList) {
        view?.findViewById<TabLayout>(R.id.fleet_tabs)?.getTabAt(list.ordinal)?.select()
    }

    private fun show(list: Fragment) {
        childFragmentManager.commit {
            setReorderingAllowed(true)
            replace(R.id.fleet_screen, list)
        }
    }
}
