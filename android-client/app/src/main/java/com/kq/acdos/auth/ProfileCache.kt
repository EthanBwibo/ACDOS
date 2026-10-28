package com.kq.acdos.auth

import android.content.SharedPreferences
import androidx.core.content.edit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The last profile read for this device's session, so a cold start with no
 * network can still open the right role's screen.
 */
interface ProfileCache {
    /** The cached profile, only if it belongs to [userId]. */
    suspend fun get(userId: String): Profile?

    suspend fun put(profile: Profile)

    suspend fun clear()
}

class SharedPreferencesProfileCache(private val prefs: SharedPreferences) : ProfileCache {
    override suspend fun get(userId: String): Profile? = withContext(Dispatchers.IO) {
        if (prefs.getString(KEY_USER_ID, null) != userId) return@withContext null
        val role = prefs.getString(KEY_ROLE, null)?.let(AppRole::fromDb) ?: return@withContext null
        Profile(userId, role, prefs.getString(KEY_FULL_NAME, null).orEmpty())
    }

    override suspend fun put(profile: Profile) = withContext(Dispatchers.IO) {
        prefs.edit(commit = true) {
            putString(KEY_USER_ID, profile.userId)
            putString(KEY_ROLE, profile.role.dbValue)
            putString(KEY_FULL_NAME, profile.fullName)
        }
    }

    override suspend fun clear() = withContext(Dispatchers.IO) {
        prefs.edit(commit = true) { clear() }
    }

    companion object {
        /** Excluded from backups in res/xml, like the session file. */
        const val PREFS_NAME = "acdos_profile"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_ROLE = "role"
        private const val KEY_FULL_NAME = "full_name"
    }
}
