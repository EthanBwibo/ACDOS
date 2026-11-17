package com.kq.acdos.ui.crew

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.fragment.app.commit
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.auth.AppRole
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openLoginWhenSessionEnds
import com.kq.acdos.ui.openProfile
import com.kq.acdos.ui.showStatusBanners
import kotlinx.coroutines.flow.flowOf

/**
 * The Crew role's home (#56): Pickup and Message tabs, and Profile (#231) in
 * the overflow menu, which has the theme and Sign out. Reached only through
 * the role in profiles (#30).
 */
class CrewHomeActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_crew_home)
        applySystemBarPadding(findViewById(R.id.main), findViewById(R.id.bottom_nav))

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.action_profile) openProfile(AppRole.CREW)
            item.itemId == R.id.action_profile
        }

        findViewById<BottomNavigationView>(R.id.bottom_nav).setOnItemSelectedListener { item ->
            show(
                if (item.itemId == R.id.tab_pickup) CrewPickupFragment() else CrewMessageFragment()
            )
            true
        }
        // After a rotation the FragmentManager restores the open tab by itself.
        if (savedInstanceState == null) show(CrewPickupFragment())

        // Each tab reports its own failed load, so only offline shows here.
        showStatusBanners(container, R.string.crew_offline_banner, flowOf(null))

        openLoginWhenSessionEnds(container)
    }

    /** Each tab names itself, including when a rotation restores it. */
    fun showTitle(@StringRes title: Int) {
        findViewById<MaterialToolbar>(R.id.toolbar).setTitle(title)
    }

    private fun show(tab: Fragment) {
        supportFragmentManager.commit { replace(R.id.tab_container, tab) }
    }
}
