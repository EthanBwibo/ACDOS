package com.kq.acdos

import android.app.Application
import com.kq.acdos.ui.applyTheme

class AcdosApplication : Application() {
    val container: AppContainer by lazy { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        // Before any activity draws, or the first one opens in the wrong theme and flips.
        applyTheme(container.themeStore.mode())
    }
}
