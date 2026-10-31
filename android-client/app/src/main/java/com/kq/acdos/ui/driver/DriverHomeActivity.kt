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
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.ui.EXTRA_FULL_NAME
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openLoginWhenSessionEnds
import kotlinx.coroutines.launch

/**
 * The Driver role's home: Route, Schedule and Sync tabs, and Sign out in the
 * overflow menu. Reached only through the role in profiles (#30). Refreshes
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
        applySystemBarPadding(findViewById(R.id.main))

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.title = intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_sign_out -> {
                    confirmSignOut()
                    true
                }

                else -> false
            }
        }

        val tabs = findViewById<BottomNavigationView>(R.id.bottom_nav)
        tabs.setOnItemSelectedListener { item ->
            show(if (item.itemId == R.id.tab_route) RouteFragment() else ComingSoonFragment())
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

        openLoginWhenSessionEnds(container)
    }

    override fun onStart() {
        super.onStart()
        refresh.refreshOnStart(first = firstStart)
        firstStart = false
    }

    private fun show(tab: Fragment) {
        supportFragmentManager.commit { replace(R.id.tab_container, tab) }
    }

    /**
     * Sign-out keeps this driver's unsynced pickup events (#118), but the
     * driver is told first how many are waiting.
     */
    private fun confirmSignOut() {
        lifecycleScope.launch {
            val driverId = container.authRepository.storedSessionUserId()
            val unsynced =
                driverId?.let { container.database.pendingPickupEventDao().countPending(it) } ?: 0
            if (unsynced == 0) {
                signOut()
            } else {
                MaterialAlertDialogBuilder(this@DriverHomeActivity)
                    .setMessage(
                        resources.getQuantityString(R.plurals.sign_out_unsynced, unsynced, unsynced)
                    )
                    .setPositiveButton(R.string.action_sign_out) { _, _ -> signOut() }
                    .setNegativeButton(R.string.action_cancel, null)
                    .show()
            }
        }
    }

    /** Only ends the session; openLoginWhenSessionEnds does the navigating. */
    private fun signOut() {
        lifecycleScope.launch { container.sessionRouter.signOut() }
    }
}
