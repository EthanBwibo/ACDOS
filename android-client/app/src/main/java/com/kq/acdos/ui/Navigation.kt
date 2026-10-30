package com.kq.acdos.ui

import android.app.Activity
import android.content.Intent
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.AppContainer
import com.kq.acdos.auth.AppRole
import com.kq.acdos.auth.Profile
import com.kq.acdos.ui.driver.DriverHomeActivity
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** Starts a screen as a new task, so Back does not return to sign-in or start-up. */
const val NEW_CLEAR_TASK = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK

/** The signed-in user's name, passed to the home screen so it shows without a lookup. */
const val EXTRA_FULL_NAME = "full_name"

/** The home screen for each role. Crew and Dispatcher are still placeholders (#56, #27). */
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

fun Activity.openLogin(accountNotSetUp: Boolean = false) {
    startActivity(
        Intent(this, LoginActivity::class.java)
            .putExtra(LoginActivity.EXTRA_ACCOUNT_NOT_SET_UP, accountNotSetUp)
            .addFlags(NEW_CLEAR_TASK)
    )
}

/**
 * The one place a home screen leaves for sign-in: after Sign out (which only
 * ends the session), or when supabase-kt ends the session itself because the
 * server rejected the refresh token. Clears the user's local data first.
 */
fun AppCompatActivity.openLoginWhenSessionEnds(container: AppContainer) {
    lifecycleScope.launch {
        repeatOnLifecycle(Lifecycle.State.STARTED) {
            container.authRepository.sessionEnded.first()
            container.sessionRouter.onSessionEnded()
            openLogin()
        }
    }
}

/** Pads [root] by the system bars and keyboard, for edge-to-edge layouts. */
fun applySystemBarPadding(root: View) {
    ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
        val type = WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime()
        val bars = insets.getInsets(type)
        v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
        insets
    }
}
