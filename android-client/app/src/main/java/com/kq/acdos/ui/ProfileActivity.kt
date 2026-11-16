package com.kq.acdos.ui

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButton
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.auth.AppRole
import com.kq.acdos.data.CrewPickupRepository
import com.kq.acdos.data.ProfileRepository
import com.kq.acdos.data.local.CrewDao
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.MyProfileDao
import com.kq.acdos.data.local.MyProfileEntity
import com.kq.acdos.ui.driver.initials
import java.time.Instant
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch

/** Starts the Profile screen from a crew or driver home screen, with the name it was given. */
fun Activity.openProfile(role: AppRole) {
    startActivity(
        Intent(this, ProfileActivity::class.java)
            .putExtra(ProfileActivity.EXTRA_ROLE, role.name)
            .putExtra(EXTRA_FULL_NAME, intent.getStringExtra(EXTRA_FULL_NAME))
    )
}

/** What the Profile screen shows from Room: the details and, for crew, the next pickup. */
data class ProfileContent(val details: MyProfileEntity?, val pickup: CrewPickupEntity?)

class ProfileViewModel(
    private val profiles: MyProfileDao,
    private val crew: CrewDao,
    private val repository: ProfileRepository?,
    private val crewPickups: CrewPickupRepository?
) : ViewModel() {
    fun content(role: AppRole): Flow<ProfileContent> = combine(
        profiles.observe(),
        if (role == AppRole.CREW) crew.observePickup() else flowOf(null),
        ::ProfileContent
    )

    /** Quietly: with no signal the "Updated" line shows how old the copy is. */
    fun refresh(role: AppRole) {
        viewModelScope.launch {
            repository?.refresh(role)
            if (role == AppRole.CREW) crewPickups?.refresh()
        }
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                val container = (app as AcdosApplication).container
                ProfileViewModel(
                    container.database.myProfileDao(),
                    container.database.crewDao(),
                    container.profileRepository,
                    container.crewPickupRepository
                )
            }
        }
    }
}

/**
 * The crew member's or driver's own details, read-only (#231), opened from
 * the overflow menu rather than a tab. The roster is the source of truth for
 * the home location, so nothing here can be edited. Sign out and the theme
 * are here instead of the menu.
 */
class ProfileActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }
    private val viewModel: ProfileViewModel by viewModels { ProfileViewModel.Factory }
    private val role by lazy {
        AppRole.valueOf(intent.getStringExtra(EXTRA_ROLE) ?: error("no role"))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_profile)
        applySystemBarPadding(findViewById(R.id.main))
        findViewById<MaterialToolbar>(R.id.toolbar).setNavigationOnClickListener { finish() }

        val name = intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        findViewById<TextView>(R.id.name).text = name
        findViewById<TextView>(R.id.avatar).text = initials(name)
        findViewById<TextView>(R.id.role).setText(
            if (role == AppRole.CREW) R.string.profile_role_crew else R.string.profile_role_driver
        )
        findViewById<MaterialButton>(R.id.theme).apply {
            text = getString(R.string.login_theme, getString(container.themeStore.mode().label))
            setOnClickListener { showThemeDialog(container.themeStore) }
        }
        findViewById<MaterialButton>(R.id.sign_out).setOnClickListener {
            if (role == AppRole.DRIVER) confirmSignOut() else signOut()
        }

        val rows = findViewById<LinearLayout>(R.id.rows)
        val updated = findViewById<TextView>(R.id.updated)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.content(role).collect { content ->
                    val shown = profileRows(
                        role,
                        content.details,
                        content.pickup,
                        Instant.now(),
                        ::getString
                    )
                    show(rows, shown)
                    updated.text = content.details?.let {
                        getString(R.string.route_updated, Times.clockWithDay(it.fetchedAt))
                    } ?: getString(R.string.profile_not_loaded)
                }
            }
        }

        openLoginWhenSessionEnds(container)
    }

    override fun onStart() {
        super.onStart()
        viewModel.refresh(role)
    }

    private fun show(container: LinearLayout, rows: List<ProfileRow>) {
        container.removeAllViews()
        val inflater = LayoutInflater.from(this)
        val gap = (8 * resources.displayMetrics.density).toInt()
        for (row in rows) {
            val view = inflater.inflate(R.layout.view_detail_row, container, false)
            view.findViewById<TextView>(R.id.detail_label).setText(row.label)
            view.findViewById<TextView>(R.id.detail_value).text = row.value
            (view.layoutParams as LinearLayout.LayoutParams).topMargin = gap
            container.addView(view)
        }
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
                MaterialAlertDialogBuilder(this@ProfileActivity)
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

    companion object {
        const val EXTRA_ROLE = "role"
    }
}
