package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import androidx.fragment.app.Fragment
import androidx.fragment.app.commit
import com.google.android.material.tabs.TabLayout
import com.kq.acdos.R

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
        tabs.getTabAt(if (showing is VehiclesFragment) VEHICLES else PICKUPS)?.select()
        tabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                show(if (tab.position == VEHICLES) VehiclesFragment() else PickupsFragment())
            }

            override fun onTabUnselected(tab: TabLayout.Tab) = Unit

            override fun onTabReselected(tab: TabLayout.Tab) = Unit
        })
    }

    override fun onStart() {
        super.onStart()
        home.showTitle(getString(R.string.dispatch_fleet_title))
    }

    private fun show(list: Fragment) {
        childFragmentManager.commit {
            setReorderingAllowed(true)
            replace(R.id.fleet_screen, list)
        }
    }

    private companion object {
        const val PICKUPS = 0
        const val VEHICLES = 1
    }
}
