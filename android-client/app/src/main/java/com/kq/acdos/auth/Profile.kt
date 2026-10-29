package com.kq.acdos.auth

/** The three account roles in profiles.role. The app never lets the user pick one. */
enum class AppRole(val dbValue: String) {
    DISPATCHER("dispatcher"),
    DRIVER("driver"),
    CREW("crew");

    companion object {
        /** Null for a value this app version does not know. */
        fun fromDb(value: String): AppRole? = entries.firstOrNull { it.dbValue == value }
    }
}

/** The signed-in user's profiles row. */
data class Profile(val userId: String, val role: AppRole, val fullName: String)

/** Outcome of reading the signed-in user's profiles row. */
sealed interface ProfileResult {
    data class Found(val profile: Profile) : ProfileResult

    /** Signed in and the read succeeded, but there is no profiles row (or an unknown role). */
    data object Missing : ProfileResult

    /** No session any more: never signed in, signed out, or the refresh token was revoked. */
    data object NoSession : ProfileResult

    /** Could not read the row (offline, timeout, server error). The session is kept. */
    data class NetworkError(val cause: Throwable) : ProfileResult
}

sealed interface SignInResult {
    data object Success : SignInResult

    data object InvalidCredentials : SignInResult

    data object NetworkError : SignInResult

    /** Any other refusal from Supabase Auth, with its description. */
    data class Rejected(val message: String) : SignInResult
}
