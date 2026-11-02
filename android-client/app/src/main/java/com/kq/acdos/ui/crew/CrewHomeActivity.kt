package com.kq.acdos.ui.crew

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.fragment.app.commit
import androidx.lifecycle.lifecycleScope
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.ui.EXTRA_FULL_NAME
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.driver.ComingSoonFragment
import com.kq.acdos.ui.openLoginWhenSessionEnds
import kotlinx.coroutines.launch

/**
 * The Crew role's home (#56): Pickup and Message tabs, and Sign out in the
 * overflow menu. Reached only through the role in profiles (#30). The
 * Message tab waits for the preset messages (#57).
 */
class CrewHomeActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_crew_home)
        applySystemBarPadding(findViewById(R.id.main))

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.title = intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        toolbar.setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.action_sign_out) {
                // Only ends the session; openLoginWhenSessionEnds does the navigating.
                lifecycleScope.launch { container.sessionRouter.signOut() }
                true
            } else {
                false
            }
        }

        findViewById<BottomNavigationView>(R.id.bottom_nav).setOnItemSelectedListener { item ->
            show(if (item.itemId == R.id.tab_pickup) CrewPickupFragment() else ComingSoonFragment())
            true
        }
        // After a rotation the FragmentManager restores the open tab by itself.
        if (savedInstanceState == null) show(CrewPickupFragment())

        openLoginWhenSessionEnds(container)
    }

    private fun show(tab: Fragment) {
        supportFragmentManager.commit { replace(R.id.tab_container, tab) }
    }
}
