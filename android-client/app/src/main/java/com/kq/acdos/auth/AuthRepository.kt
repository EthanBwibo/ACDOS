package com.kq.acdos.auth

import kotlinx.coroutines.flow.Flow

/**
 * What the FastAPI client (#26) needs from auth: an OkHttp Interceptor adds
 * [accessToken] as the Bearer token and an Authenticator calls
 * [refreshAccessToken] on a 401. Neither touches supabase-kt or Ktor.
 */
interface AccessTokenProvider {
    /** The current access token, or null when not signed in or mid-refresh. */
    suspend fun accessToken(): String?

    /** Refreshes the session now; null if that failed. A failure never signs out. */
    suspend fun refreshAccessToken(): String?
}

/** Supabase Auth behind an interface, so routing can be unit tested with a fake. */
interface AuthRepository : AccessTokenProvider {
    /** User id of the session saved on the device, read without the network. */
    suspend fun storedSessionUserId(): String?

    suspend fun signIn(email: String, password: String): SignInResult

    /** Reads the caller's own profiles row (RLS: profiles_select_own). */
    suspend fun fetchProfile(): ProfileResult

    /** Ends the session on the server if reachable, and always on the device. */
    suspend fun signOut()

    /** Emits when the session ends: sign-out, or a refresh token the server rejected. */
    val sessionEnded: Flow<Unit>
}
