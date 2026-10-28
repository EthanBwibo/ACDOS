package com.kq.acdos.auth

/** Where the app goes after start-up or sign-in. */
sealed interface Destination {
    data object Login : Destination

    data class Home(val profile: Profile) : Destination

    /** Signed in, but no profiles row: the user has been signed out again. */
    data object AccountNotSetUp : Destination

    /** Signed in, but the profile could not be read. The session is kept. */
    data object Retry : Destination
}

/**
 * Decides the destination from the stored session and profiles.role.
 * The role is never chosen by the user.
 */
class SessionRouter(private val auth: AuthRepository, private val cache: ProfileCache) {

    /**
     * On a cold start with a stored session, a cached profile for that user is
     * used straight away, so the app opens offline without waiting on the network.
     */
    suspend fun onColdStart(): Destination {
        val userId = auth.storedSessionUserId() ?: return Destination.Login
        cache.get(userId)?.let { return Destination.Home(it) }
        return resolveProfile()
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
            cache.clear()
            Destination.Login
        }

        // Keep the session: a bad network must never sign the user out.
        is ProfileResult.NetworkError -> Destination.Retry
    }

    suspend fun signOut() {
        auth.signOut()
        cache.clear()
    }
}
