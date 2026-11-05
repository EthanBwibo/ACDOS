package com.kq.acdos.data

import android.app.UiModeManager
import android.content.Context
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.edit
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ThemeStoreTest {
    private val prefs = ApplicationProvider.getApplicationContext<Context>()
        .getSharedPreferences(ThemeStore.PREFS_NAME, Context.MODE_PRIVATE)

    @Test
    fun `nothing saved means follow the system`() {
        assertEquals(ThemeMode.SYSTEM, ThemeStore(prefs).mode())
    }

    @Test
    fun `a saved choice reads back from a new store`() {
        ThemeStore(prefs).save(ThemeMode.DARK)

        assertEquals(ThemeMode.DARK, ThemeStore(prefs).mode())
    }

    @Test
    fun `a saved choice can be changed`() {
        val store = ThemeStore(prefs)
        store.save(ThemeMode.DARK)

        store.save(ThemeMode.LIGHT)

        assertEquals(ThemeMode.LIGHT, store.mode())
    }

    @Test
    fun `an unknown saved value means follow the system`() {
        prefs.edit { putString("theme_mode", "SEPIA") }

        assertEquals(ThemeMode.SYSTEM, ThemeStore(prefs).mode())
    }

    @Test
    fun `each choice maps to its night mode`() {
        assertEquals(AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM, ThemeMode.SYSTEM.nightMode)
        assertEquals(AppCompatDelegate.MODE_NIGHT_NO, ThemeMode.LIGHT.nightMode)
        assertEquals(AppCompatDelegate.MODE_NIGHT_YES, ThemeMode.DARK.nightMode)
        assertEquals(UiModeManager.MODE_NIGHT_AUTO, ThemeMode.SYSTEM.systemNightMode)
        assertEquals(UiModeManager.MODE_NIGHT_NO, ThemeMode.LIGHT.systemNightMode)
        assertEquals(UiModeManager.MODE_NIGHT_YES, ThemeMode.DARK.systemNightMode)
    }
}
