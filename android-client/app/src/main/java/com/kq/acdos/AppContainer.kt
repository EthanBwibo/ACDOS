package com.kq.acdos

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.core.handlers.ReplaceFileCorruptionHandler
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.preferencesDataStore
import com.kq.acdos.auth.AuthRepository
import com.kq.acdos.auth.SessionRouter
import com.kq.acdos.auth.SharedPreferencesProfileCache
import com.kq.acdos.auth.SharedPreferencesSessionManager
import com.kq.acdos.auth.SupabaseAuthRepository
import com.kq.acdos.data.CrewPickupRepository
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.DriverRouteRepository
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.ThemeStore
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.outbox.ApiPickupEventUploader
import com.kq.acdos.data.outbox.BatchResult
import com.kq.acdos.data.outbox.PickupEventOutbox
import com.kq.acdos.data.outbox.PickupEventUploader
import com.kq.acdos.data.remote.ApiClient
import com.kq.acdos.data.remote.DispatcherApi
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.MessagesApi
import com.kq.acdos.data.remote.OptimisationJobsApi
import io.github.jan.supabase.auth.Auth
import io.github.jan.supabase.createSupabaseClient
import io.github.jan.supabase.postgrest.Postgrest
import io.ktor.client.engine.okhttp.OkHttp
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import retrofit2.create

private val Context.themeDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "theme",
    corruptionHandler = ReplaceFileCorruptionHandler { emptyPreferences() }
)

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

    /** False in builds without an API base URL, such as CI. */
    val isApiConfigured: Boolean = BuildConfig.API_BASE_URL.isNotBlank()

    // The FastAPI backend, authenticated with the Supabase access token.
    private val retrofit by lazy {
        ApiClient.retrofit(BuildConfig.API_BASE_URL, ApiClient.okHttp(authRepository))
    }

    val optimisationJobsApi: OptimisationJobsApi by lazy { retrofit.create() }

    val meApi: MeApi by lazy { retrofit.create() }

    val dispatcherApi: DispatcherApi by lazy { retrofit.create() }

    val messagesApi: MessagesApi by lazy { retrofit.create() }

    /** Null without an API URL; the dispatcher screen then shows nothing. */
    val dispatchRepository: DispatchRepository? by lazy {
        if (isApiConfigured) DispatchRepository(dispatcherApi, optimisationJobsApi) else null
    }

    val database: AcdosDatabase by lazy { AcdosDatabase.build(appContext) }

    /** One per process, so its 60 s throttle holds across screens. Null without an API URL. */
    val driverRouteRepository: DriverRouteRepository? by lazy {
        if (isApiConfigured) DriverRouteRepository(meApi, database.driverRouteDao()) else null
    }

    /** Without an API URL, events are recorded but wait on the phone. */
    val pickupEventOutbox: PickupEventOutbox by lazy {
        val uploader = if (isApiConfigured) {
            ApiPickupEventUploader(meApi)
        } else {
            PickupEventUploader { BatchResult.Retry }
        }
        PickupEventOutbox(
            database.pendingPickupEventDao(),
            uploader,
            currentUserId = { authRepository.storedSessionUserId() }
        )
    }

    /** Outlives screens, so an upload started by a tap finishes after the driver moves on. */
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Starts uploading the signed-in driver's pending pickup events; returns at once. */
    fun uploadPickupEvents() {
        appScope.launch { pickupEventOutbox.uploadPending() }
    }

    /** Null without an API URL; the Pickup tab then shows only the cache. */
    val crewPickupRepository: CrewPickupRepository? by lazy {
        if (isApiConfigured) CrewPickupRepository(meApi, database.crewDao()) else null
    }

    /** Null without an API URL; the Message tab then lists only cached presets. */
    val messagesRepository: MessagesRepository? by lazy {
        if (isApiConfigured) MessagesRepository(messagesApi, database.crewDao()) else null
    }

    val themeStore: ThemeStore by lazy { ThemeStore(appContext.themeDataStore) }

    val sessionRouter: SessionRouter by lazy {
        SessionRouter(
            authRepository,
            SharedPreferencesProfileCache(prefs(SharedPreferencesProfileCache.PREFS_NAME)),
            database.userDataDao()
        )
    }

    private fun prefs(name: String) = appContext.getSharedPreferences(name, Context.MODE_PRIVATE)
}
