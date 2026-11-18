package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.commitNow
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.auth.AppRole
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openLoginWhenSessionEnds
import com.kq.acdos.ui.openProfile
import com.kq.acdos.ui.showStatusBanners
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * The dispatcher's app (#27): five bottom-nav tabs (#230), Overview, Plan,
 * Routes, Fleet & crew and Messages. Each tab is a [TabHostFragment] with its
 * own back stack, so a drill-down opens inside its tab with the nav bar
 * showing. All the screens share these ViewModels, so a job started on one
 * keeps running on the others. Online only: nothing here is cached.
 *
 * A tab that isn't selected is hidden and held at CREATED with
 * setMaxLifecycle, so its screens stop. Their collectors pause, so a hidden
 * screen can't change the title. Messages gets onStop, so a message selected
 * while another tab is showing isn't marked read.
 */
class DispatcherHomeActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }
    private val viewModel: DispatcherViewModel by viewModels { DispatcherViewModel.Factory }
    private val inbox: InboxViewModel by viewModels { InboxViewModel.Factory }

    private lateinit var toolbar: MaterialToolbar
    private lateinit var tabs: BottomNavigationView

    /** The selected tab. */
    var current = DispatcherTab.OVERVIEW
        private set

    /** Back closes a drill-down, then goes to Overview, then leaves the app. */
    private val back = object : OnBackPressedCallback(false) {
        override fun handleOnBackPressed() {
            val host = host(current)
            if (host?.drilledDown == true) host.back() else selectTab(DispatcherTab.OVERVIEW)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_dispatcher_home)
        val root = findViewById<View>(R.id.main)
        tabs = findViewById(R.id.bottom_nav)
        applySystemBarPadding(root, tabs)

        toolbar = findViewById(R.id.toolbar)
        toolbar.setNavigationOnClickListener { close() }
        toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_refresh -> {
                    viewModel.load()
                    inbox.load()
                    true
                }

                R.id.action_profile -> {
                    openProfile(AppRole.DISPATCHER)
                    true
                }

                else -> false
            }
        }
        onBackPressedDispatcher.addCallback(this, back)
        // After a rotation the FragmentManager restores every tab and its screens by itself.
        savedInstanceState?.getString(STATE_TAB)?.let { current = DispatcherTab.valueOf(it) }
        tabs.setOnItemSelectedListener { item ->
            showTab(DispatcherTab.of(item.itemId))
            true
        }
        tabs.setOnItemReselectedListener { host(current)?.backToStart() }
        if (savedInstanceState == null) showTab(DispatcherTab.OVERVIEW)
        updateBack()

        val loading = findViewById<LinearProgressIndicator>(R.id.loading)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(viewModel.state, inbox.loading) { state, inboxLoading ->
                    state.loading || inboxLoading
                }.collect { loading.isVisible = it }
            }
        }
        val failure = combine(viewModel.state, inbox.loadFailed) { state, inboxFailed ->
            state.loadFailure?.let { getString(it.text, it.detail) }
                ?: getString(R.string.dispatch_inbox_failed).takeIf { inboxFailed }
        }
        showStatusBanners(container, R.string.dispatch_offline_banner, failure)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    val text = getString(message.text, message.detail)
                    Snackbar.make(root, text, Snackbar.LENGTH_LONG).setAnchorView(tabs).show()
                }
            }
        }
        // A dot on Plan while a re-plan waits, wherever the breakdown or delay was recorded.
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    tabs.getOrCreateBadge(R.id.tab_plan).isVisible = state.replan != null
                }
            }
        }
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.messages.collect { messages ->
                    val unread = messages.orEmpty().count { it.readAt == null }
                    tabs.getOrCreateBadge(R.id.tab_messages).apply {
                        isVisible = unread > 0
                        number = unread
                    }
                }
            }
        }

        openLoginWhenSessionEnds(container)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_TAB, current.name)
    }

    private fun host(tab: DispatcherTab) =
        supportFragmentManager.findFragmentByTag(tab.tag) as TabHostFragment?

    /**
     * Shows [tab]'s host, adding it the first time, and stops the others:
     * each is hidden and held at CREATED, so its screens get onStop.
     */
    private fun showTab(tab: DispatcherTab) {
        current = tab
        supportFragmentManager.commitNow {
            setReorderingAllowed(true)
            for (other in DispatcherTab.entries) {
                val host = host(other)
                if (other == tab || host == null) continue
                hide(host)
                setMaxLifecycle(host, Lifecycle.State.CREATED)
            }
            val host = host(tab)
            if (host == null) {
                add(R.id.screen, TabHostFragment.of(tab), tab.tag)
            } else {
                show(host)
                setMaxLifecycle(host, Lifecycle.State.RESUMED)
            }
        }
        updateBack()
    }

    /** The list Fleet & crew shows next, asked for by an Overview tile; taken once. */
    private var fleetList: FleetList? = null

    /**
     * Switches to Fleet & crew, as the bottom nav does, and shows [list] there. The tiles are
     * on Overview, so Fleet & crew always starts again here and takes [list] in its onStart.
     * A drill-down open on that tab (Import roster) stays open, with [list] underneath it.
     */
    fun showFleet(list: FleetList) {
        fleetList = list
        selectTab(DispatcherTab.FLEET)
    }

    /** The list a tile asked for, if any; asking clears it. */
    fun takeFleetList(): FleetList? = fleetList.also { fleetList = null }

    /** Selects [tab] as if its nav item was tapped. */
    fun selectTab(tab: DispatcherTab) {
        if (tabs.selectedItemId == tab.itemId) showTab(tab) else tabs.selectedItemId = tab.itemId
    }

    /** The back arrow and the back callback follow the selected tab's back stack. */
    fun updateBack() {
        if (!::toolbar.isInitialized) return
        val drilledDown = host(current)?.drilledDown == true
        if (drilledDown) {
            toolbar.setNavigationIcon(R.drawable.ic_arrow_back)
        } else {
            toolbar.navigationIcon = null
        }
        back.isEnabled = drilledDown || current != DispatcherTab.OVERVIEW
    }

    /** Each screen names itself when it starts, including when its tab comes back. */
    fun showTitle(title: String) {
        toolbar.title = title
    }

    /** Opens [screen] on top of the selected tab's screens. */
    fun open(screen: Fragment) {
        host(current)?.open(screen)
    }

    /** Switches to [tab] and opens [screen] there: the Overview's Re-plan alert uses this. */
    fun open(tab: DispatcherTab, screen: Fragment) {
        selectTab(tab)
        host(tab)?.open(screen)
    }

    /** Closes the selected tab's top screen. */
    fun close() {
        host(current)?.back()
    }

    private companion object {
        const val STATE_TAB = "dispatcher_tab"
    }
}
