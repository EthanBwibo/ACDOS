package com.kq.acdos.data

import android.app.UiModeManager
import androidx.appcompat.app.AppCompatDelegate
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ThemeStoreTest {
    @get:Rule
    val folder = TemporaryFolder()

    private fun dataStore() = PreferenceDataStoreFactory.create {
        folder.newFile("theme.preferences_pb").also { it.delete() }
    }

    /** A DataStore whose file can't be read. */
    private object Unreadable : DataStore<Preferences> {
        override val data: Flow<Preferences> = flow { throw IOException("disk") }

        override suspend fun updateData(
            transform: suspend (t: Preferences) -> Preferences
        ): Preferences = throw IOException("disk")
    }

    @Test
    fun `nothing saved means follow the system`() = runBlocking {
        assertEquals(ThemeMode.SYSTEM, ThemeStore(dataStore()).mode.first())
    }

    @Test
    fun `a saved choice reads back`() = runBlocking {
        val store = ThemeStore(dataStore())

        store.save(ThemeMode.DARK)

        assertEquals(ThemeMode.DARK, store.mode.first())
    }

    @Test
    fun `an unknown saved value means follow the system`() = runBlocking {
        val data = dataStore()
        data.edit { it[stringPreferencesKey("theme_mode")] = "SEPIA" }

        assertEquals(ThemeMode.SYSTEM, ThemeStore(data).mode.first())
    }

    @Test
    fun `an unreadable file still opens the app`() = runBlocking {
        assertEquals(ThemeMode.SYSTEM, ThemeStore(Unreadable).mode.first())
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
