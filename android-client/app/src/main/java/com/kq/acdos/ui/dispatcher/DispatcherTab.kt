package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import androidx.annotation.IdRes
import androidx.fragment.app.Fragment
import androidx.fragment.app.FragmentManager
import androidx.fragment.app.commit
import com.kq.acdos.R

/** The dispatcher's bottom-nav tabs (#230), and the screen each one starts on. */
enum class DispatcherTab(@IdRes val itemId: Int, val root: () -> Fragment) {
    OVERVIEW(R.id.tab_overview, ::DispatchHubFragment),
    PLAN(R.id.tab_plan, ::OptimisationRunFragment),
    ROUTES(R.id.tab_routes, ::RoutesFragment),
    FLEET(R.id.tab_fleet, ::FleetCrewFragment),
    MESSAGES(R.id.tab_messages, ::MessagesFragment);

    /** The FragmentManager tag of this tab's [TabHostFragment]. */
    val tag get() = "tab_$name"

    companion object {
        fun of(@IdRes itemId: Int) = entries.first { it.itemId == itemId }
    }
}

/**
 * One tab and its own back stack. The tab's screens live in this fragment's
 * child FragmentManager, so a drill-down (a route, Re-plan, Import roster)
 * stays inside its tab with the nav bar showing, and each tab is where it was
 * when the dispatcher comes back to it.
 */
class TabHostFragment : Fragment(R.layout.fragment_tab_host) {
    val tab get() = DispatcherTab.valueOf(requireArguments().getString(ARG_TAB)!!)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Restored with its screens after a rotation; only a new tab needs its first one.
        if (savedInstanceState == null) {
            childFragmentManager.commit {
                setReorderingAllowed(true)
                add(R.id.tab_screen, tab.root())
            }
        }
        childFragmentManager.addOnBackStackChangedListener {
            (activity as? DispatcherHomeActivity)?.updateBack()
        }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (activity as? DispatcherHomeActivity)?.updateBack()
    }

    /** True when a screen is open on top of the tab's first one. */
    val drilledDown get() = childFragmentManager.backStackEntryCount > 0

    fun open(screen: Fragment) {
        childFragmentManager.commit {
            setReorderingAllowed(true)
            replace(R.id.tab_screen, screen)
            addToBackStack(null)
        }
    }

    fun back() = childFragmentManager.popBackStack()

    /** Back to the tab's first screen, as when its tab is tapped again. */
    fun backToStart() {
        if (drilledDown) {
            val first = childFragmentManager.getBackStackEntryAt(0).id
            childFragmentManager.popBackStack(first, FragmentManager.POP_BACK_STACK_INCLUSIVE)
        }
    }

    companion object {
        private const val ARG_TAB = "tab"

        fun of(tab: DispatcherTab) = TabHostFragment().apply {
            arguments = Bundle().apply { putString(ARG_TAB, tab.name) }
        }
    }
}
