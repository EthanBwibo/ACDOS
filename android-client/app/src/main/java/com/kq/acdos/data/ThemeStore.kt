package com.kq.acdos.data

import android.app.UiModeManager
import android.content.SharedPreferences
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.edit
import com.kq.acdos.R

/** The user's theme choice, in the order the Theme dialog lists it. */
enum class ThemeMode(
    /** What AppCompat calls this mode. */
    val nightMode: Int,
    /** What the system calls it. The two sets of constants differ for SYSTEM. */
    val systemNightMode: Int,
    @param:StringRes val label: Int
) {
    SYSTEM(
        AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM,
        UiModeManager.MODE_NIGHT_AUTO,
        R.string.theme_system
    ),
    LIGHT(AppCompatDelegate.MODE_NIGHT_NO, UiModeManager.MODE_NIGHT_NO, R.string.theme_light),
    DARK(AppCompatDelegate.MODE_NIGHT_YES, UiModeManager.MODE_NIGHT_YES, R.string.theme_dark)
}

/**
 * Saves the theme choice on this phone. It belongs to the phone rather than the user, so
 * it stays when someone signs out. SharedPreferences because [mode] has to be readable
 * synchronously in Application.onCreate, before the first activity draws.
 */
class ThemeStore(private val prefs: SharedPreferences) {
    /** [ThemeMode.SYSTEM] when nothing is saved, or the saved value is not a mode. */
    fun mode(): ThemeMode {
        val saved = prefs.getString(KEY_MODE, null)
        return ThemeMode.entries.find { it.name == saved } ?: ThemeMode.SYSTEM
    }

    fun save(mode: ThemeMode) {
        prefs.edit { putString(KEY_MODE, mode.name) }
    }

    companion object {
        const val PREFS_NAME = "acdos_theme"
        private const val KEY_MODE = "theme_mode"
    }
}
