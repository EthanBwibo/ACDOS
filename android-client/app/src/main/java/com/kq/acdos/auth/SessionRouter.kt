package com.kq.acdos.auth

import com.kq.acdos.data.local.UserDataStore

/** Where the app goes after start-up or sign-in. */
sealed interface Destination {
    data object Login : Destination

    data class Home(val profile: Profile) : Destination

    /** Signed in, but no profiles row: the user has been signed out again. */
    data object AccountNotSetUp : Destination

    /** Signed in, but the profile could not be read. The session is kept. */
    data object Retry : Destination

    /** Opened from the cached role, which the server no longer has: signed out (#116). */
    data object RoleChanged : Destination
}

/**
 * Decides the destination from the stored session and profiles.role.
 * The role is never chosen by the user. Whenever the session ends, the cached
 * profile and the user's local data ([userData]) go with it, so the next user
 * on this phone sees none of it.
 */
class SessionRouter(
    private val auth: AuthRepository,
    private val cache: ProfileCache,
    private val userData: UserDataStore
) {

    /** The cached profile Home was opened from, until [recheckCachedProfile] settles it. */
    private var unchecked: Profile? = null

    /** Why the session was ended here, for the sign-in screen; read by [onSessionEnded]. */
    private var endedBecause: Destination = Destination.Login

    /**
     * On a cold start with a stored session, a cached profile for that user is
     * used straight away, so the app opens offline without waiting on the network.
     * The home screen then re-checks it with [recheckCachedProfile].
     */
    suspend fun onColdStart(): Destination {
        val userId = auth.storedSessionUserId() ?: return Destination.Login
        cache.get(userId)?.let {
            unchecked = it
            return Destination.Home(it)
        }
        return resolveProfile()
    }

    /**
     * After Home opened from the cache, reads profiles.role again (#116). The same role
     * refreshes the cache. A changed role or a removed row signs out, and the home screen's
     * session watcher then opens sign-in with the reason ([onSessionEnded]). Only signing
     * out navigates, so there is one way off a home screen.
     *
     * A network error changes nothing and leaves the check for the next home screen to
     * start, as does cancellation (a rotation). Does nothing if Home wasn't opened from the
     * cache, or the check is already settled.
     */
    suspend fun recheckCachedProfile() {
        val cached = unchecked ?: return
        when (val result = auth.fetchProfile()) {
            is ProfileResult.Found -> {
                unchecked = null
                if (result.profile.role == cached.role) {
                    cache.put(result.profile)
                } else {
                    signOut(because = Destination.RoleChanged)
                }
            }

            ProfileResult.Missing -> {
                unchecked = null
                signOut(because = Destination.AccountNotSetUp)
            }

            // supabase-kt ended the session itself; the session watcher handles that.
            ProfileResult.NoSession -> unchecked = null

            // Keep the session and the cached role: a bad network must never sign out.
            is ProfileResult.NetworkError -> Unit
        }
    }

    /** Reads profiles.role: after sign-in, and when the user taps Retry. */
    suspend fun resolveProfile(): Destination = when (val result = auth.fetchProfile()) {
        is ProfileResult.Found -> {
            cache.put(result.profile)
            Destination.Home(result.profile)
        }

        ProfileResult.Missing -> {
            signOut()
            Destination.AccountNotSetUp
        }

        ProfileResult.NoSession -> {
            clearLocalData()
            Destination.Login
        }

        // Keep the session: a bad network must never sign the user out.
        is ProfileResult.NetworkError -> Destination.Retry
    }

    suspend fun signOut() = signOut(because = Destination.Login)

    private suspend fun signOut(because: Destination) {
        // Before auth.signOut(), which ends the session and so wakes the session watcher.
        endedBecause = because
        unchecked = null
        auth.signOut()
        clearLocalData()
    }

    /**
     * The session ended without the user signing out here, e.g. the server
     * rejected the refresh token. Also runs after [signOut], since the Home
     * screen calls it whenever the session ends; clearing twice is harmless.
     *
     * Returns where to go: [Destination.Login], or [Destination.AccountNotSetUp] or
     * [Destination.RoleChanged] when [recheckCachedProfile] signed out, so the
     * sign-in screen can say why.
     */
    suspend fun onSessionEnded(): Destination {
        clearLocalData()
        return endedBecause.also { endedBecause = Destination.Login }
    }

    /** Unsynced pickup events are kept: see UserDataDao.clearUserData. */
    private suspend fun clearLocalData() {
        cache.clear()
        userData.clearUserData()
    }
}
