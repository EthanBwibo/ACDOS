package com.kq.acdos.ui

import android.app.UiModeManager
import android.content.Context
import android.os.Build
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.getSystemService
import androidx.lifecycle.lifecycleScope
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.color.MaterialColors
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.kq.acdos.R
import com.kq.acdos.data.ThemeMode
import com.kq.acdos.data.ThemeStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * AppCompat only changes what the app draws. The system draws an activity's starting window
 * itself, in its own theme, so with AppCompat alone a Light app on a dark phone flashes dark
 * on launch. From Android 12 the system can be told the app's choice, and it remembers it.
 */
fun Context.applyTheme(mode: ThemeMode) {
    AppCompatDelegate.setDefaultNightMode(mode.nightMode)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        getSystemService<UiModeManager>()?.setApplicationNightMode(mode.systemNightMode)
    }
}

/** System, Light or Dark. The choice is saved, then applied straight away. */
fun AppCompatActivity.showThemeDialog(store: ThemeStore) {
    lifecycleScope.launch {
        val current = store.mode.first()
        val labels = ThemeMode.entries.map { getString(it.label) }.toTypedArray()
        MaterialAlertDialogBuilder(this@showThemeDialog)
            .setTitle(R.string.action_theme)
            .setSingleChoiceItems(labels, current.ordinal) { dialog, index ->
                dialog.dismiss()
                val chosen = ThemeMode.entries[index]
                lifecycleScope.launch {
                    // In this order: applying the mode recreates the activity.
                    store.save(chosen)
                    applyTheme(chosen)
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }
}

/** SwipeRefreshLayout has no theme attributes for these; its defaults are black on white. */
fun SwipeRefreshLayout.useThemeColors() {
    setColorSchemeColors(MaterialColors.getColor(this, androidx.appcompat.R.attr.colorPrimary))
    setProgressBackgroundColorSchemeColor(
        MaterialColors.getColor(this, com.google.android.material.R.attr.colorSurfaceContainerHigh)
    )
}
