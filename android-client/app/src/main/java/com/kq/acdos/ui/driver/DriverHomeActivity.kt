package com.kq.acdos.ui.driver

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.fragment.app.commit
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.auth.AppRole
import com.kq.acdos.data.outbox.uploadOnReconnect
import com.kq.acdos.ui.EXTRA_FULL_NAME
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openLoginWhenSessionEnds
import com.kq.acdos.ui.openProfile
import kotlinx.coroutines.launch

/**
 * The Driver role's home: Route, Schedule and Sync tabs, and Profile (#231)
 * in the overflow menu, which has the theme and Sign out. Reached only through the role in profiles (#30). Refreshes
 * the route each time it comes to the front (#123).
 */
class DriverHomeActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }
    private val refresh: RouteRefreshViewModel by viewModels { RouteRefreshViewModel.Factory }

    /** The first start of this screen refreshes past the throttle. */
    private var firstStart = true

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_driver_home)
        applySystemBarPadding(findViewById(R.id.main), findViewById(R.id.bottom_nav))

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.title = intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        toolbar.setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.action_profile) openProfile(AppRole.DRIVER)
            item.itemId == R.id.action_profile
        }

        val tabs = findViewById<BottomNavigationView>(R.id.bottom_nav)
        tabs.setOnItemSelectedListener { item ->
            show(
                when (item.itemId) {
                    R.id.tab_schedule -> ScheduleFragment()
                    R.id.tab_sync -> SyncFragment()
                    else -> RouteFragment()
                }
            )
            true
        }
        // After a rotation the FragmentManager restores the open tab by itself.
        if (savedInstanceState == null) show(RouteFragment())

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                refresh.messages.collect { message ->
                    Snackbar.make(findViewById(R.id.main), message, Snackbar.LENGTH_LONG)
                        .setAnchorView(tabs)
                        .show()
                }
            }
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                uploadOnReconnect(container.connectivity.network, container::sendPickupEvents)
            }
        }

        openLoginWhenSessionEnds(container)
    }

    /** Each tab names itself. Null falls back to the driver's name. */
    fun showHeader(title: String?, subtitle: String?) {
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.title = title ?: intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        toolbar.subtitle = subtitle
    }

    override fun onStart() {
        super.onStart()
        refresh.refreshOnStart(first = firstStart)
        firstStart = false
        // Pickups recorded with no signal go up as soon as the driver is back.
        container.uploadPickupEvents()
    }

    private fun show(tab: Fragment) {
        supportFragmentManager.commit { replace(R.id.tab_container, tab) }
    }
}
