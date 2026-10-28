package com.kq.acdos

import android.app.Application

class AcdosApplication : Application() {
    val container: AppContainer by lazy { AppContainer(this) }
}
