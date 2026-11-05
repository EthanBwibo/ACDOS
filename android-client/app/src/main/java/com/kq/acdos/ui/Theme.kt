package com.kq.acdos.ui

import android.app.UiModeManager
import android.content.Context
import android.os.Build
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.getSystemService
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.button.MaterialButton
import com.google.android.material.color.MaterialColors
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.progressindicator.CircularProgressIndicatorSpec
import com.google.android.material.progressindicator.IndeterminateDrawable
import com.kq.acdos.R
import com.kq.acdos.data.ThemeMode
import com.kq.acdos.data.ThemeStore

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
    val labels = ThemeMode.entries.map { getString(it.label) }.toTypedArray()
    MaterialAlertDialogBuilder(this)
        .setTitle(R.string.action_theme)
        .setSingleChoiceItems(labels, store.mode().ordinal) { dialog, index ->
            dialog.dismiss()
            val chosen = ThemeMode.entries[index]
            // In this order: applying the mode recreates the activity.
            store.save(chosen)
            applyTheme(chosen)
        }
        .setNegativeButton(R.string.action_cancel, null)
        .show()
}

/**
 * Loading shown on the button itself. It stops taking taps but stays enabled, because a
 * disabled button turns grey and the white spinner would no longer show. The caller still
 * has to ignore a repeat, because the keyboard's Done key can get past this.
 */
fun MaterialButton.showLoading(loading: Boolean, @StringRes label: Int) {
    isClickable = !loading
    setText(label)
    icon = if (loading) spinner() else null
}

private fun MaterialButton.spinner(): IndeterminateDrawable<*> {
    val spec = CircularProgressIndicatorSpec(
        context,
        null,
        0,
        com.google.android.material.R.style.Widget_Material3_CircularProgressIndicator_ExtraSmall
    )
    spec.indicatorColors = intArrayOf(currentTextColor)
    return IndeterminateDrawable.createCircularDrawable(context, spec)
}

/** SwipeRefreshLayout has no theme attributes for these; its defaults are black on white. */
fun SwipeRefreshLayout.useThemeColors() {
    setColorSchemeColors(MaterialColors.getColor(this, androidx.appcompat.R.attr.colorPrimary))
    setProgressBackgroundColorSchemeColor(
        MaterialColors.getColor(this, com.google.android.material.R.attr.colorSurfaceContainerHigh)
    )
}
