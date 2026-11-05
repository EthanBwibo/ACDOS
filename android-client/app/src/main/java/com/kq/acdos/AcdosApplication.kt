package com.kq.acdos

import android.app.Application
import com.kq.acdos.ui.applyTheme
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking

class AcdosApplication : Application() {
    val container: AppContainer by lazy { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        // The one blocking call on the main thread, on purpose. DataStore can only be read
        // asynchronously, and the first activity must not draw before the mode is set, or
        // it opens in the wrong theme and flips. The read is one small file.
        val mode = runBlocking { container.themeStore.mode.first() }
        applyTheme(mode)
    }
}
