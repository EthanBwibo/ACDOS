package com.kq.acdos.ui

import android.app.Activity
import android.content.Intent
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.kq.acdos.auth.AppRole
import com.kq.acdos.auth.Profile

/** Starts a screen as a new task, so Back does not return to sign-in or start-up. */
const val NEW_CLEAR_TASK = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK

/** The placeholder home screen for each role; #27, #28 and #29 replace them. */
fun homeActivityFor(role: AppRole): Class<out Activity> = when (role) {
    AppRole.DRIVER -> DriverHomeActivity::class.java
    AppRole.CREW -> CrewHomeActivity::class.java
    AppRole.DISPATCHER -> DispatcherHomeActivity::class.java
}

fun Activity.openHome(profile: Profile) {
    startActivity(
        Intent(this, homeActivityFor(profile.role))
            .putExtra(PlaceholderHomeActivity.EXTRA_FULL_NAME, profile.fullName)
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

/** Pads [root] by the system bars and keyboard, for edge-to-edge layouts. */
fun applySystemBarPadding(root: View) {
    ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
        val type = WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime()
        val bars = insets.getInsets(type)
        v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
        insets
    }
}
