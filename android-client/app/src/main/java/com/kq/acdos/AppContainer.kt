package com.kq.acdos

import android.content.Context
import com.kq.acdos.auth.AuthRepository
import com.kq.acdos.auth.SessionRouter
import com.kq.acdos.auth.SharedPreferencesProfileCache
import com.kq.acdos.auth.SharedPreferencesSessionManager
import com.kq.acdos.auth.SupabaseAuthRepository
import com.kq.acdos.data.local.AcdosDatabase
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import io.ktor.client.engine.okhttp.OkHttp
import kotlin.time.Duration.Companion.seconds

/** Hand-wired dependencies, one per process (no DI framework). */
class AppContainer(context: Context) {
    private val appContext = context.applicationContext

    /** False in builds without a Supabase URL and key, such as CI. */
    val isConfigured: Boolean =
        BuildConfig.SUPABASE_URL.isNotBlank() && BuildConfig.SUPABASE_PUBLISHABLE_KEY.isNotBlank()

    val authRepository: AuthRepository by lazy {
        val sessionManager =
            SharedPreferencesSessionManager(prefs(SharedPreferencesSessionManager.PREFS_NAME))
        val client = createSupabaseClient(
            BuildConfig.SUPABASE_URL,
            BuildConfig.SUPABASE_PUBLISHABLE_KEY
        ) {
            httpEngine = OkHttp.create()
            // 2G/3G: the 10 s default is short for a slow handshake.
            requestTimeout = 20.seconds
            install(Auth) {
                this.sessionManager = sessionManager
                autoLoadFromStorage = true
                alwaysAutoRefresh = true
                retryDelay = 10.seconds
            }
            install(Postgrest)
        }
        SupabaseAuthRepository(client, sessionManager)
    }

    val database: AcdosDatabase by lazy { AcdosDatabase.build(appContext) }

    val sessionRouter: SessionRouter by lazy {
        SessionRouter(
            authRepository,
            SharedPreferencesProfileCache(prefs(SharedPreferencesProfileCache.PREFS_NAME)),
            database.userDataDao()
        )
    }

    private fun prefs(name: String) = appContext.getSharedPreferences(name, Context.MODE_PRIVATE)
}
