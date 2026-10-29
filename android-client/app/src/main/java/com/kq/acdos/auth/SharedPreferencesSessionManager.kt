package com.kq.acdos.auth

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.jan.supabase.auth.SessionManager
import io.github.jan.supabase.auth.user.UserSession
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/**
 * Keeps the Supabase session (access and refresh token) in an app-private
 * SharedPreferences file, so it survives restarts. Chosen explicitly instead of
 * supabase-kt's default so the file has a known name, which the backup rules
 * exclude: a refresh token must not be restored onto another device.
 *
 * Not encrypted: androidx.security EncryptedSharedPreferences is deprecated,
 * and the file is readable only by this app.
 */
class SharedPreferencesSessionManager(private val prefs: SharedPreferences) : SessionManager {
    // supabase-kt requires encodeDefaults for a session to round-trip.
    private val json = Json {
        encodeDefaults = true
        ignoreUnknownKeys = true
    }

    override suspend fun saveSession(session: UserSession) = withContext(Dispatchers.IO) {
        prefs.edit(commit = true) { putString(KEY_SESSION, json.encodeToString(session)) }
    }

    override suspend fun loadSession(): UserSession = withContext(Dispatchers.IO) {
        val stored = prefs.getString(KEY_SESSION, null) ?: error("No stored session")
        json.decodeFromString<UserSession>(stored)
    }

    override suspend fun deleteSession() = withContext(Dispatchers.IO) {
        prefs.edit(commit = true) { remove(KEY_SESSION) }
    }

    companion object {
        const val PREFS_NAME = "acdos_auth"
        private const val KEY_SESSION = "session"
    }
}
