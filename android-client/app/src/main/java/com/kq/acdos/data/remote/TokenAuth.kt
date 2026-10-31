package com.kq.acdos.data.remote

import com.kq.acdos.auth.AccessTokenProvider
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route

private const val AUTHORIZATION = "Authorization"
private const val BEARER = "Bearer "

private fun Request.withBearer(token: String): Request =
    newBuilder().header(AUTHORIZATION, BEARER + token).build()

/**
 * Adds `Authorization: Bearer <access token>` to every request: the only
 * credential the backend reads. No apikey header and no publishable key.
 * Signed out, the request goes without one and the backend answers 401.
 *
 * OkHttp interceptors are not suspend functions, so the token is read with
 * runBlocking. This runs on OkHttp's own worker thread, never the main thread.
 */
class BearerTokenInterceptor(private val tokens: AccessTokenProvider) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = runBlocking { tokens.accessToken() }
        val request = chain.request()
        return chain.proceed(if (token == null) request else request.withBearer(token))
    }
}

/**
 * On a 401, refreshes the session and retries the request once.
 *
 * Refreshes are serialised by [refreshLock]: when several requests fail with
 * the same expired token, the first one refreshes and the others find the new
 * token already there and retry with it, instead of each refreshing again.
 *
 * A second 401, or a refresh that fails, gives the 401 back to the caller. It
 * never signs the user out: a session the server rejected ends through
 * supabase-kt (AuthRepository.sessionEnded).
 *
 * OkHttp only calls this for 401. A 403 (wrong role) goes straight to the caller.
 */
class TokenAuthenticator(private val tokens: AccessTokenProvider) : Authenticator {
    private val refreshLock = Mutex()

    override fun authenticate(route: Route?, response: Response): Request? {
        // Retry once: priorResponse is set when this request is already a retry.
        if (response.priorResponse != null) return null

        val failedToken = response.request.header(AUTHORIZATION)?.removePrefix(BEARER)
        val token = runBlocking {
            refreshLock.withLock {
                val current = tokens.accessToken()
                if (current != null && current != failedToken) {
                    // Another request refreshed while this one waited for the lock.
                    current
                } else {
                    tokens.refreshAccessToken()
                }
            }
        } ?: return null
        return response.request.withBearer(token)
    }
}
