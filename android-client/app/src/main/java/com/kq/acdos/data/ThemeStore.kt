package com.kq.acdos.data

import android.app.UiModeManager
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatDelegate
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import com.kq.acdos.R
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map

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
 * it stays when someone signs out.
 */
class ThemeStore(private val store: DataStore<Preferences>) {
    /** Falls back to [ThemeMode.SYSTEM], so an unreadable file can never stop the app opening. */
    val mode: Flow<ThemeMode> = store.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { saved -> ThemeMode.entries.find { it.name == saved[KEY] } ?: ThemeMode.SYSTEM }

    suspend fun save(mode: ThemeMode) {
        store.edit { it[KEY] = mode.name }
    }

    private companion object {
        val KEY = stringPreferencesKey("theme_mode")
    }
}
