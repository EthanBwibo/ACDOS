package com.kq.acdos.ui

import android.app.Activity
import android.content.Intent
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.AppContainer
import com.kq.acdos.auth.AppRole
import com.kq.acdos.auth.Destination
import com.kq.acdos.auth.Profile
import com.kq.acdos.ui.crew.CrewHomeActivity
import com.kq.acdos.ui.dispatcher.DispatcherHomeActivity
import com.kq.acdos.ui.driver.DriverHomeActivity
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Starts a screen as a new task, so Back does not return to sign-in or start-up. */
const val NEW_CLEAR_TASK = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK

/** The signed-in user's name, passed to the home screen so it shows without a lookup. */
const val EXTRA_FULL_NAME = "full_name"

/** The home screen for each role. */
fun homeActivityFor(role: AppRole): Class<out Activity> = when (role) {
    AppRole.DRIVER -> DriverHomeActivity::class.java
    AppRole.CREW -> CrewHomeActivity::class.java
    AppRole.DISPATCHER -> DispatcherHomeActivity::class.java
}

fun Activity.openHome(profile: Profile) {
    startActivity(
        Intent(this, homeActivityFor(profile.role))
            .putExtra(EXTRA_FULL_NAME, profile.fullName)
            .addFlags(NEW_CLEAR_TASK)
    )
}

fun Activity.openLogin(accountNotSetUp: Boolean = false, roleChanged: Boolean = false) {
    startActivity(
        Intent(this, LoginActivity::class.java)
            .putExtra(LoginActivity.EXTRA_ACCOUNT_NOT_SET_UP, accountNotSetUp)
            .putExtra(LoginActivity.EXTRA_ROLE_CHANGED, roleChanged)
            .addFlags(NEW_CLEAR_TASK)
    )
}

/**
 * The one place a home screen leaves for sign-in: after Sign out (which only
 * ends the session), when supabase-kt ends the session itself because the
 * server rejected the refresh token, or when the re-check of a cached role
 * signs out (#116). Clears the user's local data first.
 *
 * Also starts that re-check, which does nothing unless Home opened from the cache.
 */
fun AppCompatActivity.openLoginWhenSessionEnds(container: AppContainer) {
    lifecycleScope.launch { container.sessionRouter.recheckCachedProfile() }
    lifecycleScope.launch {
        repeatOnLifecycle(Lifecycle.State.STARTED) {
            container.authRepository.sessionEnded.first()
            when (container.sessionRouter.onSessionEnded()) {
                Destination.AccountNotSetUp -> openLogin(accountNotSetUp = true)
                Destination.RoleChanged -> openLogin(roleChanged = true)
                else -> openLogin()
            }
        }
    }
}

/**
 * Pads an edge-to-edge screen so nothing sits under the status bar, the
 * system navigation bar or the keyboard. Every screen calls this once.
 *
 * With a [bottomBar] (the BottomNavigationView), the bar takes the bottom
 * inset itself, so its colour runs down behind the system navigation bar and
 * its labels sit right above it. [root] then has no bottom padding, unless
 * the keyboard is up, when root is padded by the keyboard and the bar by
 * nothing.
 *
 * The insets are consumed here. BottomNavigationView pads itself by the
 * bottom inset by default, so passing the insets on would add the system bar
 * height a second time: that was the empty band under the nav labels (#225).
 */
fun applySystemBarPadding(root: View, bottomBar: View? = null) {
    val barStartPadding = bottomBar?.paddingBottom ?: 0
    ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
        val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
        val keyboard = insets.getInsets(WindowInsetsCompat.Type.ime())
        val keyboardUp = keyboard.bottom > bars.bottom
        val bottom = if (keyboardUp) keyboard.bottom else bars.bottom
        if (bottomBar == null) {
            v.setPadding(bars.left, bars.top, bars.right, bottom)
        } else {
            v.setPadding(bars.left, bars.top, bars.right, if (keyboardUp) bottom else 0)
            bottomBar.updatePadding(
                bottom = barStartPadding + if (keyboardUp) 0 else bars.bottom
            )
        }
        WindowInsetsCompat.CONSUMED
    }
}
