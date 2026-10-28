package com.kq.acdos.auth

import android.util.Log
import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.auth.SessionManager
import io.github.jan.supabase.auth.auth
import io.github.jan.supabase.auth.exception.AuthErrorCode
import io.github.jan.supabase.auth.exception.AuthRestException
import io.github.jan.supabase.auth.providers.builtin.Email
import io.github.jan.supabase.auth.status.SessionStatus
import io.github.jan.supabase.exceptions.HttpRequestException
import io.github.jan.supabase.exceptions.RestException
import io.github.jan.supabase.postgrest.from
import io.github.jan.supabase.postgrest.query.Columns
import kotlin.coroutines.cancellation.CancellationException
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * [AuthRepository] on supabase-kt. Token refresh is supabase-kt's: on a network
 * or 5xx error it keeps the session and retries every retryDelay; it clears the
 * session only when the server rejects the refresh token (4xx).
 */
class SupabaseAuthRepository(
    private val client: SupabaseClient,
    private val sessionManager: SessionManager
) : AuthRepository {

    @Serializable
    private data class ProfileRow(val role: String, @SerialName("full_name") val fullName: String)

    override suspend fun storedSessionUserId(): String? =
        sessionManager.loadSessionOrNull()?.user?.id

    override suspend fun signIn(email: String, password: String): SignInResult = try {
        client.auth.signInWith(Email) {
            this.email = email
            this.password = password
        }
        SignInResult.Success
    } catch (e: AuthRestException) {
        if (e.errorCode == AuthErrorCode.InvalidCredentials) {
            SignInResult.InvalidCredentials
        } else {
            SignInResult.Rejected(e.errorDescription)
        }
    } catch (e: HttpRequestException) {
        Log.w(TAG, "Sign-in could not reach Supabase", e)
        SignInResult.NetworkError
    } catch (e: RestException) {
        SignInResult.Rejected(e.description ?: e.error)
    }

    override suspend fun fetchProfile(): ProfileResult {
        // Wait for supabase-kt to load (and maybe refresh) the stored session.
        // Offline that can take indefinitely, so give up and let the user retry.
        // Without a session PostgREST falls back to the publishable key and RLS
        // returns no rows, which must not be read as "no profiles row".
        val status = withTimeoutOrNull(SESSION_WAIT) {
            client.auth.awaitInitialization()
            client.auth.sessionStatus.value
        } ?: return networkError("Session still loading")

        val session = when (status) {
            is SessionStatus.Authenticated -> status.session
            is SessionStatus.NotAuthenticated -> return ProfileResult.NoSession
            else -> return networkError("Session not usable: $status")
        }
        val userId = session.user?.id ?: return networkError("Session has no user")

        return try {
            val row = client.from("profiles")
                .select(Columns.list("role", "full_name")) { filter { eq("id", userId) } }
                .decodeSingleOrNull<ProfileRow>()
            val role = row?.let { AppRole.fromDb(it.role) }
            if (row == null || role == null) {
                ProfileResult.Missing
            } else {
                ProfileResult.Found(Profile(userId, role, row.fullName))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "Could not read profiles", e)
            ProfileResult.NetworkError(e)
        }
    }

    override suspend fun signOut() {
        try {
            client.auth.signOut()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // supabase-kt clears the local session only after the server call
            // succeeds, so offline it would stay signed in. Clear it here; the
            // refresh token then expires unused on the server.
            Log.w(TAG, "Server sign-out failed, clearing the local session", e)
            client.auth.clearSession()
        }
    }

    override val sessionEnded: Flow<Unit> =
        client.auth.sessionStatus.filterIsInstance<SessionStatus.NotAuthenticated>().map { }

    override suspend fun accessToken(): String? = client.auth.currentAccessTokenOrNull()

    override suspend fun refreshAccessToken(): String? = try {
        client.auth.refreshCurrentSession()
        client.auth.currentAccessTokenOrNull()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Log.w(TAG, "Token refresh failed, keeping the session", e)
        null
    }

    private fun networkError(reason: String) =
        ProfileResult.NetworkError(IllegalStateException(reason))

    private companion object {
        const val TAG = "SupabaseAuth"
        val SESSION_WAIT = 15.seconds
    }
}
