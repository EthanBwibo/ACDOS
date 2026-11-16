package com.kq.acdos

import android.app.Application
import com.kq.acdos.ui.applyTheme
import org.osmdroid.config.Configuration

open class AcdosApplication : Application() {
    open val container: AppContainer by lazy { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        // Before any activity draws, or the first one opens in the wrong theme and flips.
        applyTheme(container.themeStore.mode())
        // The route map's tiles come from OpenStreetMap, whose tile policy asks
        // every app to identify itself. The default tile cache stays on, so tiles
        // already seen show again on 2G/3G or with no signal.
        Configuration.getInstance().apply {
            load(this@AcdosApplication, getSharedPreferences("osmdroid", MODE_PRIVATE))
            userAgentValue = BuildConfig.APPLICATION_ID
        }
    }
}
